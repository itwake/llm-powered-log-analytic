from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from logan_analysis.models import LogTemplate, NormalizedLogLine


def _template_key(
    *, analysis_run_id: str, template_text: str, parser_version: str
) -> str:
    raw = f"{analysis_run_id}:{template_text}:{parser_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _template_sort_key(item: LogTemplate) -> tuple[bool, Any, str]:
    return (item.first_seen is None, item.first_seen, item.template_text)


class TemplateExtractor:
    parser_version = "template_extractor_v2"

    # One combined pass replaces the shapes that always mask to <*>:
    # timestamps (whole-token, so no letter-glued fragments survive), UUIDs,
    # 12+-char hex ids (TDT_TASK_ID), 0x hex, req/trace/session prefixed ids,
    # and path-ish tokens.
    SIMPLE_MASK_RE = re.compile(
        r"\b\d{4}-\d{2}-\d{2}[t |]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:z|[+-]\d{2}:?\d{2})?\b"
        r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
        r"|\b[0-9a-f]{12,}\b"
        r"|\b0x[0-9a-f]+\b"
        r"|\b(?:req|trace|span|session|job|tenant|user)-[A-Za-z0-9_.:-]+\b"
        r"|\b/[A-Za-z0-9_./-]{3,}\b",
        re.I,
    )
    # Java object identity hashes: Form@e4900dee
    OBJECT_HASH_RE = re.compile(r"@[0-9a-f]{6,}\b", re.I)
    # The second lookbehind keeps kept error codes (eai-000511) intact.
    NUMBER_RE = re.compile(r"(?<![A-Za-z])(?<![A-Za-z]-)\b\d+(?:\.\d+)?")
    KEY_VALUE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_-]*=)([A-Za-z0-9_.:/-]+)")
    # Mixed letter/digit identifiers (BP10000027, BERSEC1825361185, job56291,
    # hkl20142165, session tokens). Runs before NUMBER_RE so hyphenated ids are
    # masked as one token instead of being fragmented digit by digit. Tokens
    # shaped like short error codes (EAI-000511) are meaningful and kept; short
    # digit suffixes keep their stem (WorkerThread8 -> workerthread<*>). The
    # digit lookahead keeps pure-alpha words out of the replacement callback.
    ALNUM_ID_RE = re.compile(r"\b(?=[a-z_-]{0,38}\d)[a-z0-9][a-z0-9_-]{5,}\b")
    ERROR_CODE_RE = re.compile(r"[a-z]{2,5}-\d{3,6}$")
    STEM_SUFFIX_RE = re.compile(r"[a-z_-]+\d{1,3}$")
    TRAILING_DIGITS_RE = re.compile(r"\d+$")
    # Residual variable fragments between field delimiters: digitless random
    # tokens and partially-masked ids that sit next to an existing mask inside
    # |-, :-, or space-delimited fields collapse into the mask.
    # Dots are excluded so dotted identifiers (java packages, hostnames) are
    # never absorbed into a neighbouring mask.
    MASK_NEIGHBOR_RE = re.compile(r"(?<=[|: ])(?:[a-z0-9_-]*<\*>)+[a-z0-9_-]*(?=[|:])")
    # Only fires when the token sits between a mask and another masked field
    # (session tokens: `<*> _jswdylv7e8ict6y5npzcji:<ip>`); plain labels such as
    # `stepname:` after a masked value are kept.
    FIELD_TOKEN_BEFORE_COLON_RE = re.compile(r"(?<=<\*> )[a-z0-9_.-]{6,}(?=:<)")
    MASK_RUN_RE = re.compile(r"(?:<\*>[ ;:,]*){3,}")
    WHITESPACE_RE = re.compile(r"\s+")

    # Bound the regex work per line: templates come from the entry head, and
    # anything longer carries no additional shape information.
    MAX_TEMPLATE_SOURCE_CHARS = 600
    MAX_TEMPLATE_CHARS = 400

    @classmethod
    def _mask_alnum_token(cls, match: re.Match[str]) -> str:
        token = match.group(0)
        digits = sum(map(str.isdigit, token))
        if not digits or digits == len(token):
            return token
        if cls.ERROR_CODE_RE.fullmatch(token):
            return token
        if cls.STEM_SUFFIX_RE.fullmatch(token):
            return cls.TRAILING_DIGITS_RE.sub("<*>", token)
        if digits >= 4 or len(token) >= 10:
            return "<*>"
        return token

    def to_template(self, normalized_message: str) -> str:
        text = normalized_message[: self.MAX_TEMPLATE_SOURCE_CHARS]
        # A redacted card token is still a variable slot; keeping the label would
        # split one message shape whenever only some values happen to be
        # Luhn-valid (e.g. random business references).
        text = text.replace("<card>", "<*>")
        text = self.SIMPLE_MASK_RE.sub("<*>", text)
        if "@" in text:
            text = self.OBJECT_HASH_RE.sub("@<*>", text)
        if "=" in text:
            text = self.KEY_VALUE_RE.sub(lambda match: f"{match.group(1)}<*>", text)
        text = self.ALNUM_ID_RE.sub(self._mask_alnum_token, text)
        text = self.NUMBER_RE.sub("<*>", text)
        if "<*>" in text:
            text = self.MASK_RUN_RE.sub("<*> ", text)
            text = self.MASK_NEIGHBOR_RE.sub("<*>", text)
            text = self.FIELD_TOKEN_BEFORE_COLON_RE.sub("<*>", text)
            text = self.MASK_RUN_RE.sub("<*> ", text)
        text = self.WHITESPACE_RE.sub(" ", text).strip()
        return text[: self.MAX_TEMPLATE_CHARS]

    def template_key(self, analysis_run_id: str, template_text: str) -> str:
        return _template_key(
            analysis_run_id=analysis_run_id,
            template_text=template_text,
            parser_version=self.parser_version,
        )

    def cluster(
        self, *, case_id: str, analysis_run_id: str, logs: list[NormalizedLogLine]
    ) -> tuple[list[NormalizedLogLine], list[LogTemplate]]:
        grouped: dict[str, list[NormalizedLogLine]] = {}
        template_text_by_key: dict[str, str] = {}
        key_by_template_text: dict[str, str] = {}
        for log in logs:
            # Parallel preprocessing precomputes template_text; fall back to the
            # local computation for callers that hand in bare normalized lines.
            template_text = (
                log.template_text
                if log.template_text is not None
                else self.to_template(log.normalized_message)
            )
            key = key_by_template_text.get(template_text)
            if key is None:
                key = self.template_key(analysis_run_id, template_text)
                key_by_template_text[template_text] = key
                template_text_by_key[key] = template_text
            grouped.setdefault(key, []).append(log)

        templates: list[LogTemplate] = []
        for key, group in grouped.items():
            template_text = template_text_by_key[key]
            template_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{analysis_run_id}:{key}"))
            timestamps = [line.timestamp for line in group if line.timestamp]
            services = sorted({line.service for line in group if line.service})
            files = sorted({line.file_path for line in group})
            representative_log_id = min(group, key=lambda line: line.ingestion_order).log_id
            for line in group:
                line.template_id = template_id
                line.template_text = template_text
            templates.append(
                LogTemplate(
                    template_id=template_id,
                    template_key=key,
                    template_text=template_text,
                    normalized_template_text=template_text,
                    representative_log_id=representative_log_id,
                    occurrence_count=len(group),
                    first_seen=min(timestamps) if timestamps else None,
                    last_seen=max(timestamps) if timestamps else None,
                    services=services,
                    files=files,
                    sample_values={
                        "parser": "stable",
                        "distinct_messages": len(
                            {line.redacted_message for line in group[:10_000]}
                        ),
                    },
                    cluster_id=key[:16],
                )
            )
        templates.sort(key=_template_sort_key)
        return logs, templates
