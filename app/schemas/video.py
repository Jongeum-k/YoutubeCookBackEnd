# app/schemas/video.py

from pydantic import BaseModel, HttpUrl


class BasicInfo(BaseModel):
    title: str
    description: str | None = None
    servings: str | None = None
    cuisine: str | None = None


class Ingredient(BaseModel):
    name: str
    amount: str | None = None
    unit: str | None = None
    note: str | None = None


class CookingStep(BaseModel):
    order: int
    instruction: str

    start_seconds: int | None = None
    end_seconds: int | None = None

    temperature: str | None = None
    duration: str | None = None


class RecipeAnalysis(BaseModel):
    basic_info: BasicInfo
    ingredients: list[Ingredient]
    steps: list[CookingStep]
    tips: list[str] = []


class AnalyzeVideoRequest(BaseModel):
    tester_key: str
    youtube_url: HttpUrl