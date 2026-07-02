from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import Settings, settings
from app.observability import record_model_gateway_request
from app.services.model_gateway import (
    ModelCredentialError,
    ModelGatewayError,
    ModelTransportError,
    extract_output_text,
    parse_expires_at,
    redact_token_material,
)


AI_PLATFORM_PROVIDER = "ai_platform"
AI_PLATFORM_DEFAULT_TRUST_TOKEN_HEADER = "X-XXXX-E2E-Trust-Token"
AI_PLATFORM_DEFAULT_TRACKING_PREFIX = "EFP"


@dataclass(frozen=True)
class ResolvedAIPlatformToken:
    token: str
    source: str
    expires_at: datetime | None = None


class AIPlatformModelGateway:
    provider = AI_PLATFORM_PROVIDER

    def __init__(
        self,
        *,
        app_settings: Settings = settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = app_settings
        self.http_client = http_client or httpx.AsyncClient(
            **app_settings.ai_platform_httpx_client_kwargs()
        )
        self._cached_token: ResolvedAIPlatformToken | None = None

    async def responses(
        self,
        *,
        user_id: str,
        model: str,
        instructions: str | None,
        input: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        metadata: dict[str, Any] | None = None,
        reasoning_effort: str = "high",
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        started_at = time.perf_counter()
        try:
            response = await self._responses_core(
                user_id=user_id,
                model=model,
                instructions=instructions,
                input=input,
                tools=tools,
                metadata=metadata,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
                response_format=response_format,
            )
        except Exception:
            record_model_gateway_request(
                provider=self.provider,
                model=model,
                stream=stream,
                status="failed",
                duration_seconds=time.perf_counter() - started_at,
            )
            raise

        if stream:
            return _instrument_ai_platform_stream(
                _single_response_stream(response),
                provider=self.provider,
                model=model,
                started_at=started_at,
            )

        record_model_gateway_request(
            provider=self.provider,
            model=model,
            stream=False,
            status="succeeded",
            duration_seconds=time.perf_counter() - started_at,
        )
        return response

    async def _responses_core(
        self,
        *,
        user_id: str,
        model: str,
        instructions: str | None,
        input: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        reasoning_effort: str = "high",
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if _normalize_provider(self.settings.llm_provider) != AI_PLATFORM_PROVIDER:
            raise ModelGatewayError("LogAn AI Platform gateway requires LOGAN_LLM_PROVIDER=ai_platform")

        resolved = await self._resolve_token()
        endpoint = _join_url(self.settings.ai_platform_chat_host, self.settings.ai_platform_chat_uri)
        payload = self._build_chat_payload(
            model=model,
            instructions=instructions,
            input=input,
            tools=tools,
            metadata=metadata,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            response_format=response_format,
        )
        try:
            response = await self.http_client.post(
                endpoint,
                json=payload,
                headers=self._chat_headers(resolved.token),
            )
            response.raise_for_status()
            provider_json = response.json()
        except httpx.HTTPStatusError as exc:
            detail = _sanitized_response_detail(exc.response)
            message = f"AI Platform chat completions failed with HTTP {exc.response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise ModelTransportError(redact_token_material(message, [resolved.token])) from exc
        except Exception as exc:
            message = redact_token_material(
                str(exc) or exc.__class__.__name__,
                [resolved.token, self.settings.ai_platform_password or ""],
            )
            raise ModelTransportError(
                f"AI Platform chat completions transport failed: {message}"
            ) from exc

        output_text = extract_output_text(provider_json)
        result: dict[str, Any] = {
            "provider": self.provider,
            "model": model,
            "payload": payload,
            "provider_json": provider_json,
            "output_text": output_text,
            "token_source": resolved.source,
        }
        parsed = _parse_json_output(output_text, response_format=response_format)
        if parsed is not None:
            result["output_json"] = parsed
        return result

    async def _resolve_token(self) -> ResolvedAIPlatformToken:
        configured_token = (self.settings.ai_platform_token or "").strip()
        configured_expires_at = parse_expires_at(self.settings.ai_platform_token_expires_at)
        if configured_token and _token_is_fresh(configured_expires_at):
            return ResolvedAIPlatformToken(
                token=configured_token,
                source="env_ai_platform_token",
                expires_at=configured_expires_at,
            )
        if self._cached_token and _token_is_fresh(self._cached_token.expires_at):
            return self._cached_token
        if self._credentials_configured():
            self._cached_token = await self._exchange_token()
            return self._cached_token
        if configured_token and configured_expires_at is not None:
            raise ModelCredentialError(
                "Configured AI Platform token is expired and no refresh credentials are available"
            )
        raise ModelCredentialError(
            "No AI Platform credential is available; configure LOGAN_AI_PLATFORM_TOKEN or "
            "LOGAN_AI_PLATFORM_USERNAME, LOGAN_AI_PLATFORM_PASSWORD, and LOGAN_AI_PLATFORM_USERCASE"
        )

    def _credentials_configured(self) -> bool:
        return all(
            [
                (self.settings.ai_platform_username or "").strip(),
                (self.settings.ai_platform_password or "").strip(),
                (self.settings.ai_platform_usercase or "").strip(),
                (self.settings.ai_platform_ib2b_host or "").strip(),
                (self.settings.ai_platform_ib2b_uri or "").strip(),
            ]
        )

    async def _exchange_token(self) -> ResolvedAIPlatformToken:
        endpoint = _join_url(self.settings.ai_platform_ib2b_host, self.settings.ai_platform_ib2b_uri)
        username = (self.settings.ai_platform_username or "").strip()
        password = self.settings.ai_platform_password or ""
        payload = {
            "input_token_state": {
                "token_type": "CREDENTIAL",
                "username": username,
                "password": password,
            },
            "output_token_state": {"token_type": "JWT"},
        }
        try:
            response = await self.http_client.post(
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = _sanitized_response_detail(exc.response)
            message = f"AI Platform iB2B token exchange failed with HTTP {exc.response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise ModelTransportError(redact_token_material(message, [password])) from exc
        except Exception as exc:
            message = redact_token_material(str(exc) or exc.__class__.__name__, [password])
            raise ModelTransportError(
                f"AI Platform iB2B token exchange transport failed: {message}"
            ) from exc

        token = data.get("issued_token")
        if not isinstance(token, str) or not token.strip():
            raise ModelTransportError("AI Platform iB2B token response did not include issued_token")
        ttl_seconds = max(1, self.settings.ai_platform_token_ttl_seconds)
        return ResolvedAIPlatformToken(
            token=token,
            source="ib2b_exchange",
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )

    def _build_chat_payload(
        self,
        *,
        model: str,
        instructions: str | None,
        input: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        metadata: dict[str, Any] | None,
        reasoning_effort: str,
        temperature: float | None,
        response_format: dict[str, Any] | None,
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        if instructions and instructions.strip():
            messages.append({"role": "developer", "content": instructions})
        for item in input:
            role = str(item.get("role") or "user")
            messages.append({"role": role, "content": _chat_content(item.get("content"))})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "reasoning_effort": reasoning_effort,
            "max_completion_tokens": self.settings.ai_platform_max_completion_tokens,
        }
        usercase = (self.settings.ai_platform_usercase or "").strip()
        if usercase:
            payload["user"] = usercase
        if response_format is not None:
            payload["response_format"] = response_format
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = tools
        if self.settings.ai_platform_store_completions:
            payload["store"] = True
        if metadata and self.settings.ai_platform_store_completions:
            payload["metadata"] = metadata
        return payload

    def _chat_headers(self, token: str) -> dict[str, str]:
        trust_token_header = self.settings.ai_platform_trust_token_header.strip()
        if not trust_token_header:
            trust_token_header = AI_PLATFORM_DEFAULT_TRUST_TOKEN_HEADER
        tracking = self._tracking_id()
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            trust_token_header: token,
            "x-correlation-id": tracking,
            "x-usersession-id": tracking,
        }

    def _tracking_id(self) -> str:
        prefix = self.settings.ai_platform_tracking_prefix.strip()
        if not prefix:
            prefix = AI_PLATFORM_DEFAULT_TRACKING_PREFIX
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")[:-3]
        return f"{prefix}-{stamp}"


async def _single_response_stream(response: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text:
        yield {"type": "message.delta", "delta": output_text}
    yield {
        "type": "message.completed",
        "provider": response.get("provider", AI_PLATFORM_PROVIDER),
        "model": response.get("model"),
        "output_text": output_text if isinstance(output_text, str) else "",
        "provider_json": response.get("provider_json"),
        "token_source": response.get("token_source"),
    }


async def _instrument_ai_platform_stream(
    events: AsyncIterator[dict[str, Any]],
    *,
    provider: str,
    model: str,
    started_at: float,
) -> AsyncIterator[dict[str, Any]]:
    status = "failed"
    try:
        async for event in events:
            yield event
        status = "succeeded"
    finally:
        record_model_gateway_request(
            provider=provider,
            model=model,
            stream=True,
            status=status,
            duration_seconds=time.perf_counter() - started_at,
        )


def _chat_content(value: Any) -> list[dict[str, Any]]:
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


def _join_url(host: str | None, uri: str | None) -> str:
    trimmed_host = (host or "").strip().rstrip("/")
    trimmed_uri = (uri or "").strip()
    if not trimmed_host or not trimmed_uri:
        raise ModelCredentialError("AI Platform host and uri are required")
    if trimmed_uri.startswith(("http://", "https://")):
        return trimmed_uri
    if not trimmed_uri.startswith("/"):
        trimmed_uri = "/" + trimmed_uri
    return trimmed_host + trimmed_uri


def _parse_json_output(
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


def _token_is_fresh(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > datetime.now(UTC) + timedelta(seconds=5)


def _normalize_provider(provider: str | None) -> str:
    normalized = (provider or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"aiplatform", "ai_platform"}:
        return AI_PLATFORM_PROVIDER
    return normalized


def _sanitized_response_detail(response: httpx.Response) -> str:
    text = response.text.strip()
    if not text:
        return ""
    try:
        payload = response.json()
    except ValueError:
        return redact_token_material(_limit_detail(text))
    detail = _detail_from_value(payload)
    return redact_token_material(_limit_detail(detail or text))


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
