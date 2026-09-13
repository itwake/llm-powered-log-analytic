"""GitHub Copilot model gateway.

A GitHub OAuth token obtained through the device flow (or pasted by the user) is exchanged for a
short-lived Copilot session token, which authorizes OpenAI-compatible chat completions on the
Copilot API. The exchange mirrors the Copilot editor plugins, so the same plugin headers are sent.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from app.config import Settings, settings
from app.llm_catalog import GITHUB_COPILOT_PROVIDER
from app.records import LlmProviderRecord
from app.services.model_gateway import (
    ModelCredentialError,
    ModelTransportError,
    ResolvedToken,
    build_chat_messages,
    chat_completion_stream_events,
    completion_result,
    http_error_message,
    iter_sse_json,
    sanitized_response_detail,
    token_is_fresh,
    transport_error_message,
)

GITHUB_API_BASE_URL = "https://api.github.com"
COPILOT_API_BASE_URL = "https://api.githubcopilot.com"
COPILOT_TOKEN_PATH = "/copilot_internal/v2/token"
COPILOT_CHAT_COMPLETIONS_PATH = "/chat/completions"
COPILOT_TOKEN_REFRESH_MARGIN_SECONDS = 300
COPILOT_USER_AGENT = "GitHubCopilotChat/0.41.0"
COPILOT_EDITOR_VERSION = "vscode/1.133.0"
COPILOT_EDITOR_PLUGIN_VERSION = "copilot-chat/0.41.0"
COPILOT_INTEGRATION_ID = "vscode-chat"
COPILOT_ACCEPT_HEADER = "application/vnd.github.copilot-chat-preview+json"
_PROXY_ENDPOINT_PATTERN = re.compile(r"(?:^|[;&,\s])proxy-ep=([^;&,\s]+)")


def copilot_plugin_headers() -> dict[str, str]:
    return {
        "User-Agent": COPILOT_USER_AGENT,
        "Editor-Version": COPILOT_EDITOR_VERSION,
        "Editor-Plugin-Version": COPILOT_EDITOR_PLUGIN_VERSION,
        "Copilot-Integration-Id": COPILOT_INTEGRATION_ID,
    }


def parse_copilot_api_base_url(token: str) -> str | None:
    """Derive the Copilot API origin encoded in a session token, when present."""
    match = _PROXY_ENDPOINT_PATTERN.search(token)
    if match is None:
        return None
    raw = unquote(match.group(1).strip())
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or parsed.path.split("/", 1)[0]).strip()
    if not host:
        return None
    if host.startswith("proxy."):
        host = "api." + host.removeprefix("proxy.")
    return f"https://{host.rstrip('/')}"


@dataclass(frozen=True)
class GitHubCopilotProviderConfig:
    github_token: str = field(default="", repr=False)
    api_base_url: str = ""
    github_api_base_url: str = GITHUB_API_BASE_URL

    @classmethod
    def from_provider(cls, provider: LlmProviderRecord) -> GitHubCopilotProviderConfig:
        api_base_url = provider.config.get("api_base_url")
        github_api_base_url = provider.config.get("github_api_base_url")
        return cls(
            github_token=str(provider.secrets.get("github_token") or ""),
            api_base_url=str(api_base_url).strip().rstrip("/") if isinstance(api_base_url, str) else "",
            github_api_base_url=(
                str(github_api_base_url).strip().rstrip("/")
                if isinstance(github_api_base_url, str) and github_api_base_url.strip()
                else GITHUB_API_BASE_URL
            ),
        )

    @property
    def credentials_configured(self) -> bool:
        return bool(self.github_token.strip())


class GitHubCopilotModelGateway:
    provider = GITHUB_COPILOT_PROVIDER

    def __init__(
        self,
        *,
        config: GitHubCopilotProviderConfig,
        app_settings: Settings = settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.settings = app_settings
        self.http_client = http_client or httpx.AsyncClient(
            **app_settings.github_copilot_httpx_client_kwargs()
        )
        self._session: ResolvedToken | None = None
        self._api_base_url = config.api_base_url or COPILOT_API_BASE_URL

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
        payload = self._build_chat_payload(
            model=model,
            instructions=instructions,
            input=input,
            tools=tools,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            response_format=response_format,
            stream=stream,
        )
        initiator = "user" if (metadata or {}).get("purpose") == "case_chat" else "agent"
        if stream:
            return self._stream(payload=payload, model=model, initiator=initiator)
        return await self._complete(
            payload=payload,
            model=model,
            initiator=initiator,
            response_format=response_format,
        )

    async def _complete(
        self,
        *,
        payload: dict[str, Any],
        model: str,
        initiator: str,
        response_format: dict[str, Any] | None,
    ) -> dict[str, Any]:
        session = await self._resolve_session()
        response = await self._post(payload, session, initiator=initiator, stream=False)
        if response.status_code == 401:
            session = await self._resolve_session(force_refresh=True)
            response = await self._post(payload, session, initiator=initiator, stream=False)
        try:
            response.raise_for_status()
            provider_json = response.json()
        except httpx.HTTPStatusError as exc:
            raise ModelTransportError(
                http_error_message(
                    "GitHub Copilot chat completions",
                    exc,
                    known_tokens=[session.token, self.config.github_token],
                )
            ) from exc
        except ValueError as exc:
            raise ModelTransportError(
                "GitHub Copilot chat completions returned a non-JSON response"
            ) from exc
        return completion_result(
            provider=self.provider,
            model=model,
            payload=payload,
            provider_json=provider_json,
            token_source=session.source,
            response_format=response_format,
        )

    async def _stream(
        self,
        *,
        payload: dict[str, Any],
        model: str,
        initiator: str,
    ) -> AsyncIterator[dict[str, Any]]:
        session = await self._resolve_session()
        endpoint = self._chat_endpoint()
        known_tokens = [session.token, self.config.github_token]
        for attempt in range(2):
            try:
                request = self.http_client.build_request(
                    "POST",
                    endpoint,
                    json=payload,
                    headers=self._chat_headers(session.token, initiator=initiator, stream=True),
                )
                response = await self.http_client.send(request, stream=True)
            except Exception as exc:
                raise ModelTransportError(
                    transport_error_message(
                        "GitHub Copilot chat completions",
                        exc,
                        known_tokens=known_tokens,
                    )
                ) from exc
            try:
                if response.status_code == 401 and attempt == 0:
                    await response.aclose()
                    session = await self._resolve_session(force_refresh=True)
                    known_tokens = [session.token, self.config.github_token]
                    continue
                if response.status_code >= 400:
                    await response.aread()
                    detail = sanitized_response_detail(response)
                    message = (
                        "GitHub Copilot chat completions failed with HTTP "
                        f"{response.status_code}"
                    )
                    if detail:
                        message = f"{message}: {detail}"
                    raise ModelTransportError(message)
                async for event in chat_completion_stream_events(
                    iter_sse_json(response),
                    provider=self.provider,
                    model=model,
                    token_source=session.source,
                ):
                    yield event
                return
            except ModelTransportError:
                raise
            except Exception as exc:
                raise ModelTransportError(
                    transport_error_message(
                        "GitHub Copilot chat completions",
                        exc,
                        known_tokens=known_tokens,
                    )
                ) from exc
            finally:
                await response.aclose()

    async def _post(
        self,
        payload: dict[str, Any],
        session: ResolvedToken,
        *,
        initiator: str,
        stream: bool,
    ) -> httpx.Response:
        try:
            return await self.http_client.post(
                self._chat_endpoint(),
                json=payload,
                headers=self._chat_headers(session.token, initiator=initiator, stream=stream),
            )
        except Exception as exc:
            raise ModelTransportError(
                transport_error_message(
                    "GitHub Copilot chat completions",
                    exc,
                    known_tokens=[session.token, self.config.github_token],
                )
            ) from exc

    async def _resolve_session(self, *, force_refresh: bool = False) -> ResolvedToken:
        if not self.config.credentials_configured:
            raise ModelCredentialError(
                "The GitHub Copilot provider is not connected; authorize GitHub in AI Providers"
            )
        if (
            not force_refresh
            and self._session is not None
            and token_is_fresh(
                self._session.expires_at,
                margin_seconds=COPILOT_TOKEN_REFRESH_MARGIN_SECONDS,
            )
        ):
            return self._session
        self._session = await self._exchange_token()
        return self._session

    async def _exchange_token(self) -> ResolvedToken:
        source_token = self.config.github_token.strip()
        endpoint = f"{self.config.github_api_base_url}{COPILOT_TOKEN_PATH}"
        try:
            response = await self.http_client.get(
                endpoint,
                headers={
                    "Authorization": f"Bearer {source_token}",
                    "Accept": "application/json",
                    **copilot_plugin_headers(),
                },
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise ModelCredentialError(
                    http_error_message(
                        "GitHub Copilot token exchange",
                        exc,
                        known_tokens=[source_token],
                    )
                    + "; reconnect GitHub in AI Providers"
                ) from exc
            raise ModelTransportError(
                http_error_message(
                    "GitHub Copilot token exchange",
                    exc,
                    known_tokens=[source_token],
                )
            ) from exc
        except Exception as exc:
            raise ModelTransportError(
                transport_error_message(
                    "GitHub Copilot token exchange",
                    exc,
                    known_tokens=[source_token],
                )
            ) from exc

        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise ModelTransportError("GitHub Copilot token exchange returned an invalid token")
        expires_at_raw = data.get("expires_at")
        expires_at: datetime | None = None
        if isinstance(expires_at_raw, (int, float)) and not isinstance(expires_at_raw, bool):
            expires_at = datetime.fromtimestamp(float(expires_at_raw), UTC)
        else:
            expires_at = datetime.now(UTC) + timedelta(minutes=25)
        if not self.config.api_base_url:
            endpoints = data.get("endpoints") if isinstance(data, dict) else None
            api_endpoint = endpoints.get("api") if isinstance(endpoints, dict) else None
            derived = (
                str(api_endpoint).strip().rstrip("/")
                if isinstance(api_endpoint, str) and api_endpoint.strip()
                else parse_copilot_api_base_url(token)
            )
            self._api_base_url = derived or COPILOT_API_BASE_URL
        return ResolvedToken(token=token.strip(), source="github_exchange", expires_at=expires_at)

    def _chat_endpoint(self) -> str:
        return f"{self._api_base_url}{COPILOT_CHAT_COMPLETIONS_PATH}"

    def _build_chat_payload(
        self,
        *,
        model: str,
        instructions: str | None,
        input: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        reasoning_effort: str,
        temperature: float | None,
        response_format: dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": build_chat_messages(
                instructions=instructions,
                input=input,
                response_format=response_format,
            ),
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if response_format is not None:
            payload["response_format"] = response_format
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
        return payload

    def _chat_headers(self, token: str, *, initiator: str, stream: bool) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else COPILOT_ACCEPT_HEADER,
            "Openai-Intent": "conversation-panel",
            "X-GitHub-Api-Version": "2023-06-01",
            "x-initiator": initiator,
            **copilot_plugin_headers(),
        }
