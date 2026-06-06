from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlparse, urlunparse

import httpx

from app.config import Settings, settings
from app.core.security import decrypt_token
from app.observability import record_copilot_gateway_request
from app.store import CredentialRecord, MetadataStore


COPILOT_USER_AGENT = "GitHubCopilotChat/0.35.0"
EDITOR_VERSION = "vscode/1.107.0"
EDITOR_PLUGIN_VERSION = "copilot-chat/0.35.0"
COPILOT_INTEGRATION_ID = "vscode-chat"
COPILOT_DEFAULT_API_BASE = "https://api.githubcopilot.com"
COPILOT_TOKEN_EXCHANGE_URL = "https://api.github.com/copilot_internal/v2/token"
SOURCE_TOKEN_PREFIXES = ("ghp_", "ghu_", "gho_", "ghs_", "ghr_", "github_pat_")


class CopilotGatewayError(RuntimeError):
    pass


class CopilotCredentialError(CopilotGatewayError):
    pass


class CopilotTransportError(CopilotGatewayError):
    pass


class CopilotModelGatewayStreamUnsupported(CopilotGatewayError):
    pass


@dataclass(frozen=True)
class ResolvedCopilotToken:
    token: str
    api_base_url: str | None
    source: str


@dataclass(frozen=True)
class DecryptedCredential:
    record: CredentialRecord
    token: str


class CopilotModelGateway:
    provider = "github_copilot"

    def __init__(
        self,
        *,
        store: MetadataStore | None = None,
        app_settings: Settings = settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.store = store
        self.settings = app_settings
        self.http_client = http_client or httpx.AsyncClient(
            timeout=app_settings.copilot_timeout_seconds
        )

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
                stream=stream,
                metadata=metadata,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
                response_format=response_format,
            )
        except Exception:
            record_copilot_gateway_request(
                provider=self.provider,
                model=model,
                stream=stream,
                status="failed",
                duration_seconds=time.perf_counter() - started_at,
            )
            raise
        if stream:
            return _instrument_copilot_stream(
                response,
                provider=self.provider,
                model=model,
                started_at=started_at,
            )
        record_copilot_gateway_request(
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
        stream: bool = False,
        metadata: dict[str, Any] | None = None,
        reasoning_effort: str = "high",
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        if self.settings.llm_provider != "github_copilot":
            raise CopilotGatewayError("LogAn only supports github_copilot as its LLM provider")

        payload = self._build_payload(
            model=model,
            instructions=instructions,
            input=input,
            tools=tools,
            stream=stream,
            metadata=metadata,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            response_format=response_format,
        )
        resolved = await self._resolve_token(user_id=user_id)
        api_base_url = self._responses_api_base_url(resolved)
        if stream:
            return self._stream_response_events(
                api_base_url=api_base_url,
                payload=payload,
                resolved=resolved,
                model=model,
            )
        try:
            response = await self.http_client.post(
                f"{api_base_url}/responses",
                json=payload,
                headers=self._responses_headers(resolved.token, stream=stream),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = f"GitHub Copilot /responses failed with HTTP {exc.response.status_code}"
            raise CopilotTransportError(_redact_token_material(message, [resolved.token])) from exc
        except Exception as exc:
            message = _redact_token_material(str(exc) or exc.__class__.__name__, [resolved.token])
            raise CopilotTransportError(f"GitHub Copilot /responses transport failed: {message}") from exc

        provider_json = response.json()
        output_text = _extract_output_text(provider_json)
        parsed: dict[str, Any] | list[Any] | None = None
        if response_format and response_format.get("type") == "json_object" and output_text:
            try:
                loaded = json.loads(output_text)
                if isinstance(loaded, (dict, list)):
                    parsed = loaded
            except json.JSONDecodeError:
                parsed = None

        result: dict[str, Any] = {
            "provider": "github_copilot",
            "model": model,
            "payload": payload,
            "provider_json": provider_json,
            "output_text": output_text,
            "token_source": resolved.source,
        }
        if parsed is not None:
            result["output_json"] = parsed
        return result

    async def _resolve_token(self, *, user_id: str) -> ResolvedCopilotToken:
        if self.store is not None:
            plugin_credential = self._decrypted_credential(
                user_id=user_id, credential_type="copilot_plugin_token"
            )
            if plugin_credential and self._credential_is_fresh(plugin_credential.record):
                return ResolvedCopilotToken(
                    token=plugin_credential.token,
                    api_base_url=_api_base_from_copilot_token(plugin_credential.token),
                    source="stored_copilot_plugin_token",
                )
            source_credential = self._decrypted_credential(
                user_id=user_id, credential_type="github_source_oauth"
            )
            if source_credential:
                return await self._exchange_source_token(
                    source_credential.token,
                    token_source="stored_github_source_oauth",
                    persist_user_id=user_id,
                    github_base_url=source_credential.record.github_base_url,
                )

        if self.settings.github_copilot_token:
            return ResolvedCopilotToken(
                token=self.settings.github_copilot_token,
                api_base_url=_api_base_from_copilot_token(self.settings.github_copilot_token),
                source="env_github_copilot_token",
            )
        if self.settings.github_source_token:
            return await self._exchange_source_token(
                self.settings.github_source_token,
                token_source="env_github_source_token",
            )
        raise CopilotCredentialError(
            "No GitHub Copilot credential is available for this user or server environment"
        )

    def _decrypted_credential(
        self, *, user_id: str, credential_type: str
    ) -> DecryptedCredential | None:
        if self.store is None:
            return None
        credential = self.store.get_credential(user_id=user_id, credential_type=credential_type)
        if credential is None:
            return None
        try:
            token = decrypt_token(
                credential.encrypted_token,
                self.store.settings.credential_encryption_key,
            )
        except Exception as exc:
            raise CopilotCredentialError(
                f"Stored {credential_type} credential could not be decrypted"
            ) from exc
        return DecryptedCredential(record=credential, token=token) if token else None

    def _credential_is_fresh(self, credential: CredentialRecord) -> bool:
        if credential.expires_at is None:
            return True
        expires_at = credential.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        skew_seconds = max(0, self.settings.copilot_token_cache_skew_seconds)
        return expires_at > datetime.now(UTC) + timedelta(seconds=skew_seconds)

    async def _exchange_source_token(
        self,
        source_token: str,
        *,
        token_source: str,
        persist_user_id: str | None = None,
        github_base_url: str = "https://github.com",
    ) -> ResolvedCopilotToken:
        if not _looks_like_source_token(source_token):
            raise CopilotCredentialError("GitHub source OAuth token has an unsupported token prefix")
        try:
            response = await self.http_client.get(
                COPILOT_TOKEN_EXCHANGE_URL,
                headers=self._exchange_headers(source_token),
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            message = f"GitHub Copilot token exchange failed with HTTP {exc.response.status_code}"
            raise CopilotTransportError(
                _redact_token_material(message, [source_token])
            ) from exc
        except Exception as exc:
            message = _redact_token_material(str(exc) or exc.__class__.__name__, [source_token])
            raise CopilotTransportError(
                f"GitHub Copilot token exchange transport failed: {message}"
            ) from exc

        copilot_token = data.get("token")
        if not isinstance(copilot_token, str) or not copilot_token:
            raise CopilotTransportError("GitHub Copilot token exchange response did not include token")
        expires_at = _parse_copilot_token_expires_at(data)
        if self.store is not None and persist_user_id is not None and expires_at is not None:
            self.store.save_credential(
                user_id=persist_user_id,
                credential_type="copilot_plugin_token",
                token=copilot_token,
                github_base_url=github_base_url,
                expires_at=expires_at,
            )
        return ResolvedCopilotToken(
            token=copilot_token,
            api_base_url=_api_base_from_copilot_token(copilot_token),
            source=token_source,
        )

    def _exchange_headers(self, source_token: str) -> dict[str, str]:
        headers = self._copilot_headers()
        headers.update(
            {
                "Authorization": f"Bearer {source_token}",
                "Accept": "application/json",
            }
        )
        return headers

    def _responses_headers(self, copilot_token: str, *, stream: bool) -> dict[str, str]:
        headers = self._copilot_headers()
        headers.update(
            {
                "Authorization": f"Bearer {copilot_token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream"
                if stream
                else "application/vnd.github.copilot-chat-preview+json",
                "Openai-Intent": "conversation-edits",
                "x-initiator": "agent",
            }
        )
        return headers

    def _copilot_headers(self) -> dict[str, str]:
        return {
            "User-Agent": COPILOT_USER_AGENT,
            "Editor-Version": EDITOR_VERSION,
            "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
            "Copilot-Integration-Id": COPILOT_INTEGRATION_ID,
        }

    def _build_payload(
        self,
        *,
        model: str,
        instructions: str | None,
        input: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        metadata: dict[str, Any] | None,
        reasoning_effort: str,
        temperature: float | None,
        response_format: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": input,
            "tools": tools or [],
            "stream": stream,
            "metadata": metadata or {},
            "reasoning": {"effort": reasoning_effort},
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if response_format is not None:
            payload["response_format"] = response_format
        return payload

    def _responses_api_base_url(self, resolved: ResolvedCopilotToken) -> str:
        return (
            self.settings.copilot_base_url
            or resolved.api_base_url
            or _api_base_from_copilot_token(resolved.token)
            or COPILOT_DEFAULT_API_BASE
        ).rstrip("/")

    async def _stream_response_events(
        self,
        *,
        api_base_url: str,
        payload: dict[str, Any],
        resolved: ResolvedCopilotToken,
        model: str,
    ) -> AsyncIterator[dict[str, Any]]:
        completed_emitted = False
        accumulated_text: list[str] = []
        try:
            async with self.http_client.stream(
                "POST",
                f"{api_base_url}/responses",
                json=payload,
                headers=self._responses_headers(resolved.token, stream=True),
            ) as response:
                response.raise_for_status()
                async for data in _iter_sse_data(response):
                    if data.strip() == "[DONE]":
                        if not completed_emitted:
                            completed_emitted = True
                            yield {
                                "type": "message.completed",
                                "provider": "github_copilot",
                                "model": model,
                                "output_text": "".join(accumulated_text),
                                "token_source": resolved.source,
                            }
                        continue
                    try:
                        provider_event = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise CopilotTransportError(
                            "GitHub Copilot /responses stream returned invalid JSON"
                        ) from exc
                    if not isinstance(provider_event, dict):
                        continue

                    delta = _extract_stream_delta(provider_event)
                    if delta:
                        accumulated_text.append(delta)
                        yield {
                            "type": "message.delta",
                            "delta": delta,
                            "provider_event": provider_event,
                        }

                    completed = _extract_stream_completed(provider_event)
                    if completed is not None:
                        completed_emitted = True
                        output_text = completed.get("output_text")
                        if not isinstance(output_text, str):
                            output_text = "".join(accumulated_text)
                        yield {
                            "type": "message.completed",
                            "provider": "github_copilot",
                            "model": model,
                            "output_text": output_text,
                            "provider_json": completed.get("provider_json", provider_event),
                            "token_source": resolved.source,
                        }
                if not completed_emitted:
                    yield {
                        "type": "message.completed",
                        "provider": "github_copilot",
                        "model": model,
                        "output_text": "".join(accumulated_text),
                        "token_source": resolved.source,
                    }
        except httpx.HTTPStatusError as exc:
            message = f"GitHub Copilot /responses failed with HTTP {exc.response.status_code}"
            raise CopilotTransportError(_redact_token_material(message, [resolved.token])) from exc
        except CopilotTransportError as exc:
            message = _redact_token_material(str(exc), [resolved.token])
            raise CopilotTransportError(message) from exc
        except Exception as exc:
            message = _redact_token_material(str(exc) or exc.__class__.__name__, [resolved.token])
            raise CopilotTransportError(
                f"GitHub Copilot /responses transport failed: {message}"
            ) from exc


async def _instrument_copilot_stream(
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
        record_copilot_gateway_request(
            provider=provider,
            model=model,
            stream=True,
            status=status,
            duration_seconds=time.perf_counter() - started_at,
        )


def _looks_like_source_token(token: str) -> bool:
    return token.startswith(SOURCE_TOKEN_PREFIXES)


def _api_base_from_copilot_token(token: str) -> str | None:
    match = re.search(r"(?:^|;)proxy-ep=([^;]+)", token)
    if not match:
        return None
    endpoint = unquote(match.group(1))
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        return None
    host = parsed.hostname or ""
    if host.startswith("proxy."):
        host = f"api.{host.removeprefix('proxy.')}"
    netloc = host
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, "", "", "", ""))


def _parse_copilot_token_expires_at(data: dict[str, Any]) -> datetime | None:
    expires_at = _parse_expires_at(data.get("expires_at"))
    if expires_at is not None:
        return expires_at
    expires_in = data.get("expires_in")
    if isinstance(expires_in, int | float) and expires_in > 0:
        return datetime.now(UTC) + timedelta(seconds=float(expires_in))
    return None


def _parse_expires_at(value: Any) -> datetime | None:
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


def _extract_output_text(provider_json: Any) -> str:
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


async def _iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    data_lines: list[str] = []
    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\r")
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:]
        if data.startswith(" "):
            data = data[1:]
        data_lines.append(data)
    if data_lines:
        yield "\n".join(data_lines)


def _extract_stream_delta(provider_event: dict[str, Any]) -> str:
    event_type = provider_event.get("type")
    delta = provider_event.get("delta")
    if event_type in {"response.output_text.delta", "output_text_delta"} and isinstance(delta, str):
        return delta
    choices = provider_event.get("choices")
    if isinstance(choices, list):
        texts: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            choice_delta = choice.get("delta")
            if isinstance(choice_delta, dict) and isinstance(choice_delta.get("content"), str):
                texts.append(choice_delta["content"])
            elif isinstance(choice.get("text"), str):
                texts.append(choice["text"])
        if texts:
            return "".join(texts)
    output_text = provider_event.get("output_text")
    if isinstance(output_text, str):
        return output_text
    nested_text = _extract_output_text(provider_event)
    return nested_text


def _extract_stream_completed(provider_event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = provider_event.get("type")
    if event_type in {
        "response.completed",
        "response.output_text.done",
        "message.completed",
        "done",
        "completed",
    }:
        provider_json = provider_event.get("response")
        if not isinstance(provider_json, dict):
            provider_json = provider_event
        return {
            "provider_json": provider_json,
            "output_text": _extract_output_text(provider_json),
        }
    if isinstance(provider_event.get("usage"), dict) and provider_event.get("choices"):
        choices = provider_event.get("choices")
        if isinstance(choices, list) and any(
            isinstance(choice, dict) and choice.get("finish_reason") for choice in choices
        ):
            return {
                "provider_json": provider_event,
                "output_text": _extract_output_text(provider_event),
            }
    return None


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


def _redact_token_material(message: str, known_tokens: list[str] | tuple[str, ...] = ()) -> str:
    redacted = message
    for token in known_tokens:
        if token:
            redacted = redacted.replace(token, "<redacted-token>")
    redacted = re.sub(r"github_pat_[A-Za-z0-9_]+", "<redacted-token>", redacted)
    redacted = re.sub(r"\bgh[pousr]_[A-Za-z0-9_]+\b", "<redacted-token>", redacted)
    redacted = re.sub(r"Bearer\s+[^,\s]+", "Bearer <redacted-token>", redacted)
    return redacted
