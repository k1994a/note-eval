from pydantic import BaseModel


class RubricAnchors(BaseModel):
    score_0: str
    score_1: str
    score_2: str


class RubricItem(BaseModel):
    id: str
    name: str
    description: str
    applies_to_event_types: list[str]
    anchors: RubricAnchors


class Rubric(BaseModel):
    version: str
    items: list[RubricItem]

    def items_for_event_type(self, event_type: str) -> list[RubricItem]:
        return [i for i in self.items if event_type in i.applies_to_event_types]

    def event_types(self) -> list[str]:
        seen: list[str] = []
        for item in self.items:
            for et in item.applies_to_event_types:
                if et not in seen:
                    seen.append(et)
        return seen
