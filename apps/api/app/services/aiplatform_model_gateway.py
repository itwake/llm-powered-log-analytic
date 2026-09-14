from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import (
    AI_PLATFORM_DEFAULT_TRACKING_PREFIX,
    AI_PLATFORM_DEFAULT_TRUST_TOKEN_HEADER,
    Settings,
    settings,
)
from app.llm_catalog import AI_PLATFORM_PROVIDER
from app.records import LlmProviderRecord
from app.services.model_gateway import (
    ModelCredentialError,
    ModelTransportError,
    ResolvedToken,
    build_chat_messages,
    completion_result,
    http_error_message,
    join_url,
    single_response_stream,
    token_is_fresh,
    transport_error_message,
)


@dataclass(frozen=True)
class AIPlatformCredentials:
    """The per-user half of an AI Platform provider. Endpoints are deployment-managed."""

    username: str = ""
    usercase: str = ""
    password: str = field(default="", repr=False)

    @classmethod
    def from_provider(cls, provider: LlmProviderRecord) -> AIPlatformCredentials:
        def value(name: str) -> str:
            raw = provider.config.get(name)
            return str(raw).strip() if isinstance(raw, str) else ""

        return cls(
            username=value("username"),
            usercase=value("usercase"),
            password=str(provider.secrets.get("password") or ""),
        )

    @property
    def configured(self) -> bool:
        return all((self.username.strip(), self.password.strip(), self.usercase.strip()))


class AIPlatformModelGateway:
    """Chat completions through the enterprise AI Platform gateway.

    The user's credentials are exchanged for a short-lived JWT through iB2B, and the token is
    reused until it expires.
    """

    provider = AI_PLATFORM_PROVIDER

    def __init__(
        self,
        *,
        credentials: AIPlatformCredentials,
        app_settings: Settings = settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.credentials = credentials
        self.settings = app_settings
        self.http_client = http_client or httpx.AsyncClient(
            **app_settings.ai_platform_httpx_client_kwargs()
        )
        self._cached_token: ResolvedToken | None = None
        # One gateway serves every concurrent request for its provider, so the exchange is
        # single-flighted: a burst of annotation calls must not log in eight times.
        self._refresh_lock = asyncio.Lock()

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
        response = await self._complete(
            model=model,
            instructions=instructions,
            input=input,
            tools=tools,
            metadata=metadata,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            response_format=response_format,
        )
        if stream:
            return single_response_stream(response)
        return response

    async def _complete(
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
        resolved = await self._resolve_token()
        endpoint = join_url(
            self.settings.ai_platform_chat_host,
            self.settings.ai_platform_chat_uri,
            label="AI Platform",
        )
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
            raise ModelTransportError(
                http_error_message(
                    "AI Platform chat completions",
                    exc,
                    known_tokens=[resolved.token],
                )
            ) from exc
        except Exception as exc:
            raise ModelTransportError(
                transport_error_message(
                    "AI Platform chat completions",
                    exc,
                    known_tokens=[resolved.token, self.credentials.password],
                )
            ) from exc

        return completion_result(
            provider=self.provider,
            model=model,
            payload=payload,
            provider_json=provider_json,
            token_source=resolved.source,
            response_format=response_format,
        )

    async def _resolve_token(self) -> ResolvedToken:
        if self._cached_token and token_is_fresh(self._cached_token.expires_at):
            return self._cached_token
        if not self.credentials.configured:
            raise ModelCredentialError(
                "The AI Platform provider is missing credentials; add the username, password, "
                "and usercase in AI Providers"
            )
        async with self._refresh_lock:
            # Another request may have refreshed the token while this one waited.
            if self._cached_token and token_is_fresh(self._cached_token.expires_at):
                return self._cached_token
            self._cached_token = await self._exchange_token()
            return self._cached_token

    async def _exchange_token(self) -> ResolvedToken:
        endpoint = join_url(
            self.settings.ai_platform_ib2b_host,
            self.settings.ai_platform_ib2b_uri,
            label="AI Platform iB2B",
        )
        password = self.credentials.password
        payload = {
            "input_token_state": {
                "token_type": "CREDENTIAL",
                "username": self.credentials.username.strip(),
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
            raise ModelTransportError(
                http_error_message(
                    "AI Platform iB2B token exchange",
                    exc,
                    known_tokens=[password],
                )
            ) from exc
        except Exception as exc:
            raise ModelTransportError(
                transport_error_message(
                    "AI Platform iB2B token exchange",
                    exc,
                    known_tokens=[password],
                )
            ) from exc

        token = data.get("issued_token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise ModelTransportError("AI Platform iB2B token response did not include issued_token")
        ttl_seconds = max(1, self.settings.ai_platform_token_ttl_seconds)
        return ResolvedToken(
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
        payload: dict[str, Any] = {
            "model": model,
            "messages": build_chat_messages(
                instructions=instructions,
                input=input,
                response_format=response_format,
            ),
            "reasoning_effort": reasoning_effort,
            "max_completion_tokens": self.settings.ai_platform_max_completion_tokens,
        }
        usercase = self.credentials.usercase.strip()
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
        tracking = self._tracking_id()
        # A blank or padded name is an illegal HTTP header name; fall back to the default.
        header = (
            self.settings.ai_platform_trust_token_header.strip()
            or AI_PLATFORM_DEFAULT_TRUST_TOKEN_HEADER
        )
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            header: token,
            "x-correlation-id": tracking,
            "x-usersession-id": tracking,
        }

    def _tracking_id(self) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")[:-3]
        prefix = self.settings.ai_platform_tracking_prefix.strip() or AI_PLATFORM_DEFAULT_TRACKING_PREFIX
        return f"{prefix}-{stamp}"
