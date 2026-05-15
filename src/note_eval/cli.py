from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .agents.scorer import score_notes
from .ingestion import generate_synthetic, load_notes, load_rubric
from .llm import LiveOpenAIClient, MockLLMClient
from .pipeline import run_pipeline
from .storage.cache import Cache


def _get_llm(mode: str | None):
    resolved = mode or os.getenv("NOTE_EVAL_LLM_MODE", "mock")
    if resolved == "live":
        return LiveOpenAIClient()
    return MockLLMClient()


def cmd_run(args: argparse.Namespace) -> int:
    notes = load_notes(args.notes)
    rubric = load_rubric(args.rubric)
    llm = _get_llm(args.llm_mode)
    cache = Cache(args.cache_dir)
    now = datetime.now(UTC) if args.now is None else datetime.fromisoformat(args.now)

    reports = run_pipeline(notes, rubric, llm, cache, now)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for author_id, report in reports.items():
        path = out_dir / f"{author_id}.json"
        path.write_text(report.model_dump_json(indent=2))
        print(f"wrote {path}")
    return 0


def _kappa(pairs: list[tuple[int, int]], n_classes: int = 3) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    counts_a = [0] * n_classes
    counts_b = [0] * n_classes
    for a, b in pairs:
        counts_a[a] += 1
        counts_b[b] += 1
    pe = sum((counts_a[c] / n) * (counts_b[c] / n) for c in range(n_classes))
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def cmd_calibrate(args: argparse.Namespace) -> int:
    notes = load_notes(args.notes)
    rubric = load_rubric(args.rubric)
    llm = _get_llm(args.llm_mode)
    cache = Cache(args.cache_dir)

    predicted = score_notes(notes, rubric, llm, cache)
    pred_index = {(s.note_id, s.rubric_item_id): s.score for s in predicted}

    truth_raw = json.loads(Path(args.truth).read_text())
    by_item: dict[str, dict[str, list]] = {}
    for entry in truth_raw:
        key = (entry["note_id"], entry["rubric_item_id"])
        if key not in pred_index:
            continue
        item_stats = by_item.setdefault(
            entry["rubric_item_id"],
            {"exact": [], "within1": [], "numeric_pairs": []},
        )
        pred = pred_index[key]
        truth = entry["score"]
        item_stats["exact"].append(pred == truth)
        if isinstance(pred, int) and isinstance(truth, int):
            item_stats["within1"].append(abs(pred - truth) <= 1)
            item_stats["numeric_pairs"].append((pred, truth))
        else:
            item_stats["within1"].append(pred == truth)

    report: dict[str, dict] = {}
    for item_id, stats in by_item.items():
        n = len(stats["exact"])
        report[item_id] = {
            "n": n,
            "exact_match_rate": sum(stats["exact"]) / n if n else None,
            "within_plus_minus_1_rate": sum(stats["within1"]) / n if n else None,
            "cohen_kappa": _kappa(stats["numeric_pairs"]),
        }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"wrote {out_path}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    path = generate_synthetic(
        authors=args.authors,
        days=args.days,
        out_dir=args.out,
        seed=args.seed,
        rubric_path=args.rubric,
    )
    print(f"wrote {path}")
    return 0


def _add_llm_mode(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--llm-mode",
        choices=["mock", "live"],
        default=None,
        help="Override NOTE_EVAL_LLM_MODE env (default: mock).",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="note-eval")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run the full pipeline")
    run_p.add_argument("--notes", required=True)
    run_p.add_argument("--rubric", required=True)
    run_p.add_argument("--out", required=True)
    run_p.add_argument("--cache-dir", default=".cache")
    run_p.add_argument("--now", default=None, help="ISO 8601 'now' anchor (default: current UTC)")
    _add_llm_mode(run_p)
    run_p.set_defaults(func=cmd_run)

    cal_p = sub.add_parser("calibrate", help="Compare scorer against ground truth")
    cal_p.add_argument("--truth", required=True)
    cal_p.add_argument("--notes", required=True)
    cal_p.add_argument("--rubric", required=True)
    cal_p.add_argument("--out", default="calibration.json")
    cal_p.add_argument("--cache-dir", default=".cache")
    _add_llm_mode(cal_p)
    cal_p.set_defaults(func=cmd_calibrate)

    gen_p = sub.add_parser("generate", help="Generate synthetic notes")
    gen_p.add_argument("--authors", type=int, required=True)
    gen_p.add_argument("--days", type=int, required=True)
    gen_p.add_argument("--out", required=True)
    gen_p.add_argument("--seed", type=int, default=None)
    gen_p.add_argument("--rubric", default="data/rubric.json")
    gen_p.set_defaults(func=cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
