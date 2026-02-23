from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class TranscriptionBase(BaseModel):
    filename: str
    content: str
    orig_language: str = "RU"
    translate_to: Optional[str] = None
    file_size: Optional[int] = None


class TranscriptionCreate(TranscriptionBase):
    pass


class Transcription(TranscriptionBase):
    id: int
    user_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TranscriptionList(BaseModel):
    transcriptions: List[Transcription]
    total: int
    skip: int
    limit: int


class TranscriptionDeleteResponse(BaseModel):
    success: bool
    message: str
