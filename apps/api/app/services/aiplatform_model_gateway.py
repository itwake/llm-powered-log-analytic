from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import Settings, settings
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
    parse_expires_at,
    single_response_stream,
    token_is_fresh,
    transport_error_message,
)

AI_PLATFORM_DEFAULT_TRUST_TOKEN_HEADER = "X-XXXX-E2E-Trust-Token"
AI_PLATFORM_DEFAULT_TRACKING_PREFIX = "EFP"
AI_PLATFORM_DEFAULT_CHAT_URI = "/v1/api/v1/chat/completions"


@dataclass(frozen=True)
class AIPlatformProviderConfig:
    """Endpoint and credential settings of one user-managed AI Platform provider."""

    chat_host: str
    chat_uri: str = AI_PLATFORM_DEFAULT_CHAT_URI
    ib2b_host: str = ""
    ib2b_uri: str = ""
    usercase: str = ""
    trust_token_header: str = AI_PLATFORM_DEFAULT_TRUST_TOKEN_HEADER
    tracking_prefix: str = AI_PLATFORM_DEFAULT_TRACKING_PREFIX
    username: str = ""
    token_expires_at: str = ""
    password: str = field(default="", repr=False)
    token: str = field(default="", repr=False)

    @classmethod
    def from_provider(
        cls,
        provider: LlmProviderRecord,
        app_settings: Settings = settings,
    ) -> AIPlatformProviderConfig:
        defaults = app_settings.ai_platform_form_defaults()

        def value(name: str) -> str:
            raw = provider.config.get(name)
            text = str(raw).strip() if isinstance(raw, str) else ""
            return text or defaults.get(name, "")

        return cls(
            chat_host=value("chat_host").rstrip("/"),
            chat_uri=value("chat_uri") or AI_PLATFORM_DEFAULT_CHAT_URI,
            ib2b_host=value("ib2b_host").rstrip("/"),
            ib2b_uri=value("ib2b_uri"),
            usercase=value("usercase"),
            trust_token_header=value("trust_token_header") or AI_PLATFORM_DEFAULT_TRUST_TOKEN_HEADER,
            tracking_prefix=value("tracking_prefix") or AI_PLATFORM_DEFAULT_TRACKING_PREFIX,
            username=value("username"),
            token_expires_at=value("token_expires_at"),
            password=str(provider.secrets.get("password") or ""),
            token=str(provider.secrets.get("token") or ""),
        )

    @property
    def exchange_credentials_configured(self) -> bool:
        return all(
            (
                self.ib2b_host.strip(),
                self.ib2b_uri.strip(),
                self.username.strip(),
                self.password.strip(),
                self.usercase.strip(),
            )
        )

    @property
    def credentials_configured(self) -> bool:
        return bool(self.token.strip()) or self.exchange_credentials_configured


class AIPlatformModelGateway:
    provider = AI_PLATFORM_PROVIDER

    def __init__(
        self,
        *,
        config: AIPlatformProviderConfig,
        app_settings: Settings = settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.settings = app_settings
        self.http_client = http_client or httpx.AsyncClient(
            **app_settings.ai_platform_httpx_client_kwargs()
        )
        self._cached_token: ResolvedToken | None = None

    async def aclose(self) -> None:
        await self.http_client.aclose()

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
        response = await self._responses_core(
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

    async def _responses_core(
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
        endpoint = join_url(self.config.chat_host, self.config.chat_uri, label="AI Platform")
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
                    known_tokens=[resolved.token, self.config.password],
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
        configured_token = self.config.token.strip()
        configured_expires_at = parse_expires_at(self.config.token_expires_at)
        if configured_token and token_is_fresh(configured_expires_at):
            return ResolvedToken(
                token=configured_token,
                source="provider_token",
                expires_at=configured_expires_at,
            )
        if self._cached_token and token_is_fresh(self._cached_token.expires_at):
            return self._cached_token
        if self.config.exchange_credentials_configured:
            self._cached_token = await self._exchange_token()
            return self._cached_token
        if configured_token and configured_expires_at is not None:
            raise ModelCredentialError(
                "The configured AI Platform token is expired and no iB2B credentials are available"
            )
        raise ModelCredentialError(
            "The AI Platform provider has no usable credentials; add a trust token or complete "
            "iB2B credentials in AI Providers"
        )

    async def _exchange_token(self) -> ResolvedToken:
        endpoint = join_url(self.config.ib2b_host, self.config.ib2b_uri, label="AI Platform iB2B")
        username = self.config.username.strip()
        password = self.config.password
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
        usercase = self.config.usercase.strip()
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
        trust_token_header = self.config.trust_token_header.strip()
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
        prefix = self.config.tracking_prefix.strip()
        if not prefix:
            prefix = AI_PLATFORM_DEFAULT_TRACKING_PREFIX
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")[:-3]
        return f"{prefix}-{stamp}"
