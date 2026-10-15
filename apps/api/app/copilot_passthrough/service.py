"""GitHub Copilot pass-through: relay a caller's own tokens through this host.

The API host can reach github.com and the Copilot API; some callers cannot. These relays let them
use their own GitHub account from here. A caller presents its GitHub OAuth token and receives
GitHub's Copilot session-token answer, then presents that session token with each Responses API
request. LogAn contributes only what the caller lacks: the outbound transport (the GitHub Copilot
proxy, CA bundle, and timeout settings) and the editor identity headers the Copilot endpoints
require. It stores and caches nothing, and it forwards to GitHub and Copilot hosts only.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

import httpx

from app.config import Settings, settings
from app.services.github_copilot_model_gateway import (
    COPILOT_ACCEPT_HEADER,
    COPILOT_API_BASE_URL,
    COPILOT_RESPONSES_PATH,
    COPILOT_TOKEN_PATH,
    GITHUB_API_BASE_URL,
    copilot_plugin_headers,
    parse_copilot_api_base_url,
)
from app.services.model_gateway import ModelTransportError, transport_error_message

COPILOT_API_HOST = "githubcopilot.com"
MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024
# Request headers a caller may set on a relayed Responses call. Authentication, the content type,
# the Accept header, and the editor identity stay LogAn's: HTTP clients send their own defaults for
# those (``Accept: */*``), and the endpoint accepts the values the Copilot plugins send.
FORWARDED_REQUEST_HEADERS: tuple[str, ...] = ("openai-intent", "x-initiator", "x-request-id")
# Response headers passed back with a relayed body. Length and encoding headers are left out
# because the body is streamed, and decoded, on its way through.
FORWARDED_RESPONSE_HEADERS: tuple[str, ...] = ("content-type", "x-request-id")
TOKEN_EXCHANGE_LABEL = "GitHub Copilot token exchange"
RESPONSES_LABEL = "GitHub Copilot responses"


def copilot_api_base_url(session_token: str) -> str:
    """The Copilot API origin to relay to for a caller-supplied session token.

    GitHub encodes the account's Copilot origin in the token (``proxy-ep=...``). The token comes
    from the caller, so the relay follows it only to a ``githubcopilot.com`` host and otherwise
    uses the default origin; anything else would make this a relay to arbitrary hosts.
    """
    derived = parse_copilot_api_base_url(session_token)
    if derived is None:
        return COPILOT_API_BASE_URL
    host = (urlparse(derived).hostname or "").lower()
    if host == COPILOT_API_HOST or host.endswith(f".{COPILOT_API_HOST}"):
        return f"https://{host}"
    return COPILOT_API_BASE_URL


class CopilotPassThrough:
    def __init__(
        self,
        *,
        app_settings: Settings = settings,
        http_client: httpx.AsyncClient | None = None,
        github_api_base_url: str = GITHUB_API_BASE_URL,
    ) -> None:
        self.settings = app_settings
        self._http_client = http_client
        self.github_api_base_url = github_api_base_url.rstrip("/")

    @property
    def enabled(self) -> bool:
        return self.settings.copilot_passthrough_enabled

    @property
    def http_client(self) -> httpx.AsyncClient:
        """The outbound client, built on first use with the GitHub Copilot transport settings so
        that a deployment that keeps the relay off never loads them."""
        if self._http_client is None:
            try:
                self._http_client = httpx.AsyncClient(
                    **self.settings.github_copilot_httpx_client_kwargs()
                )
            except OSError as exc:
                raise ModelTransportError(
                    "The TLS CA bundle for GitHub cannot be loaded; check "
                    "LOGAN_GITHUB_COPILOT_CA_BUNDLE (or SSL_CERT_FILE / REQUESTS_CA_BUNDLE) "
                    "on the API host"
                ) from exc
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()

    async def exchange_token(self, github_token: str) -> httpx.Response:
        """Ask GitHub for a Copilot session token with the caller's GitHub token.

        The answer is returned whole, whatever its status: the caller reads GitHub's reply (token,
        expiry, endpoints, or the rejection) exactly as a Copilot plugin would.
        """
        try:
            return await self.http_client.get(
                f"{self.github_api_base_url}{COPILOT_TOKEN_PATH}",
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/json",
                    **copilot_plugin_headers(),
                },
            )
        except ModelTransportError:
            raise
        except Exception as exc:
            raise ModelTransportError(
                transport_error_message(TOKEN_EXCHANGE_LABEL, exc, known_tokens=[github_token])
            ) from exc

    async def relay_responses(
        self,
        *,
        session_token: str,
        body: bytes,
        caller_headers: Mapping[str, str],
    ) -> httpx.Response:
        """Forward one Responses API request and return the upstream response unread, so the
        body (server-sent events or JSON) can be streamed back as it arrives."""
        url = f"{copilot_api_base_url(session_token)}{COPILOT_RESPONSES_PATH}"
        try:
            request = self.http_client.build_request(
                "POST",
                url,
                content=body,
                headers=self._responses_headers(session_token, caller_headers),
            )
            return await self.http_client.send(request, stream=True)
        except ModelTransportError:
            raise
        except Exception as exc:
            raise ModelTransportError(
                transport_error_message(RESPONSES_LABEL, exc, known_tokens=[session_token])
            ) from exc

    @staticmethod
    def _responses_headers(
        session_token: str,
        caller_headers: Mapping[str, str],
    ) -> httpx.Headers:
        # No X-GitHub-Api-Version: the Copilot endpoint rejects it with "invalid apiVersion".
        headers = httpx.Headers(
            {
                "Authorization": f"Bearer {session_token}",
                "Content-Type": "application/json",
                "Accept": COPILOT_ACCEPT_HEADER,
                "Openai-Intent": "conversation-edits",
                "x-initiator": "user",
                **copilot_plugin_headers(),
            }
        )
        for name in FORWARDED_REQUEST_HEADERS:
            value = (caller_headers.get(name) or "").strip()
            if value:
                headers[name] = value
        return headers
