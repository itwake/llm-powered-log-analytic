from __future__ import annotations

import re
from dataclasses import dataclass


URL_SECRET_RE = re.compile(
    r"([?&](?:token|access_token|source_token|password|passwd|secret|api_key|apikey|key)=)"
    r"([^&\s]+)",
    re.IGNORECASE,
)
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
BEARER_RE = re.compile(r"\bBearer\s+(?!Bearer\b)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# The negative lookahead keeps clock times (13:13:58) and similar short
# all-numeric colon runs from being redacted as IPv6 addresses.
IPV6_RE = re.compile(
    r"\b(?!(?:\d{1,2}:){2,7}\d{1,2}\b)(?:[A-Fa-f0-9]{1,4}:){2,7}[A-Fa-f0-9]{1,4}\b"
)
ASSIGNMENT_SECRET_RE = re.compile(
    r"\b(password|passwd|secret|api[_-]?key|token|access[_-]?token|source[_-]?token)="
    r"([^\s,&]+)",
    re.IGNORECASE,
)
TENANT_RE = re.compile(r"\b(?:tenant|customer)[_-]?id=([A-Za-z0-9._:-]+)", re.IGNORECASE)
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
SENSITIVE_FIELD_WORD_RE = re.compile(
    r"(?i)\b(authorization|bearer|password|passwd|secret|api[_-]?key|access[_-]?token|"
    r"source[_-]?token|token)\b"
)
# Fast pre-filters: full patterns only run when these cheap scans hit.
IPV4_GATE_RE = re.compile(r"\d{1,3}\.\d{1,3}\.")
IPV6_GATE_RE = re.compile(r"[A-Fa-f0-9]{1,4}:[A-Fa-f0-9]{1,4}:")
CARD_GATE_RE = re.compile(r"\d[\d -]{11,}\d")


def _luhn_valid(digits: str) -> bool:
    """Card-number check so long business references (event ids, reconciliation
    references) are not redacted as payment cards."""
    if not digits.isdigit():
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


@dataclass(frozen=True)
class RedactionResult:
    text: str
    replacements: dict[str, int]


class Redactor:
    @staticmethod
    def _replacement(label: str) -> str:
        return f"<{label}>"

    def redact(self, text: str) -> RedactionResult:
        replacements: dict[str, int] = {}

        def count(label: str, n: int) -> None:
            replacements[label] = replacements.get(label, 0) + n

        def sub(pattern: re.Pattern[str], label: str) -> None:
            nonlocal text

            def repl(match: re.Match[str]) -> str:
                if label == "SECRET_ASSIGNMENT":
                    key = match.group(1)
                    return f"{key}={self._replacement('SECRET')}"
                return self._replacement(label)

            text, n = pattern.subn(repl, text)
            if n:
                count(label, n)

        # Cheap substring gates skip regex passes that cannot match; on large
        # inputs most lines carry none of these markers.
        has_equals = "=" in text
        if has_equals and ("?" in text or "&" in text):

            def url_repl(match: re.Match[str]) -> str:
                return f"{match.group(1)}{self._replacement('SECRET')}"

            text, n = URL_SECRET_RE.subn(url_repl, text)
            if n:
                count("URL_QUERY_SECRET", n)

        if "eyJ" in text:
            sub(JWT_RE, "JWT")
        if "earer" in text or "EARER" in text:
            sub(BEARER_RE, "TOKEN")
        if has_equals:
            sub(ASSIGNMENT_SECRET_RE, "SECRET_ASSIGNMENT")
            sub(TENANT_RE, "TENANT_ID")
        if "@" in text:
            sub(EMAIL_RE, "EMAIL")
        if ":" in text and IPV6_GATE_RE.search(text):
            sub(IPV6_RE, "IP")
        if IPV4_GATE_RE.search(text):
            sub(IPV4_RE, "IP")
        if "-" in text:
            sub(UUID_RE, "UUID")
        if CARD_GATE_RE.search(text):

            def card_repl(match: re.Match[str]) -> str:
                digits = re.sub(r"[ -]", "", match.group(0))
                if _luhn_valid(digits):
                    count("CARD", 1)
                    return self._replacement("CARD")
                return match.group(0)

            text = CARD_RE.sub(card_repl, text)
        return RedactionResult(text=text, replacements=replacements)


def redact_text(text: str) -> str:
    return Redactor().redact(text).text


def redact_bounded_text(value: object, *, max_length: int) -> str:
    text = redact_text(str(value or ""))
    text = SENSITIVE_FIELD_WORD_RE.sub("<REDACTED_FIELD>", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return f"{text[: max_length - 3]}..."
