from __future__ import annotations

from collections.abc import AsyncIterator
import json
from pathlib import Path
import re
import uuid
from typing import Any

from pydantic import ValidationError

from logan_workers.models import (
    LogTemplate,
    RepresentativeSample,
    TemplateAnnotation,
    TemplateAnnotationResult,
)

PROMPT_VERSION = "annotation_v1"
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "annotation_prompt.md"
TRUNCATION_SUFFIX = "...(truncated)"


def _load_annotation_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return (
            "Classify the log template and representative lines. Return only valid JSON "
            "with golden_signal, fault_categories, entities, severity_score, confidence, "
            "and rationale."
        )


def _truncate_text(value: str, *, max_chars: int | None) -> str:
    if max_chars is None or max_chars <= 0 or len(value) <= max_chars:
        return value
    if max_chars <= len(TRUNCATION_SUFFIX):
        return value[:max_chars]
    return f"{value[: max_chars - len(TRUNCATION_SUFFIX)]}{TRUNCATION_SUFFIX}"


def _prioritized_templates(
    templates: list[LogTemplate],
    *,
    max_templates: int | None,
) -> list[LogTemplate]:
    if max_templates is None or max_templates <= 0 or len(templates) <= max_templates:
        return templates
    return sorted(
        templates,
        key=lambda template: (-template.occurrence_count, template.template_id),
    )[:max_templates]


class MockAIPlatformAnnotationGateway:
    provider = "ai_platform"
    model = "gpt-5.4"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def responses(self, **kwargs: Any) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return self._stream_response()
        raw_text = " ".join(
            part.get("text", "")
            for item in kwargs.get("input", [])
            for part in item.get("content", [])
            if isinstance(part, dict)
        )
        text = raw_text.lower()
        metadata = kwargs.get("metadata") if isinstance(kwargs.get("metadata"), dict) else {}
        if (
            metadata.get("purpose") == "causal_summary"
            or kwargs.get("instructions") == "causal_summary_v1"
        ):
            return {"output_json": self._summarize(raw_text)}
        return {"output_json": self._classify(text)}

    async def _stream_response(self) -> AsyncIterator[dict[str, Any]]:
        message = "Mock analysis context response."
        yield {"type": "message.delta", "delta": message}
        yield {"type": "message.completed", "output_text": message}

    def _classify(self, text: str) -> dict[str, Any]:
        services = self._service_mentions(text)
        daemon = self._daemon_mention(text)
        source_ips = self._source_mentions(text)
        auth_failure_terms = [
            "authentication failure",
            "failed password",
            "invalid user",
            "auth failure",
            "authentication error",
            "login failed",
            "failed login",
            "auth could not identify password",
            "user unknown",
        ]
        if any(term in text for term in auth_failure_terms):
            service = services[0] if services else daemon or "auth"
            return {
                "golden_signal": "error",
                "fault_categories": ["authentication", "security"],
                "entities": {
                    "service": [service],
                    "source_ip": source_ips,
                    "user": re.findall(
                        r"\b(?:user|for invalid user|for)\s+([a-z0-9_.-]+)",
                        text,
                    )[:3],
                },
                "severity_score": 0.78,
                "confidence": 0.86,
                "rationale": "Authentication failures indicate failed access attempts or login errors.",
            }
        if any(
            term in text
            for term in [
                "connection refused",
                "refused connect",
                "network is unreachable",
                "no route to host",
                "host unreachable",
                "link is down",
            ]
        ):
            service = services[0] if services else daemon or "network"
            return {
                "golden_signal": "availability",
                "fault_categories": ["network"],
                "entities": {"service": [service], "source_ip": source_ips},
                "severity_score": 0.72,
                "confidence": 0.8,
                "rationale": "Network refusal or unreachable hosts indicate availability impact.",
            }
        if any(
            term in text
            for term in [
                "i/o error",
                "buffer i/o",
                "disk error",
                "device offline",
                "device error",
                "read error",
                "write error",
            ]
        ):
            return {
                "golden_signal": "error",
                "fault_categories": ["io", "device"],
                "entities": {
                    "service": services[:1],
                    "device": re.findall(r"\b(?:dev|device)\s+([a-z0-9/_-]+)", text)[:3],
                },
                "severity_score": 0.76,
                "confidence": 0.82,
                "rationale": "I/O or device errors are explicit infrastructure errors.",
            }
        if (
            ("connection from" in text or "connect from" in text or "accepted password" in text)
            and daemon in {"sshd", "ftpd", "ftp"}
        ):
            return {
                "golden_signal": "traffic",
                "fault_categories": ["network", "access"],
                "entities": {"service": [daemon], "source_ip": source_ips},
                "severity_score": 0.4,
                "confidence": 0.72,
                "rationale": "Repeated SSH/FTP connection activity is a traffic signal for incident review.",
            }
        if "connection pool exhausted" in text or "pool usage high" in text:
            service = services[0] if services else "unknown-service"
            return {
                "golden_signal": "saturation",
                "fault_categories": ["resource", "database"],
                "entities": {"service": [service], "database": ["db"] if "db" in text else []},
                "severity_score": 0.88,
                "confidence": 0.92,
                "rationale": "Connection pool exhaustion indicates resource saturation.",
            }
        called_service = self._called_service(text)
        if "timeout calling" in text:
            source_service = services[0] if services else "unknown-service"
            target_service = called_service or (
                services[1] if len(services) > 1 else "unknown-service"
            )
            return {
                "golden_signal": "availability",
                "fault_categories": ["dependency", "timeout"],
                "entities": {
                    "source_service": [source_service],
                    "target_service": [target_service],
                    "duration_ms": ["30000"],
                },
                "severity_score": 0.86,
                "confidence": 0.91,
                "rationale": "A service timed out while calling a dependency.",
            }
        if "failed status" in text or "status=<*>" in text or " status=500" in text:
            return {
                "golden_signal": "error",
                "fault_categories": ["application"],
                "entities": {
                    "service": [services[0] if services else "unknown-service"],
                    "status_code": ["500"],
                    "url_path": re.findall(r"\s(/[a-z0-9_./-]+)", text)[:1],
                },
                "severity_score": 0.84,
                "confidence": 0.89,
                "rationale": "Requests failed with server errors.",
            }
        if "failed to acquire db connection" in text:
            service = services[0] if services else "unknown-service"
            return {
                "golden_signal": "availability",
                "fault_categories": ["database", "timeout", "resource"],
                "entities": {"service": [service], "database": ["db"], "duration_ms": ["5000"]},
                "severity_score": 0.82,
                "confidence": 0.88,
                "rationale": "A service could not acquire a database connection.",
            }
        if "usage high" in text or "retry" in text:
            return {
                "golden_signal": "traffic",
                "fault_categories": ["resource"],
                "entities": {},
                "severity_score": 0.45,
                "confidence": 0.7,
                "rationale": "The line indicates elevated load or retry behavior.",
            }
        if "failed " in text or " failure" in text or " error" in text:
            service = services[0] if services else daemon or "unknown-service"
            return {
                "golden_signal": "error",
                "fault_categories": ["application"],
                "entities": {"service": [service]},
                "severity_score": 0.62,
                "confidence": 0.72,
                "rationale": "The template contains an explicit failure or error signal.",
            }
        return {
            "golden_signal": "information",
            "fault_categories": [],
            "entities": {},
            "severity_score": 0.1,
            "confidence": 0.75,
            "rationale": "Routine informational log.",
        }

    def _service_mentions(self, text: str) -> list[str]:
        mentions: list[str] = []
        patterns = [
            r"['\"]service['\"]\s*:\s*['\"]([^'\"]+)['\"]",
            r"['\"]services['\"]\s*:\s*\[([^\]]+)\]",
            r"\b(?:trace|debug|info|warn|warning|error|fatal)\s+([a-z][a-z0-9-]*)\b",
            r"\b([a-z][a-z0-9-]*(?:-service|gateway|scheduler|cache|kafka)[a-z0-9-]*)\b",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, text):
                values = re.findall(
                    r"[a-z][a-z0-9-]*(?:-service|gateway|scheduler|cache|kafka)?",
                    match,
                )
                for value in values or [match]:
                    if value and value not in {"service", "services"} and value not in mentions:
                        mentions.append(value)
        return mentions

    def _called_service(self, text: str) -> str | None:
        match = re.search(r"\b(?:calling|call to)\s+([a-z][a-z0-9-]*)\b", text)
        return match.group(1) if match else None

    def _daemon_mention(self, text: str) -> str | None:
        for daemon in ("sshd", "ftpd", "ftp", "named", "kernel", "cron", "sudo", "su"):
            if re.search(rf"\b{daemon}\b", text):
                return daemon
        return None

    def _source_mentions(self, text: str) -> list[str]:
        mentions = re.findall(r"\b(?:from|rhost=|host=)\s+([<>\w.:-]+)", text)
        return list(dict.fromkeys(mentions))[:5]

    def _summary_packet(self, text: str) -> dict[str, Any]:
        try:
            packet = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return packet if isinstance(packet, dict) else {}

    def _summary_log_ids(self, packet: dict[str, Any], text: str) -> list[str]:
        log_ids = [
            str(item.get("log_id"))
            for item in packet.get("evidence_lines", [])
            if isinstance(item, dict) and item.get("log_id")
        ]
        if not log_ids:
            log_ids = re.findall(r'"log_id"\s*:\s*"([^"]+)"', text)
        return list(dict.fromkeys(log_ids))[:6] or ["unknown-log"]

    def _summary_label(self, item: dict[str, Any] | None) -> str:
        if not item:
            return "selected evidence"
        service = item.get("service") or "unknown service"
        template = item.get("template_text") or item.get("redacted_message") or "selected evidence"
        return f"service `{service}`, template `{template}`"

    def _summary_source(self, packet: dict[str, Any]) -> dict[str, Any] | None:
        candidates = packet.get("root_cause_candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, dict):
                    return candidate
        edges = packet.get("causal_edges")
        if isinstance(edges, list):
            for edge in edges:
                if isinstance(edge, dict) and isinstance(edge.get("source"), dict):
                    return edge["source"]
        evidence_lines = packet.get("evidence_lines")
        if isinstance(evidence_lines, list):
            for line in evidence_lines:
                if isinstance(line, dict):
                    return line
        return None

    def _summary_target(self, packet: dict[str, Any]) -> dict[str, Any] | None:
        edges = packet.get("causal_edges")
        if isinstance(edges, list):
            for edge in edges:
                if isinstance(edge, dict) and isinstance(edge.get("target"), dict):
                    return edge["target"]
        evidence_lines = packet.get("evidence_lines")
        if isinstance(evidence_lines, list):
            for line in evidence_lines[1:]:
                if isinstance(line, dict):
                    return line
        return None

    def _summarize(self, text: str) -> dict[str, Any]:
        packet = self._summary_packet(text)
        log_ids = self._summary_log_ids(packet, text)
        first_refs = log_ids[:3]
        source = self._summary_source(packet)
        target = self._summary_target(packet)
        source_label = self._summary_label(source)
        target_label = self._summary_label(target)
        markdown = "\n".join(
            [
                "# Incident Diagnosis Summary",
                "",
                "## Internal RCA",
                (
                    f"Evidence suggests candidate source signal {source_label} may precede "
                    f"downstream symptom {target_label}. Treat this as a candidate root cause "
                    "or contributing factor that needs validation with metrics and traces "
                    "before final RCA."
                ),
                "",
                "## Evidence Claims",
                f"- Candidate chain is supported by evidence refs: {', '.join(first_refs)}.",
                "",
                "## Uncertainties",
                "- Clock skew and deployment context are not ruled out.",
                "- Service metrics and traces must validate the candidate source signal.",
            ]
        )
        return {
            "internal_rca_markdown": markdown,
            "customer_update_markdown": (
                "Evidence suggests an upstream or underlying issue contributed to the observed "
                "symptoms. Engineering is validating the candidate cause and mitigation steps."
            ),
            "evidence_claims": [
                {
                    "claim": (
                        f"Evidence suggests candidate source signal {source_label} may precede "
                        f"downstream symptom {target_label}."
                    ),
                    "evidence_refs": first_refs,
                    "confidence": 0.78,
                    "needs_validation": True,
                }
            ],
            "next_validation_steps": [
                {
                    "title": "Validate candidate source signal",
                    "description": (
                        f"Check metrics, traces, dependency health, and recent changes for "
                        f"{source_label} near the first cited evidence. Confirm whether it "
                        "started before the downstream symptoms."
                    ),
                    "priority": "high",
                    "owner_role": "SRE",
                    "evidence_refs": first_refs,
                },
                {
                    "title": "Correlate downstream symptoms",
                    "description": (
                        f"Compare {target_label} with the candidate source signal timing and "
                        "request identifiers where available."
                    ),
                    "priority": "medium",
                    "owner_role": "Developer",
                    "evidence_refs": log_ids[3:6] or first_refs,
                },
            ],
            "uncertainties": [
                "Clock skew and sparse windows may affect causal ordering.",
                "Service metrics and traces are required before final RCA.",
            ],
            "confidence": 0.78,
        }


def build_annotation_payload(
    *,
    case_context: dict[str, Any],
    template: LogTemplate,
    samples: list[RepresentativeSample],
    max_sample_message_chars: int | None = None,
    max_samples_per_template: int | None = None,
) -> dict[str, Any]:
    selected_samples = samples
    if max_samples_per_template is not None and max_samples_per_template > 0:
        selected_samples = samples[:max_samples_per_template]
    return {
        "case_context": case_context,
        "template_context": {
            "template_id": template.template_id,
            "template_text": _truncate_text(
                template.template_text,
                max_chars=max_sample_message_chars,
            ),
            "occurrence_count": template.occurrence_count,
            "first_seen": template.first_seen.isoformat() if template.first_seen else None,
            "last_seen": template.last_seen.isoformat() if template.last_seen else None,
            "services": template.services,
            "files": template.files,
        },
        "representative_lines": [
            {
                "sample_reason": sample.sample_reason,
                "timestamp": sample.timestamp.isoformat() if sample.timestamp else None,
                "level": sample.level,
                "service": sample.service,
                "message": _truncate_text(sample.message, max_chars=max_sample_message_chars),
                "evidence_ref": sample.evidence_ref.model_dump(mode="json"),
            }
            for sample in selected_samples
        ],
    }


async def annotate_templates(
    *,
    analysis_run_id: str,
    templates: list[LogTemplate],
    samples: list[RepresentativeSample],
    case_context: dict[str, Any],
    gateway: MockAIPlatformAnnotationGateway | None = None,
    max_templates: int | None = None,
    max_sample_message_chars: int | None = None,
    max_samples_per_template: int | None = None,
) -> tuple[list[TemplateAnnotation], list[dict[str, Any]]]:
    gateway = gateway or MockAIPlatformAnnotationGateway()
    samples_by_template: dict[str, list[RepresentativeSample]] = {}
    for sample in samples:
        samples_by_template.setdefault(sample.template_id, []).append(sample)

    annotations: list[TemplateAnnotation] = []
    model_inputs: list[dict[str, Any]] = []
    for template in _prioritized_templates(templates, max_templates=max_templates):
        payload = build_annotation_payload(
            case_context=case_context,
            template=template,
            samples=samples_by_template.get(template.template_id, []),
            max_sample_message_chars=max_sample_message_chars,
            max_samples_per_template=max_samples_per_template,
        )
        model_inputs.append(payload)
        response = await gateway.responses(
            user_id=case_context.get("user_id", "local"),
            model="gpt-5.4",
            instructions=_load_annotation_prompt(),
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": str(payload)}],
                }
            ],
            stream=False,
            metadata={
                "case_id": case_context.get("case_id"),
                "analysis_run_id": analysis_run_id,
                "purpose": "template_annotation",
                "prompt_version": PROMPT_VERSION,
            },
            reasoning_effort="high",
            response_format={"type": "json_object"},
        )
        raw = response.get("output_json", response)
        try:
            parsed = TemplateAnnotationResult.model_validate(raw)
        except ValidationError:
            parsed = TemplateAnnotationResult(
                golden_signal="unknown",
                fault_categories=["unknown"],
                entities={},
                severity_score=0.0,
                confidence=0.0,
                rationale="Model output could not be validated.",
            )
        annotations.append(
            TemplateAnnotation(
                annotation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{template.template_id}:annotation_v1")),
                template_id=template.template_id,
                analysis_run_id=analysis_run_id,
                model_provider=getattr(gateway, "provider", "ai_platform"),
                model_name="gpt-5.4",
                prompt_version=PROMPT_VERSION,
                raw_model_response=raw if isinstance(raw, dict) else {"raw": raw},
                **parsed.model_dump(),
            )
        )
    return annotations, model_inputs
