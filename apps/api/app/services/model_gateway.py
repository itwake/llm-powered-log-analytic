"""Shared model-gateway helpers for the OpenAI-compatible chat completion providers."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

JSON_OBJECT_FORMAT_INSTRUCTION = "Return valid JSON only."


class ModelGatewayError(RuntimeError):
    pass


class ModelCredentialError(ModelGatewayError):
    pass


class ModelTransportError(ModelGatewayError):
    pass


@dataclass(frozen=True)
class ResolvedToken:
    token: str
    source: str
    expires_at: datetime | None = None


def token_is_fresh(expires_at: datetime | None, *, margin_seconds: int = 5) -> bool:
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > datetime.now(UTC) + timedelta(seconds=margin_seconds)


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


def join_url(host: str | None, uri: str | None, *, label: str = "provider") -> str:
    trimmed_host = (host or "").strip().rstrip("/")
    trimmed_uri = (uri or "").strip()
    if not trimmed_host or not trimmed_uri:
        raise ModelCredentialError(f"{label} host and uri are required")
    if trimmed_uri.startswith(("http://", "https://")):
        return trimmed_uri
    if not trimmed_uri.startswith("/"):
        trimmed_uri = "/" + trimmed_uri
    return trimmed_host + trimmed_uri


def build_chat_messages(
    *,
    instructions: str | None,
    input: list[dict[str, Any]],
    response_format: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Project Responses-style input items onto chat-completion messages."""
    messages: list[dict[str, Any]] = []
    if instructions and instructions.strip():
        messages.append({"role": "developer", "content": instructions})
    for item in input:
        role = str(item.get("role") or "user")
        messages.append({"role": role, "content": chat_content(item.get("content"))})
    if requires_json_keyword(response_format) and not _messages_contain_json_keyword(messages):
        messages.append({"role": "developer", "content": JSON_OBJECT_FORMAT_INSTRUCTION})
    return messages


def build_responses_input(input: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project input items onto the Responses API shape the Copilot plugins send.

    Text parts become ``input_text`` for user and developer roles and ``output_text`` for the
    assistant; images stay ``input_image`` with a plain URL; anything else is dropped.
    """
    items: list[dict[str, Any]] = []
    for item in input:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user")
        text_type = "output_text" if role == "assistant" else "input_text"
        content: list[dict[str, Any]] = []
        raw = item.get("content")
        parts = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
        for part in parts:
            if isinstance(part, str):
                content.append({"type": text_type, "text": part})
            elif not isinstance(part, dict):
                continue
            elif part.get("type") in {"input_text", "output_text", "text"} and isinstance(
                part.get("text"), str
            ):
                content.append({"type": text_type, "text": part["text"]})
            elif (
                role != "assistant"
                and part.get("type") == "input_image"
                and isinstance(part.get("image_url"), str)
            ):
                content.append({"type": "input_image", "image_url": part["image_url"]})
        if content:
            items.append({"role": role, "content": content})
    return items


def contains_json_keyword(value: Any) -> bool:
    """Whether a prompt fragment already asks for JSON, so no extra instruction is needed."""
    return _content_contains_json_keyword(value)


def chat_content(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    content: list[dict[str, Any]] = []
    for part in value:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "input_text" and isinstance(part.get("text"), str):
            content.append({"type": "text", "text": part["text"]})
        elif part_type == "input_image" and isinstance(part.get("image_url"), str):
            content.append(
                {"type": "image_url", "image_url": {"url": part["image_url"]}}
            )
        elif part_type == "text" and isinstance(part.get("text"), str):
            content.append({"type": "text", "text": part["text"]})
        elif part_type == "image_url" and part.get("image_url"):
            content.append({"type": "image_url", "image_url": part["image_url"]})
    return content


def requires_json_keyword(response_format: dict[str, Any] | None) -> bool:
    return bool(response_format and response_format.get("type") == "json_object")


def parse_json_output(
    output_text: str,
    *,
    response_format: dict[str, Any] | None,
) -> dict[str, Any] | list[Any] | None:
    if not output_text or not response_format or response_format.get("type") != "json_object":
        return None
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def completion_result(
    *,
    provider: str,
    model: str,
    payload: dict[str, Any],
    provider_json: Any,
    token_source: str,
    response_format: dict[str, Any] | None,
) -> dict[str, Any]:
    output_text = extract_output_text(provider_json)
    result: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "payload": payload,
        "provider_json": provider_json,
        "output_text": output_text,
        "token_source": token_source,
    }
    parsed = parse_json_output(output_text, response_format=response_format)
    if parsed is not None:
        result["output_json"] = parsed
    return result


async def single_response_stream(response: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """Emulate streaming for a provider response that arrived in one piece."""
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text:
        yield {"type": "message.delta", "delta": output_text}
    yield {
        "type": "message.completed",
        "provider": response.get("provider"),
        "model": response.get("model"),
        "output_text": output_text if isinstance(output_text, str) else "",
        "provider_json": response.get("provider_json"),
        "token_source": response.get("token_source"),
    }


def http_error_message(
    prefix: str,
    exc: httpx.HTTPStatusError,
    *,
    known_tokens: list[str] | tuple[str, ...] = (),
) -> str:
    detail = sanitized_response_detail(exc.response)
    message = f"{prefix} failed with HTTP {exc.response.status_code}"
    if detail:
        message = f"{message}: {detail}"
    return redact_token_material(message, known_tokens)


def transport_error_message(
    prefix: str,
    exc: BaseException,
    *,
    known_tokens: list[str] | tuple[str, ...] = (),
) -> str:
    name = exc.__class__.__name__
    text = redact_token_material(str(exc).strip(), known_tokens)
    detail = f"{name}: {text}" if text and text != name else name
    return f"{prefix} transport failed: {detail}"


def sanitized_response_detail(response: httpx.Response) -> str:
    try:
        text = response.text.strip()
    except Exception:
        return ""
    if not text:
        return ""
    try:
        payload = response.json()
    except ValueError:
        return redact_token_material(_limit_detail(text))
    detail = _detail_from_value(payload)
    return redact_token_material(_limit_detail(detail or text))


def _messages_contain_json_keyword(messages: list[dict[str, Any]]) -> bool:
    return any(_content_contains_json_keyword(message.get("content")) for message in messages)


def _content_contains_json_keyword(content: Any) -> bool:
    if isinstance(content, str):
        return "json" in content.lower()
    if isinstance(content, list):
        return any(_content_contains_json_keyword(item) for item in content)
    if isinstance(content, dict):
        return any(_content_contains_json_keyword(value) for value in content.values())
    return False


def _detail_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "; ".join(filter(None, (_detail_from_value(item) for item in value[:5])))
    if isinstance(value, dict):
        parts: list[str] = []
        if "error" in value:
            detail = _detail_from_value(value["error"])
            if detail:
                parts.append(f"error={detail}")
        for key in (
            "message",
            "error_description",
            "code",
            "type",
            "param",
            "detail",
            "details",
            "status",
            "statusCode",
            "request_id",
            "requestId",
        ):
            if key in value:
                detail = _detail_from_value(value[key])
                if detail:
                    parts.append(f"{key}={detail}")
        if parts:
            return "; ".join(parts)
        return json.dumps(value, separators=(",", ":"))
    if value is None:
        return ""
    return json.dumps(value, separators=(",", ":"))


def _limit_detail(value: str, max_length: int = 1000) -> str:
    trimmed = value.strip()
    if len(trimmed) <= max_length:
        return trimmed
    return trimmed[:max_length] + "...(truncated)"


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
