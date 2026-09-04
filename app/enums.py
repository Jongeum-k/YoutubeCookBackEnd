# app/enums.py

from enum import StrEnum


class VideoAnalysisStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"


class GeminiRequestStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"