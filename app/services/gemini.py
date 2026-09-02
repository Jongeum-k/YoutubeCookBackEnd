# app/services/gemini.py

from collections.abc import AsyncIterator

from google import genai
from google.genai import types

from app.core.config import get_settings
from app.dtos.gemini import GeminiStreamChunk, GeminiUsage
from app.schemas.video import RecipeAnalysis

_LANGUAGE_NAMES = {
    "ko": "Korean",
    "en": "English",
}


class GeminiService:
    def __init__(self) -> None:
        settings = get_settings()

        self.model = settings.gemini_model
        self.translation_model = settings.gemini_translation_model

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
    ) -> AsyncIterator[GeminiStreamChunk]:
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

        async for chunk in self._generate_structured_stream(
            model=self.model,
            contents=contents,
        ):
            yield chunk

    async def translate_recipe_stream(
        self,
        recipe: RecipeAnalysis,
        *,
        target_language: str,
    ) -> AsyncIterator[GeminiStreamChunk]:
        """Translate an already-extracted recipe into another language.

        No video is attached -- this only re-expresses existing text
        in another language, it does not re-analyze the source video.
        """
        language_name = _LANGUAGE_NAMES.get(
            target_language,
            target_language,
        )

        prompt = f"""
Translate the following cooking recipe into {language_name}.

Keep the structure identical to the source: the same number of
ingredients in the same order, and the same number of steps in the
same order. Only translate natural-language text -- titles,
descriptions, ingredient names/notes, step instructions,
temperatures, durations, and tips.

Copy every numeric/timing field through unchanged (ingredient and
step order, start_seconds, end_seconds). Do not invent, drop, or
reorder anything.

Source recipe (JSON):
{recipe.model_dump_json()}
""".strip()

        contents = types.Content(
            parts=[
                types.Part(text=prompt),
            ]
        )

        async for chunk in self._generate_structured_stream(
            model=self.translation_model,
            contents=contents,
        ):
            yield chunk

    async def _generate_structured_stream(
        self,
        *,
        model: str,
        contents: types.Content,
    ) -> AsyncIterator[GeminiStreamChunk]:
        stream = await self.client.aio.models.generate_content_stream(
            model=model,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_schema": RecipeAnalysis,
            },
        )

        async for chunk in stream:
            usage = None

            if chunk.usage_metadata:
                metadata = chunk.usage_metadata

                usage = GeminiUsage(
                    input_tokens=metadata.prompt_token_count or 0,
                    output_tokens=metadata.candidates_token_count or 0,
                    thoughts_tokens=metadata.thoughts_token_count or 0,
                    total_tokens=metadata.total_token_count or 0,
                    cached_tokens=metadata.cached_content_token_count or 0,
                )
            if chunk.text or usage:
                yield GeminiStreamChunk(
                    text=chunk.text or None,
                    usage=usage,
                    response_id=chunk.response_id,
                    model_version=chunk.model_version,
                )
