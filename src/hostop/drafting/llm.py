"""LLM access for drafting. Real: Anthropic Messages API with JSON-schema structured output. Mock: deterministic."""

from __future__ import annotations

import json
from typing import Any, Protocol


class LLMRefusalError(Exception):
    pass


class LLM(Protocol):
    name: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]: ...


class AnthropicLLM:
    """Model comes from ANTHROPIC_MODEL. Uses output_config.format=json_schema so the reply is valid JSON."""

    name = "anthropic"

    def __init__(self, model: str, api_key: str | None = None, effort: str = "medium") -> None:
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model, self.effort = model, effort

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        output_config: Any = {"effort": self.effort, "format": {"type": "json_schema", "schema": schema}}
        response = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
        if response.stop_reason == "refusal":
            raise LLMRefusalError(f"model declined (request id {response._request_id})")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return dict(json.loads(text))
