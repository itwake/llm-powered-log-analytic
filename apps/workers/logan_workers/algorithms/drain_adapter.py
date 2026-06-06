from __future__ import annotations

import hashlib
import re
import uuid

from logan_workers.models import LogTemplate, NormalizedLogLine


class StableDrainAdapter:
    """Small Drain-style adapter with a stable seam for a future drain3 swap."""

    parser_version = "stable_drain_adapter_v1"

    UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
    HEX_RE = re.compile(r"\b0x[0-9a-f]+\b", re.I)
    NUMBER_RE = re.compile(r"(?<![A-Za-z])\b\d+(?:\.\d+)?\b")
    KEY_VALUE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_-]*=)([A-Za-z0-9_.:/-]+)")
    REQUEST_RE = re.compile(r"\b(req|trace|span)-[A-Za-z0-9_.:-]+\b", re.I)
    PATHISH_RE = re.compile(r"\b/[A-Za-z0-9_./-]{3,}\b")

    def __init__(self, *, config_hash: str = "default") -> None:
        self.config_hash = config_hash

    def to_template(self, normalized_message: str) -> str:
        text = normalized_message
        text = self.UUID_RE.sub("<*>", text)
        text = self.HEX_RE.sub("<*>", text)
        text = self.REQUEST_RE.sub("<*>", text)
        text = self.KEY_VALUE_RE.sub(lambda match: f"{match.group(1)}<*>", text)
        text = self.NUMBER_RE.sub("<*>", text)
        text = self.PATHISH_RE.sub(lambda match: match.group(0) if match.group(0) == "/checkout" else "<*>", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def template_key(self, analysis_run_id: str, template_text: str) -> str:
        raw = f"{analysis_run_id}:{template_text}:{self.parser_version}:{self.config_hash}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def cluster(
        self, *, case_id: str, analysis_run_id: str, logs: list[NormalizedLogLine]
    ) -> tuple[list[NormalizedLogLine], list[LogTemplate]]:
        grouped: dict[str, list[NormalizedLogLine]] = {}
        template_text_by_key: dict[str, str] = {}
        for log in logs:
            template_text = self.to_template(log.normalized_message)
            key = self.template_key(analysis_run_id, template_text)
            grouped.setdefault(key, []).append(log)
            template_text_by_key[key] = template_text

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
                    sample_values={"distinct_messages": len({line.redacted_message for line in group})},
                    drain_cluster_id=key[:16],
                )
            )
        templates.sort(key=lambda item: (item.first_seen is None, item.first_seen, item.template_text))
        return logs, templates
