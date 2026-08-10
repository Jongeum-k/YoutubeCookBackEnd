# app/services/gemini.py

from collections.abc import AsyncIterator

from google import genai
from google.genai import types

from app.core.config import get_settings
from app.schemas.video import RecipeAnalysis


class GeminiService:
    def __init__(self) -> None:
        settings = get_settings()

        self.model = settings.gemini_model

        self.client = genai.Client(
            api_key=settings.gemini_api_key,
        )

    def analyze_cooking_text(self, text: str) -> str:
        prompt = f"""
You are a cooking-video analysis assistant.

Analyze the following cooking transcript and return:

1. Recipe title
2. Ingredients
3. Cooking steps
4. Important temperatures and cooking times
5. Optional tips or substitutions

Transcript:
{text}
""".strip()

        interaction = self.client.interactions.create(
            model=self.model,
            input=prompt,
            store=False,
            generation_config={
                "thinking_level": "low",
            },
        )

        if not interaction.output_text:
            raise RuntimeError("Gemini returned an empty response.")

        return interaction.output_text

    async def analyze_cooking_video_stream(
        self,
        youtube_url: str,
    ) -> AsyncIterator[str]:
        prompt = """
Analyze this cooking video and extract the recipe.

Return only information that can reasonably be inferred from the video.

Requirements:

- basic_info
    - recipe title
    - short description
    - servings if mentioned or clearly inferable
    - cuisine if identifiable

- ingredients
    - ingredient name
    - amount
    - unit
    - optional notes

- steps
    - ordered cooking instructions
    - approximate video timestamps when possible
    - temperatures
    - cooking durations

- tips
    - useful cooking tips or substitutions mentioned in the video

Do not invent exact quantities, temperatures, or times
when they are not present or reasonably inferable.
""".strip()

        contents = types.Content(
            parts=[
                types.Part(
                    file_data=types.FileData(
                        file_uri=youtube_url,
                    ),
                ),
                types.Part(text=prompt),
            ]
        )

        stream = await self.client.aio.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_schema": RecipeAnalysis,
            },
        )

        async for chunk in stream:
            if chunk.text:
                yield chunk.text