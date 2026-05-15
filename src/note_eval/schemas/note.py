from datetime import datetime

from pydantic import BaseModel


class Note(BaseModel):
    note_id: str
    author_id: str
    subject_id: str
    event_type: str
    occurred_at: datetime
    text: str
