from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

from logan_workers.models import LogTemplate, NormalizedLogLine

try:  # Optional at import time so older dev envs can still run the stable adapter.
    from drain3 import TemplateMiner
    from drain3.template_miner_config import TemplateMinerConfig
except Exception:  # pragma: no cover - exercised by environments without drain3 installed.
    TemplateMiner = None  # type: ignore[assignment]
    TemplateMinerConfig = None  # type: ignore[assignment]


@dataclass(frozen=True)
class DrainConfig:
    engine: str = "drain3"
    config_hash: str = "default"
    sim_th: float = 0.4
    depth: int = 4
    max_children: int = 100
    max_clusters: int = 10000
    parametrize_numeric_tokens: bool = True
    extra_delimiters: tuple[str, ...] = ("?", "&", ",", ";", "(", ")", "[", "]")
    fallback_to_stable: bool = True

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None, *, config_hash: str = "default") -> "DrainConfig":
        if not value:
            return cls(config_hash=config_hash)
        extra_delimiters = value.get("extra_delimiters", cls.extra_delimiters)
        if isinstance(extra_delimiters, str):
            extra_delimiters = tuple(item for item in extra_delimiters if item)
        elif isinstance(extra_delimiters, list):
            extra_delimiters = tuple(str(item) for item in extra_delimiters if str(item))
        else:
            extra_delimiters = cls.extra_delimiters
        return cls(
            engine=str(value.get("engine", "drain3")).lower(),
            config_hash=str(value.get("config_hash", config_hash)),
            sim_th=float(value.get("sim_th", cls.sim_th)),
            depth=int(value.get("depth", cls.depth)),
            max_children=int(value.get("max_children", cls.max_children)),
            max_clusters=int(value.get("max_clusters", cls.max_clusters)),
            parametrize_numeric_tokens=bool(
                value.get("parametrize_numeric_tokens", cls.parametrize_numeric_tokens)
            ),
            extra_delimiters=extra_delimiters,
            fallback_to_stable=bool(value.get("fallback_to_stable", cls.fallback_to_stable)),
        )


def _template_key(
    *, analysis_run_id: str, template_text: str, parser_version: str, config_hash: str
) -> str:
    raw = f"{analysis_run_id}:{template_text}:{parser_version}:{config_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _template_sort_key(item: LogTemplate) -> tuple[bool, Any, str]:
    return (item.first_seen is None, item.first_seen, item.template_text)


class StableDrainAdapter:
    """Small deterministic Drain-style fallback used when drain3 is unavailable."""

    parser_version = "stable_drain_adapter_v1"

    UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
    HEX_RE = re.compile(r"\b0x[0-9a-f]+\b", re.I)
    NUMBER_RE = re.compile(r"(?<![A-Za-z])\b\d+(?:\.\d+)?\b")
    KEY_VALUE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_-]*=)([A-Za-z0-9_.:/-]+)")
    REQUEST_RE = re.compile(r"\b(req|trace|span|session|job|tenant|user)-[A-Za-z0-9_.:-]+\b", re.I)
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
        text = self.PATHISH_RE.sub("<*>", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def template_key(self, analysis_run_id: str, template_text: str) -> str:
        return _template_key(
            analysis_run_id=analysis_run_id,
            template_text=template_text,
            parser_version=self.parser_version,
            config_hash=self.config_hash,
        )

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
                    sample_values={
                        "parser": "stable",
                        "distinct_messages": len({line.redacted_message for line in group}),
                    },
                    drain_cluster_id=key[:16],
                )
            )
        templates.sort(key=_template_sort_key)
        return logs, templates


class Drain3Adapter(StableDrainAdapter):
    """Drain3-backed adapter that preserves the existing cluster() seam."""

    parser_version = "drain3_v1"

    def __init__(self, *, config: DrainConfig | None = None, config_hash: str = "default") -> None:
        self.config = config or DrainConfig(config_hash=config_hash)
        super().__init__(config_hash=self.config.config_hash)

    @property
    def available(self) -> bool:
        return TemplateMiner is not None and TemplateMinerConfig is not None

    def _miner(self):
        if not self.available:
            raise RuntimeError("drain3 is not installed")
        config = TemplateMinerConfig()
        config.drain_sim_th = self.config.sim_th
        config.drain_depth = self.config.depth
        config.drain_max_children = self.config.max_children
        config.drain_max_clusters = self.config.max_clusters
        config.parametrize_numeric_tokens = self.config.parametrize_numeric_tokens
        config.drain_extra_delimiters = list(self.config.extra_delimiters)
        config.mask_prefix = "<"
        config.mask_suffix = ">"
        return TemplateMiner(config=config)

    def _prepare_message(self, normalized_message: str) -> str:
        # Keep high-cardinality values masked before Drain3 clustering. Drain3 still owns the
        # tree clustering and final template convergence behind this stable adapter interface.
        return self.to_template(normalized_message)

    def _cluster_template_texts(self, miner: Any) -> dict[str, str]:
        return {
            str(cluster.cluster_id): re.sub(r"\s+", " ", cluster.get_template()).strip()
            for cluster in miner.drain.clusters
        }

    def cluster(
        self, *, case_id: str, analysis_run_id: str, logs: list[NormalizedLogLine]
    ) -> tuple[list[NormalizedLogLine], list[LogTemplate]]:
        if not self.available:
            if self.config.fallback_to_stable:
                return StableDrainAdapter(config_hash=self.config_hash).cluster(
                    case_id=case_id, analysis_run_id=analysis_run_id, logs=logs
                )
            raise RuntimeError("drain3 is not installed")

        miner = self._miner()
        grouped: dict[str, list[NormalizedLogLine]] = {}
        first_template_by_cluster: dict[str, str] = {}
        for log in logs:
            result = miner.add_log_message(self._prepare_message(log.normalized_message))
            cluster_id = str(result.get("cluster_id"))
            grouped.setdefault(cluster_id, []).append(log)
            template = result.get("template_mined")
            if isinstance(template, str):
                first_template_by_cluster.setdefault(cluster_id, template)

        final_templates = self._cluster_template_texts(miner)
        templates: list[LogTemplate] = []
        for cluster_id, group in grouped.items():
            template_text = final_templates.get(cluster_id) or first_template_by_cluster[cluster_id]
            key = self.template_key(analysis_run_id, template_text)
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
                        "parser": "drain3",
                        "cluster_id": cluster_id,
                        "distinct_messages": len({line.redacted_message for line in group}),
                        "sim_th": self.config.sim_th,
                        "depth": self.config.depth,
                        "max_children": self.config.max_children,
                        "max_clusters": self.config.max_clusters,
                    },
                    drain_cluster_id=cluster_id,
                )
            )
        templates.sort(key=_template_sort_key)
        return logs, templates


def build_drain_adapter(
    *, config_hash: str = "default", config: dict[str, Any] | DrainConfig | None = None
) -> StableDrainAdapter:
    drain_config = config if isinstance(config, DrainConfig) else DrainConfig.from_mapping(
        config, config_hash=config_hash
    )
    if drain_config.engine in {"stable", "stable_drain", "stable_drain_adapter"}:
        return StableDrainAdapter(config_hash=drain_config.config_hash)
    if drain_config.engine == "drain3":
        adapter = Drain3Adapter(config=drain_config)
        if adapter.available or not drain_config.fallback_to_stable:
            return adapter
        return StableDrainAdapter(config_hash=drain_config.config_hash)
    raise ValueError(f"unsupported drain engine: {drain_config.engine}")
