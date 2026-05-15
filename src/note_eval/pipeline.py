from __future__ import annotations

import operator
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from langgraph.constants import Send
from langgraph.graph import END, StateGraph

from . import aggregation
from .agents import monthly as monthly_agent
from .agents import recent as recent_agent
from .agents import scorer as scorer_agent
from .agents import trend as trend_agent
from .llm import LLMClient
from .schemas.note import Note
from .schemas.report import AuthorReport, EventTypeReport
from .schemas.rubric import Rubric
from .schemas.score import Score
from .schemas.summary import MonthlySummary, RecentSummary, Trend
from .storage.cache import Cache


class PipelineState(TypedDict, total=False):
    notes: list[Note]
    rubric: Rubric
    scores: list[Score]
    monthly_summaries: Annotated[list[MonthlySummary], operator.add]
    trends: Annotated[list[Trend], operator.add]
    recents: Annotated[list[RecentSummary], operator.add]
    reports: dict[str, AuthorReport]
    now: datetime


def _build_graph(llm: LLMClient, cache: Cache):
    def score_node(state: PipelineState) -> dict[str, Any]:
        scores = scorer_agent.score_notes(state["notes"], state["rubric"], llm, cache)
        return {"scores": scores}

    def route_to_monthly(state: PipelineState) -> list[Send]:
        scores = state["scores"]
        rubric = state["rubric"]
        notes_by_id = {n.note_id: n for n in state["notes"]}
        groups: dict[tuple[str, str, str], list[Score]] = {}
        for s in scores:
            mk = aggregation.month_key(
                datetime.fromisoformat(s.occurred_at.replace("Z", "+00:00"))
            )
            groups.setdefault((s.author_id, s.event_type, mk), []).append(s)
        sends: list[Send] = []
        for (author_id, event_type, month), group_scores in groups.items():
            relevant_note_ids = {s.note_id for s in group_scores}
            sends.append(
                Send(
                    "monthly_node",
                    {
                        "author_id": author_id,
                        "event_type": event_type,
                        "month": month,
                        "scores": group_scores,
                        "notes_by_id": {nid: notes_by_id[nid] for nid in relevant_note_ids if nid in notes_by_id},
                        "rubric": rubric,
                    },
                )
            )
        if not sends:
            sends.append(Send("monthly_skip", {}))
        return sends

    def monthly_node(payload: dict[str, Any]) -> dict[str, Any]:
        summary = monthly_agent.summarize_month(
            author_id=payload["author_id"],
            event_type=payload["event_type"],
            month=payload["month"],
            scores=payload["scores"],
            notes_by_id=payload["notes_by_id"],
            rubric=payload["rubric"],
            llm=llm,
        )
        return {"monthly_summaries": [summary]}

    def monthly_skip(_: dict[str, Any]) -> dict[str, Any]:
        return {"monthly_summaries": []}

    def route_to_trend_recent(state: PipelineState) -> list[Send]:
        scores_by_pair: dict[tuple[str, str], list[Score]] = {}
        for s in state["scores"]:
            scores_by_pair.setdefault((s.author_id, s.event_type), []).append(s)

        ms_by_pair: dict[tuple[str, str], list[MonthlySummary]] = {}
        for ms in state.get("monthly_summaries", []):
            ms_by_pair.setdefault((ms.author_id, ms.event_type), []).append(ms)

        sends: list[Send] = []
        for (author_id, event_type), summaries in ms_by_pair.items():
            sends.append(
                Send(
                    "trend_node",
                    {
                        "author_id": author_id,
                        "event_type": event_type,
                        "monthly_summaries": summaries,
                    },
                )
            )
            sends.append(
                Send(
                    "recent_node",
                    {
                        "author_id": author_id,
                        "event_type": event_type,
                        "monthly_summaries": summaries,
                        "scores": scores_by_pair.get((author_id, event_type), []),
                        "now": state["now"],
                    },
                )
            )
        if not sends:
            sends.append(Send("branches_skip", {}))
        return sends

    def trend_node(payload: dict[str, Any]) -> dict[str, Any]:
        result = trend_agent.analyze_trend(
            author_id=payload["author_id"],
            event_type=payload["event_type"],
            monthly_summaries=payload["monthly_summaries"],
            llm=llm,
        )
        return {"trends": [result]}

    def recent_node(payload: dict[str, Any]) -> dict[str, Any]:
        result = recent_agent.summarize_recent(
            author_id=payload["author_id"],
            event_type=payload["event_type"],
            monthly_summaries=payload["monthly_summaries"],
            scores=payload["scores"],
            now=payload["now"],
            llm=llm,
        )
        return {"recents": [result]}

    def branches_skip(_: dict[str, Any]) -> dict[str, Any]:
        return {"trends": [], "recents": []}

    def assemble_node(state: PipelineState) -> dict[str, Any]:
        rubric_version = state["rubric"].version
        generated_at = datetime.now(UTC).isoformat()

        monthly_by_pair: dict[tuple[str, str], list[MonthlySummary]] = {}
        for ms in state.get("monthly_summaries", []):
            monthly_by_pair.setdefault((ms.author_id, ms.event_type), []).append(ms)

        trends_by_pair: dict[tuple[str, str], Trend] = {
            (t.author_id, t.event_type): t for t in state.get("trends", [])
        }
        recents_by_pair: dict[tuple[str, str], RecentSummary] = {
            (r.author_id, r.event_type): r for r in state.get("recents", [])
        }

        scores_by_pair: dict[tuple[str, str], list[Score]] = {}
        for s in state["scores"]:
            scores_by_pair.setdefault((s.author_id, s.event_type), []).append(s)

        reports: dict[str, AuthorReport] = {}
        authors = {ms.author_id for ms in state.get("monthly_summaries", [])} | {
            s.author_id for s in state["scores"]
        }
        for author_id in authors:
            by_event_type: dict[str, EventTypeReport] = {}
            for (a, et), monthly_list in monthly_by_pair.items():
                if a != author_id:
                    continue
                trend_obj = trends_by_pair.get((a, et))
                recent_obj = recents_by_pair.get((a, et))
                if trend_obj is None or recent_obj is None:
                    continue
                by_event_type[et] = EventTypeReport(
                    event_type=et,
                    monthly_summaries=sorted(monthly_list, key=lambda m: m.month),
                    trend=trend_obj,
                    last_30_days=recent_obj,
                    score_table=scores_by_pair.get((a, et), []),
                )
            if by_event_type:
                reports[author_id] = AuthorReport(
                    author_id=author_id,
                    rubric_version=rubric_version,
                    generated_at=generated_at,
                    by_event_type=by_event_type,
                )
        return {"reports": reports}

    graph = StateGraph(PipelineState)
    graph.add_node("score_node", score_node)
    graph.add_node("monthly_node", monthly_node)
    graph.add_node("monthly_skip", monthly_skip)
    graph.add_node("trend_node", trend_node)
    graph.add_node("recent_node", recent_node)
    graph.add_node("branches_skip", branches_skip)
    graph.add_node("assemble_node", assemble_node)

    graph.set_entry_point("score_node")
    graph.add_conditional_edges("score_node", route_to_monthly, ["monthly_node", "monthly_skip"])
    graph.add_conditional_edges(
        "monthly_node",
        route_to_trend_recent,
        ["trend_node", "recent_node", "branches_skip"],
    )
    graph.add_conditional_edges(
        "monthly_skip",
        route_to_trend_recent,
        ["trend_node", "recent_node", "branches_skip"],
    )
    graph.add_edge("trend_node", "assemble_node")
    graph.add_edge("recent_node", "assemble_node")
    graph.add_edge("branches_skip", "assemble_node")
    graph.add_edge("assemble_node", END)
    return graph.compile()


def run_pipeline(
    notes: list[Note],
    rubric: Rubric,
    llm: LLMClient,
    cache: Cache,
    now: datetime,
) -> dict[str, AuthorReport]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    app = _build_graph(llm, cache)
    initial: dict[str, Any] = {
        "notes": notes,
        "rubric": rubric,
        "scores": [],
        "monthly_summaries": [],
        "trends": [],
        "recents": [],
        "reports": {},
        "now": now,
    }
    final = app.invoke(initial)
    return final["reports"]
