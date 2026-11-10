"""Modular LLM provider interface (Claude, OpenAI).

Providers only return structured objects validated against a Pydantic schema.
They never see API keys from anywhere but server settings, and callers must
check project consent before invoking them (see app/llm/explain.py).
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.core.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Provider failed or refused; message is safe to show to the user."""


class LLMNotConfigured(LLMError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, system: str, prompt: str, schema: type[T]) -> T: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings):
        import anthropic

        self._anthropic = anthropic
        self.model = settings.anthropic_model
        self.effort = settings.anthropic_effort
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key,
                                          timeout=settings.llm_timeout_seconds, max_retries=2)

    def generate(self, system: str, prompt: str, schema: type[T]) -> T:
        a = self._anthropic
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                output_config={"effort": self.effort},
                # Server-side refusal fallback: a declined request is retried on
                # Anthropic's recommended fallback model within the same call.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.RateLimitError as exc:
            raise LLMError("The AI provider is rate limiting requests; try again shortly.") from exc
        except a.AuthenticationError as exc:
            raise LLMError("The server's Anthropic API key was rejected.") from exc
        except a.APIStatusError as exc:
            raise LLMError(f"AI provider error ({exc.status_code}).") from exc
        except a.APIConnectionError as exc:
            raise LLMError("Could not reach the AI provider.") from exc
        if response.stop_reason == "refusal":
            raise LLMError("The model declined to answer this request.")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise LLMError("The AI response was incomplete; try a narrower request.")
        return response.parsed_output


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings):
        import openai

        self._openai = openai
        self.model = settings.openai_model
        self.client = openai.OpenAI(api_key=settings.openai_api_key,
                                    timeout=settings.llm_timeout_seconds, max_retries=2)

    def generate(self, system: str, prompt: str, schema: type[T]) -> T:
        o = self._openai
        try:
            response = self.client.responses.parse(
                model=self.model, instructions=system, input=prompt, text_format=schema)
        except o.RateLimitError as exc:
            raise LLMError("The AI provider is rate limiting requests; try again shortly.") from exc
        except o.AuthenticationError as exc:
            raise LLMError("The server's OpenAI API key was rejected.") from exc
        except o.APIStatusError as exc:
            raise LLMError(f"AI provider error ({exc.status_code}).") from exc
        except o.APIConnectionError as exc:
            raise LLMError("Could not reach the AI provider.") from exc
        if response.output_parsed is None:
            raise LLMError("The AI response could not be parsed.")
        return response.output_parsed


def provider_status(settings: Settings) -> tuple[str, bool, str | None]:
    if settings.llm_provider == "anthropic":
        return "anthropic", bool(settings.anthropic_api_key), settings.anthropic_model
    if settings.llm_provider == "openai":
        return "openai", bool(settings.openai_api_key), settings.openai_model
    return "none", False, None


def get_provider(settings: Settings) -> LLMProvider:
    name, configured, _ = provider_status(settings)
    if not configured:
        raise LLMNotConfigured("No AI provider is configured on this server "
                               "(set AUDITOR_LLM_PROVIDER and the matching API key).")
    return AnthropicProvider(settings) if name == "anthropic" else OpenAIProvider(settings)
