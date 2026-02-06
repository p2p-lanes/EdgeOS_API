"""
AI-powered application review using Google Gemini.

This module provides functionality to evaluate applications and generate
a review with a score and description explaining the evaluation.
"""

from google import genai

from app.api.applications.models import Application
from app.api.applications.schemas import ApplicationBaseCommon
from app.core.config import settings
from app.core.logger import logger


def _build_application_prompt(application: Application, prompt: str) -> str:
    """Build a prompt with relevant application data for AI evaluation."""
    return f"""{prompt}

APPLICATION DATA:
{ApplicationBaseCommon.model_validate(application, from_attributes=True).model_dump()}
"""


def review_application(application: Application) -> str | None:
    """
    Analyze an application using Google Gemini and return a review with score and description.

    Args:
        application: The Application model instance to evaluate.

    Returns:
        A text review containing the score and explanation, or None if review fails.
    """
    if not settings.GEMINI_API_KEY:
        logger.warning('GEMINI_API_KEY not configured, skipping AI review')
        return None

    if not application.popup_city.ai_review_prompt:
        logger.warning(
            'AI review prompt not configured for popup city %d',
            application.popup_city.id,
        )
        return None

    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        prompt = _build_application_prompt(
            application,
            application.popup_city.ai_review_prompt,
        )

        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt,
        )

        if not response.text:
            raise ValueError('AI returned empty response')
        review_text = response.text.strip()

        logger.info('AI reviewed application %d', application.id)
        return review_text

    except Exception as e:
        logger.error('Error reviewing application %d with AI: %s', application.id, e)
        return None
