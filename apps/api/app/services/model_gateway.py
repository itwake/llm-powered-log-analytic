from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any


class ModelGatewayError(RuntimeError):
    pass


class ModelCredentialError(ModelGatewayError):
    pass


class ModelTransportError(ModelGatewayError):
    pass


def parse_expires_at(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value), UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return datetime.fromtimestamp(float(raw), UTC)
        except (OverflowError, OSError, ValueError):
            pass
        iso_value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def extract_output_text(provider_json: Any) -> str:
    if isinstance(provider_json, dict):
        direct = provider_json.get("output_text")
        if isinstance(direct, str):
            return direct
        output = provider_json.get("output")
        if isinstance(output, list):
            texts: list[str] = []
            for item in output:
                texts.extend(_extract_text_from_output_item(item))
            if texts:
                return "".join(texts)
        choices = provider_json.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
                if isinstance(first.get("text"), str):
                    return first["text"]
    return ""


def redact_token_material(message: str, known_tokens: list[str] | tuple[str, ...] = ()) -> str:
    redacted = message
    for token in known_tokens:
        if token:
            redacted = redacted.replace(token, "<redacted-token>")
    redacted = re.sub(r"github_pat_[A-Za-z0-9_]+", "<redacted-token>", redacted)
    redacted = re.sub(r"\bgh[pousr]_[A-Za-z0-9_]+\b", "<redacted-token>", redacted)
    redacted = re.sub(r"Bearer\s+[^,\s]+", "Bearer <redacted-token>", redacted)
    return redacted


def _extract_text_from_output_item(item: Any) -> list[str]:
    if not isinstance(item, dict):
        return []
    texts: list[str] = []
    if item.get("type") in {"output_text", "text"} and isinstance(item.get("text"), str):
        texts.append(item["text"])
    content = item.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                    texts.append(part["text"])
                elif isinstance(part.get("text"), str) and "type" not in part:
                    texts.append(part["text"])
    return texts
