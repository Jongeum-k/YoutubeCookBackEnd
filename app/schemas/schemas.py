from pydantic import BaseModel, Field


class AnalyzeTextRequest(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=100_000,
        description="Cooking video transcript or recipe-related text",
    )


class AnalyzeTextResponse(BaseModel):
    result: str
    model: str