"""LLM provider adapters for recipe extraction.

Providers are optional: the SDK (openai, anthropic) is imported lazily
so the base ``wright-core`` distribution stays dependency-free.  Users
bring their own SDK via ``uvx --with openai`` and their own key.

Supported providers: openai, anthropic, gemini.  For anything else,
implement the one-method :class:`Provider` protocol.

Public surface:

    Provider — protocol: ``complete(prompt) -> str``; optionally
        ``complete_parsed(prompt, schema)`` for clients with native
        pydantic structured output (OpenAI's ``.parse``).
    detect_provider(key) — resolve provider from key prefix or env.
    resolve_provider(provider, key, model) — detection + key lookup +
        adapter construction, with actionable error messages.
    make_provider(provider, key, model) — build a single adapter.

Gemini uses its OpenAI-compatible endpoint, so the ``openai`` SDK
covers both openai and gemini.
"""

from __future__ import annotations

import os
from typing import Protocol

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class Provider(Protocol):
    """Anything that can complete a prompt to text.

    Optionally implements ``complete_parsed(prompt, schema) -> object``
    for clients with native pydantic structured output (e.g. OpenAI's
    ``beta.chat.completions.parse``).  Extraction uses it when present
    and falls back to plain completion + validation otherwise.
    """

    def complete(self, prompt: str) -> str:
        """Return the model's completion for the prompt."""


DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-haiku-latest",
    "gemini": "gemini-2.0-flash",
}

# Canonical env var names, in detection priority order.
ENV_VARS: dict[str, list[str]] = {
    "openai": ["OPENAI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
}

SDK_PACKAGES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "openai",  # Gemini via its OpenAI-compatible endpoint
}


class ProviderError(Exception):
    """Raised when no usable provider/key/SDK is available."""


def _check_finish_reason(finish_reason: str | None) -> None:
    """Raise a clear error for non-stop finish reasons.

    ``content_filter`` and ``length`` produce truncated output that
    fails JSON validation with a confusing error — surface the real
    cause instead.
    """
    if finish_reason == "content_filter":
        raise ProviderError(
            "The provider's content filter interrupted extraction for this "
            "page. Try again, or try a different provider with --provider."
        )
    if finish_reason == "length":
        raise ProviderError(
            "The model hit its output token limit before finishing the "
            "recipe. Try a different model with --model."
        )


def _key_prefix_provider(key: str) -> str | None:
    """Map a key prefix to a provider name, or None if unrecognised."""
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith("sk-"):
        return "openai"
    return None


def detect_provider(key: str | None = None) -> str:
    """Resolve the provider name from an explicit key or the environment.

    Resolution order: key prefix, then env vars in registry order.
    """
    if key:
        name = _key_prefix_provider(key)
        if name is None:
            raise ProviderError(
                "Could not infer provider from key prefix "
                "(expected 'sk-', 'sk-ant-', or 'AIza'). "
                "Pass --provider explicitly."
            )
        return name
    for name, env_names in ENV_VARS.items():
        for env in env_names:
            if os.environ.get(env):
                return name
    env_list = ", ".join(e for names in ENV_VARS.values() for e in names)
    raise ProviderError(f"No API key found. Pass --key, or set one of: {env_list}.")


def resolve_provider(
    provider: str | None,
    key: str | None,
    model: str | None = None,
) -> tuple[str, Provider]:
    """Detect the provider, resolve its key, and build the Provider.

    Resolution order for the provider: explicit --provider, then key
    prefix, then environment.  Resolution order for the key: explicit
    --key, then the provider's env vars.
    """
    name = provider or detect_provider(key)
    if name not in ENV_VARS:
        supported = ", ".join(ENV_VARS)
        raise ProviderError(f"Unknown provider: {name!r} (supported: {supported})")
    resolved_key = key
    if resolved_key is None:
        for env in ENV_VARS[name]:
            resolved_key = os.environ.get(env)
            if resolved_key:
                break
    if not resolved_key:
        env_list = " or ".join(ENV_VARS[name])
        raise ProviderError(
            f"No API key for provider {name!r}. Pass --key or set {env_list}."
        )
    return name, make_provider(name, resolved_key, model)


def make_provider(
    provider: str,
    key: str,
    model: str | None = None,
) -> Provider:
    """Build a Provider, importing the SDK lazily.

    Raises ProviderError with an actionable hint if the SDK is missing.
    """
    model = model or DEFAULT_MODELS[provider]
    if provider in ("openai", "gemini"):
        try:
            import openai  # ty: ignore[unresolved-import]
        except ImportError as exc:
            raise ProviderError(
                "The 'openai' package is not installed. "
                "Run with: uvx --with openai wright-core parse <url>"
            ) from exc
        kwargs: dict = {"api_key": key}
        if provider == "gemini":
            kwargs["base_url"] = GEMINI_BASE_URL
        client = openai.OpenAI(**kwargs)

        class _OpenAI:
            def complete(self, prompt: str) -> str:
                """Call chat completions with JSON response format."""
                completion = client.chat.completions.create(
                    model=model,
                    temperature=0,
                    max_tokens=16384,
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": prompt}],
                )
                choice = completion.choices[0]
                _check_finish_reason(choice.finish_reason)
                return choice.message.content or ""

            def complete_parsed(self, prompt: str, schema: type) -> object:
                """Native pydantic structured output (server-side schema)."""
                completion = client.beta.chat.completions.parse(
                    model=model,
                    temperature=0,
                    max_tokens=16384,
                    response_format=schema,
                    messages=[{"role": "user", "content": prompt}],
                )
                choice = completion.choices[0]
                _check_finish_reason(choice.finish_reason)
                parsed = completion.choices[0].message.parsed
                if parsed is None:
                    raise ValueError(
                        completion.choices[0].message.refusal
                        or "Model returned no parsed object"
                    )
                return parsed

        return _OpenAI()

    if provider == "anthropic":
        try:
            import anthropic  # ty: ignore[unresolved-import]
        except ImportError as exc:
            raise ProviderError(
                "The 'anthropic' package is not installed. "
                "Run with: uvx --with anthropic wright-core parse <url>"
            ) from exc
        client = anthropic.Anthropic(api_key=key)

        class _Anthropic:
            def complete(self, prompt: str) -> str:
                """Call messages.create and join text blocks."""
                message = client.messages.create(
                    model=model,
                    max_tokens=8192,
                    temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                )
                return "".join(
                    block.text for block in message.content if block.type == "text"
                )

        return _Anthropic()

    raise ProviderError(
        f"Unknown provider: {provider!r} (supported: openai, anthropic, gemini)"
    )
