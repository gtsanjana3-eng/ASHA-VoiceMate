"""Request bodies accepted by the API. Pydantic checks every input before use."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

LANG_PATTERN = r"^[a-z]{2}-[A-Z]{2}$"


class StartSessionRequest(BaseModel):
    language: str = Field(default="en-IN", pattern=LANG_PATTERN)


class UtteranceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    # "stt" = came from Gnani speech-to-text, "typed" = test input box,
    # "replay" = restoring an unsaved draft. Shown in the transcript panel.
    source: Literal["stt", "typed", "replay"] = "typed"


class LanguageRequest(BaseModel):
    language: str = Field(pattern=LANG_PATTERN)


class SaveRequest(BaseModel):
    client_request_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9-]+$")


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="en-IN", pattern=LANG_PATTERN)
