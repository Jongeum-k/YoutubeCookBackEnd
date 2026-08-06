from google import genai

from app.core.config import get_settings


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