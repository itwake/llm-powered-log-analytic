from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass


URL_SECRET_RE = re.compile(
    r"([?&](?:token|access_token|password|passwd|secret|api_key|apikey|key)=)([^&\s]+)",
    re.IGNORECASE,
)
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
BEARER_RE = re.compile(r"\bBearer\s+(?!Bearer\b)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6_RE = re.compile(r"\b(?:[A-Fa-f0-9]{1,4}:){2,7}[A-Fa-f0-9]{1,4}\b")
ASSIGNMENT_SECRET_RE = re.compile(
    r"\b(password|passwd|secret|api[_-]?key|token|access[_-]?token)=([^\s,&]+)",
    re.IGNORECASE,
)
TENANT_RE = re.compile(r"\b(?:tenant|customer)[_-]?id=([A-Za-z0-9._:-]+)", re.IGNORECASE)
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


@dataclass(frozen=True)
class RedactionResult:
    text: str
    replacements: dict[str, int]


class Redactor:
    def __init__(self, *, mode: str = "mask", secret: str = "logan-local-redaction") -> None:
        self.mode = mode
        self.secret = secret.encode()

    def _replacement(self, label: str, value: str | None = None) -> str:
        if self.mode == "hash" and value:
            digest = hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()[:12]
            return f"<{label}:{digest}>"
        return f"<{label}>"

    def redact(self, text: str) -> RedactionResult:
        replacements: dict[str, int] = {}

        def count(label: str, n: int) -> None:
            replacements[label] = replacements.get(label, 0) + n

        def sub(pattern: re.Pattern[str], label: str, value_group: int | None = None) -> None:
            nonlocal text

            def repl(match: re.Match[str]) -> str:
                value = match.group(value_group or 0)
                if label == "SECRET_ASSIGNMENT":
                    key = match.group(1)
                    return f"{key}={self._replacement('SECRET', value)}"
                return self._replacement(label, value)

            text, n = pattern.subn(repl, text)
            if n:
                count(label, n)

        def url_repl(match: re.Match[str]) -> str:
            return f"{match.group(1)}{self._replacement('SECRET', match.group(2))}"

        text, n = URL_SECRET_RE.subn(url_repl, text)
        if n:
            count("URL_QUERY_SECRET", n)

        sub(JWT_RE, "JWT")
        sub(BEARER_RE, "TOKEN")
        sub(ASSIGNMENT_SECRET_RE, "SECRET_ASSIGNMENT", 2)
        sub(TENANT_RE, "TENANT_ID", 1)
        sub(EMAIL_RE, "EMAIL")
        sub(IPV6_RE, "IP")
        sub(IPV4_RE, "IP")
        sub(UUID_RE, "UUID")
        sub(CARD_RE, "CARD")
        return RedactionResult(text=text, replacements=replacements)


def redact_text(text: str, *, mode: str = "mask", secret: str = "logan-local-redaction") -> str:
    return Redactor(mode=mode, secret=secret).redact(text).text
