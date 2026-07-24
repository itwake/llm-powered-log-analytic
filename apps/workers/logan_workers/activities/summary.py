from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from logan_workers.algorithms.redactors import redact_text
from logan_workers.models import (
    CausalGraph,
    CausalSummary,
    EvidenceRef,
    LogTemplate,
    NormalizedLogLine,
)
from logan_workers.ports import ModelGateway
from pydantic import BaseModel, Field, ValidationError, field_validator

PROMPT_VERSION = "causal_summary_v1"
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "causal_summary_prompt.md"
MAX_PACKET_TEXT = 800
MAX_PACKET_EVIDENCE_LINES = 16
MAX_PACKET_EDGES = 8
MAX_PACKET_CANDIDATES = 5

_FORBIDDEN_PACKET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "model_input",
    "model_inputs",
    "password",
    "prompt",
    "prompts",
    "raw_line",
    "raw_line_id",
    "raw_line_ids",
    "raw_message",
    "raw_text",
    "representative_lines",
    "secret",
    "source_token",
    "token",
}
_SECRET_WORD_RE = re.compile(
    r"(?i)\b(authorization|bearer|password|passwd|secret|api[_-]?key|access[_-]?token|"
    r"source[_-]?token|token)\b"
)
_UNREDACTED_SECRET_VALUE_RE = re.compile(
    r"(?i)(authorization\s*[:=]\s*bearer\s+(?!<)[^\s,;]+|"
    r"bearer\s+(?!<)[A-Za-z0-9._~+/=-]+|"
    r"\b(?:password|passwd|secret|api[_-]?key|token|access[_-]?token|source[_-]?token)"
    r"\s*[:=]\s*(?!<)[^\s,;]+|"
    r"\b(?:gh[opsru]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+|"
    r"sk-[A-Za-z0-9_-]{10,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b)"
)


class SummaryEvidenceLine(BaseModel):
    log_id: str
    template_id: str | None = None
    line_number: int
    service: str | None = None
    time: str | None = None
    redacted_message: str
    template_text: str | None = None
    confidence: float = Field(ge=0, le=1)
    method: str


class SummaryTemplateEvidence(BaseModel):
    template_id: str
    template_text: str
    service: str | None = None
    time: str | None = None
    confidence: float = Field(ge=0, le=1)
    method: str


class SummaryEdgeEvidence(BaseModel):
    method: str
    confidence: float = Field(ge=0, le=1)
    source: SummaryTemplateEvidence
    target: SummaryTemplateEvidence
    needs_validation: bool = True


class SummaryRootCauseCandidateEvidence(BaseModel):
    template_id: str
    template_text: str
    service: str | None = None
    time: str | None = None
    confidence: float = Field(ge=0, le=1)
    method: str = "candidate_root_cause_rank"


class SummaryEvidencePacket(BaseModel):
    case_context: dict[str, str | None]
    evidence_lines: list[SummaryEvidenceLine]
    causal_edges: list[SummaryEdgeEvidence]
    root_cause_candidates: list[SummaryRootCauseCandidateEvidence]


class CausalSummaryClaim(BaseModel):
    claim: str = Field(min_length=1, max_length=1200)
    evidence_refs: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    needs_validation: bool = True

    @field_validator("claim")
    @classmethod
    def claim_must_be_cautious(cls, value: str) -> str:
        lowered = value.lower()
        cautious_terms = ("candidate", "likely", "evidence suggests", "needs validation")
        if not any(term in lowered for term in cautious_terms):
            return f"Candidate finding: {value}"
        return value


class CausalSummaryNextValidationStep(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=800)
    priority: Literal["high", "medium", "low"] = "medium"
    owner_role: str = Field(default="SRE", max_length=80)
    evidence_refs: list[str] = Field(default_factory=list)


class CausalSummaryModelOutput(BaseModel):
    internal_rca_markdown: str = Field(min_length=1, max_length=12000)
    customer_update_markdown: str = Field(min_length=1, max_length=12000)
    evidence_claims: list[CausalSummaryClaim] = Field(min_length=1)
    next_validation_steps: list[CausalSummaryNextValidationStep] = Field(min_length=1)
    uncertainties: list[str] = Field(min_length=1, max_length=8)
    confidence: float = Field(ge=0, le=1)


def _safe_text(value: object, *, max_length: int = MAX_PACKET_TEXT) -> str:
    text = redact_text(str(value or ""))
    text = _SECRET_WORD_RE.sub("<REDACTED_FIELD>", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_length:
        return f"{text[: max_length - 3]}..."
    return text


def _iso_time(value: Any) -> str | None:
    return value.isoformat() if value else None


def _template_service(
    template: LogTemplate,
    lines_by_template: dict[str, list[NormalizedLogLine]],
) -> str | None:
    if template.services:
        return template.services[0]
    for line in lines_by_template.get(template.template_id, []):
        if line.service:
            return line.service
    return None


def _template_confidence(
    template_id: str,
    lines_by_template: dict[str, list[NormalizedLogLine]],
) -> float:
    lines = lines_by_template.get(template_id, [])
    if not lines:
        return 0.0
    return round(max(line.confidence for line in lines), 4)


def _line_method(line: NormalizedLogLine) -> str:
    categories = "+".join(line.fault_categories[:3])
    parts = [part for part in (line.golden_signal, categories) if part]
    return "+".join(parts) if parts else "log_evidence"


def _edge_template_evidence(
    *,
    template: LogTemplate,
    method: str,
    confidence: float,
    lines_by_template: dict[str, list[NormalizedLogLine]],
) -> SummaryTemplateEvidence:
    return SummaryTemplateEvidence(
        template_id=template.template_id,
        template_text=_safe_text(template.template_text),
        service=_template_service(template, lines_by_template),
        time=_iso_time(template.first_seen),
        confidence=round(confidence, 4),
        method=method,
    )


def _log_line_evidence(line: NormalizedLogLine) -> SummaryEvidenceLine:
    return SummaryEvidenceLine(
        log_id=line.log_id,
        template_id=line.template_id,
        line_number=line.line_number,
        service=line.service,
        time=_iso_time(line.timestamp),
        redacted_message=_safe_text(line.redacted_message),
        template_text=_safe_text(line.template_text) if line.template_text else None,
        confidence=round(line.confidence, 4),
        method=_line_method(line),
    )


def _safe_case_context(case_context: dict[str, Any] | None) -> dict[str, str | None]:
    context = case_context or {}
    allowed_keys = (
        "case_id",
        "analysis_run_id",
        "title",
        "issue_description",
        "product",
        "environment",
    )
    safe: dict[str, str | None] = {}
    for key in allowed_keys:
        value = context.get(key)
        safe[key] = None if value is None else _safe_text(value, max_length=600)
    return safe


def _assert_summary_packet_safe(value: Any) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in _FORBIDDEN_PACKET_KEYS:
                raise ValueError(f"unsafe causal summary evidence packet key: {key}")
            _assert_summary_packet_safe(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_summary_packet_safe(nested)
    elif isinstance(value, str):
        if _UNREDACTED_SECRET_VALUE_RE.search(value):
            raise ValueError("unsafe causal summary evidence packet string")


def _logs_by_template(logs: list[NormalizedLogLine]) -> dict[str, list[NormalizedLogLine]]:
    grouped: dict[str, list[NormalizedLogLine]] = defaultdict(list)
    for line in logs:
        if line.template_id:
            grouped[line.template_id].append(line)
    return grouped


def _ranked_evidence_lines(
    *,
    causal_graph: CausalGraph,
    logs: list[NormalizedLogLine],
    lines_by_template: dict[str, list[NormalizedLogLine]],
) -> list[NormalizedLogLine]:
    by_log_id = {line.log_id: line for line in logs}
    ranked: list[NormalizedLogLine] = []
    seen: set[str] = set()

    def add_line(line: NormalizedLogLine | None) -> None:
        if line is None or line.log_id in seen:
            return
        seen.add(line.log_id)
        ranked.append(line)

    for node in causal_graph.nodes:
        for ref in node.evidence_refs[:1]:
            add_line(by_log_id.get(ref.log_id))

    for edge in causal_graph.edges[:MAX_PACKET_EDGES]:
        for template_id in (edge.source_template_id, edge.target_template_id):
            candidates = lines_by_template.get(template_id, [])
            if candidates:
                add_line(max(candidates, key=lambda line: (line.severity_score, line.confidence)))

    if len(ranked) < MAX_PACKET_EVIDENCE_LINES:
        fallback_lines = sorted(
            logs,
            key=lambda line: (-line.severity_score, -line.confidence, line.ingestion_order),
        )
        for line in fallback_lines:
            if line.template_id:
                add_line(line)
            if len(ranked) >= MAX_PACKET_EVIDENCE_LINES:
                break

    return ranked[:MAX_PACKET_EVIDENCE_LINES]


def build_causal_summary_evidence_packet(
    *,
    causal_graph: CausalGraph,
    templates: list[LogTemplate],
    logs: list[NormalizedLogLine],
    case_context: dict[str, Any] | None = None,
) -> SummaryEvidencePacket:
    templates_by_id = {template.template_id: template for template in templates}
    lines_by_template = _logs_by_template(logs)

    edges: list[SummaryEdgeEvidence] = []
    for edge in causal_graph.edges[:MAX_PACKET_EDGES]:
        source_template = templates_by_id.get(edge.source_template_id)
        target_template = templates_by_id.get(edge.target_template_id)
        if source_template is None or target_template is None:
            continue
        edges.append(
            SummaryEdgeEvidence(
                method=edge.method,
                confidence=round(edge.confidence, 4),
                source=_edge_template_evidence(
                    template=source_template,
                    method=f"source:{edge.method}",
                    confidence=_template_confidence(source_template.template_id, lines_by_template),
                    lines_by_template=lines_by_template,
                ),
                target=_edge_template_evidence(
                    template=target_template,
                    method=f"target:{edge.method}",
                    confidence=_template_confidence(target_template.template_id, lines_by_template),
                    lines_by_template=lines_by_template,
                ),
                needs_validation=edge.needs_validation,
            )
        )

    candidates: list[SummaryRootCauseCandidateEvidence] = []
    for candidate in causal_graph.root_cause_candidates[:MAX_PACKET_CANDIDATES]:
        template = templates_by_id.get(candidate.template_id)
        if template is None:
            continue
        candidates.append(
            SummaryRootCauseCandidateEvidence(
                template_id=template.template_id,
                template_text=_safe_text(template.template_text),
                service=_template_service(template, lines_by_template),
                time=_iso_time(template.first_seen),
                confidence=round(candidate.score, 4),
            )
        )

    packet = SummaryEvidencePacket(
        case_context=_safe_case_context(case_context),
        evidence_lines=[
            _log_line_evidence(line)
            for line in _ranked_evidence_lines(
                causal_graph=causal_graph,
                logs=logs,
                lines_by_template=lines_by_template,
            )
        ],
        causal_edges=edges,
        root_cause_candidates=candidates,
    )
    _assert_summary_packet_safe(packet)
    return packet


def _evidence_refs_from_packet(
    packet: SummaryEvidencePacket,
    logs: list[NormalizedLogLine],
) -> tuple[list[EvidenceRef], dict[str, EvidenceRef]]:
    by_log_id = {line.log_id: line for line in logs}
    refs: list[EvidenceRef] = []
    ref_by_log_id: dict[str, EvidenceRef] = {}
    for item in packet.evidence_lines:
        line = by_log_id.get(item.log_id)
        if line is None:
            continue
        ref = line.evidence_ref()
        refs.append(ref)
        ref_by_log_id[item.log_id] = ref
    return refs, ref_by_log_id


_RESOURCE_KEYWORDS = (
    "capacity",
    "connection",
    "cpu",
    "disk",
    "exhaust",
    "limit",
    "memory",
    "pool",
    "pressure",
    "quota",
    "resource",
    "saturation",
    "throttle",
)
_DEPENDENCY_KEYWORDS = (
    "dependency",
    "downstream",
    "rpc",
    "timeout",
    "unavailable",
    "upstream",
)
_SYMPTOM_KEYWORDS = (
    "availability",
    "error",
    "failed",
    "failure",
    "latency",
    "status",
)


def _template_descriptor(item: SummaryTemplateEvidence | SummaryRootCauseCandidateEvidence) -> str:
    service = f"service `{item.service}`" if item.service else "unknown service"
    time = f", time `{item.time}`" if item.time else ""
    return f"{service}, template `{item.template_text}`{time}"


def _line_descriptor(line: SummaryEvidenceLine) -> str:
    service = f"service `{line.service}`" if line.service else "unknown service"
    time = f", time `{line.time}`" if line.time else ""
    template = f", template `{line.template_text}`" if line.template_text else ""
    return f"{service}, log `{line.log_id}` line {line.line_number}{template}{time}"


def _primary_source_signal(
    packet: SummaryEvidencePacket,
) -> SummaryRootCauseCandidateEvidence | SummaryTemplateEvidence | SummaryEvidenceLine | None:
    if packet.root_cause_candidates:
        return packet.root_cause_candidates[0]
    if packet.causal_edges:
        return packet.causal_edges[0].source
    return packet.evidence_lines[0] if packet.evidence_lines else None


def _primary_downstream_signal(
    packet: SummaryEvidencePacket,
) -> SummaryTemplateEvidence | SummaryEvidenceLine | None:
    if packet.causal_edges:
        return packet.causal_edges[0].target
    return packet.evidence_lines[1] if len(packet.evidence_lines) > 1 else None


def _signal_descriptor(
    item: SummaryRootCauseCandidateEvidence | SummaryTemplateEvidence | SummaryEvidenceLine | None,
) -> str:
    if item is None:
        return "the selected evidence"
    if isinstance(item, SummaryEvidenceLine):
        return _line_descriptor(item)
    return _template_descriptor(item)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _line_text(line: SummaryEvidenceLine) -> str:
    return " ".join(
        filter(None, [line.service, line.redacted_message, line.template_text, line.method])
    )


def _first_line_matching(
    packet: SummaryEvidencePacket,
    keywords: tuple[str, ...],
) -> SummaryEvidenceLine | None:
    for line in packet.evidence_lines:
        if _contains_any(_line_text(line), keywords):
            return line
    return None


def _affected_services(packet: SummaryEvidencePacket) -> list[str]:
    services: list[str] = []
    for service in [
        *(line.service for line in packet.evidence_lines),
        *(edge.source.service for edge in packet.causal_edges),
        *(edge.target.service for edge in packet.causal_edges),
        *(candidate.service for candidate in packet.root_cause_candidates),
    ]:
        if service and service not in services:
            services.append(service)
    return services


def _detected_signals(packet: SummaryEvidencePacket) -> list[str]:
    signals: list[str] = []
    source_signal = _primary_source_signal(packet)
    downstream_signal = _primary_downstream_signal(packet)
    if source_signal is not None:
        signals.append(f"Candidate source signal: {_signal_descriptor(source_signal)}.")
    if downstream_signal is not None:
        signals.append(f"Downstream symptom: {_signal_descriptor(downstream_signal)}.")

    services = _affected_services(packet)
    if services:
        quoted = ", ".join(f"`{service}`" for service in services[:6])
        signals.append(f"Affected service(s): {quoted} appear in selected evidence.")

    resource_line = _first_line_matching(packet, _RESOURCE_KEYWORDS)
    dependency_line = _first_line_matching(packet, _DEPENDENCY_KEYWORDS)
    if resource_line is not None:
        signals.append(f"Dependency/resource signal: {_line_descriptor(resource_line)}.")
    elif dependency_line is not None:
        signals.append(f"Dependency/resource signal: {_line_descriptor(dependency_line)}.")

    symptom_line = _first_line_matching(packet, _SYMPTOM_KEYWORDS)
    if symptom_line is not None and downstream_signal is None:
        signals.append(f"Downstream symptom: {_line_descriptor(symptom_line)}.")
    return signals


def _edge_line(index: int, edge: SummaryEdgeEvidence) -> str:
    return (
        f"{index}. Evidence suggests candidate source signal {_template_descriptor(edge.source)} "
        f"may precede downstream symptom {_template_descriptor(edge.target)} "
        f"(confidence {edge.confidence:.2f}, method {edge.method}, needs validation)."
    )


def _claim_ref_ids(refs: list[EvidenceRef]) -> list[str]:
    return [ref.log_id for ref in refs[:4]]


def _fallback_next_actions(
    *,
    packet: SummaryEvidencePacket,
    refs: list[EvidenceRef],
) -> list[dict[str, Any]]:
    first_refs = [ref.model_dump(mode="json") for ref in refs[:3]]
    second_refs = [ref.model_dump(mode="json") for ref in refs[3:6] or refs[:3]]
    source_description = _signal_descriptor(_primary_source_signal(packet))
    downstream_description = _signal_descriptor(_primary_downstream_signal(packet))
    actions = [
        {
            "title": "Validate candidate source signal",
            "description": (
                f"Review metrics, traces, recent changes, and dependency health for "
                f"{source_description}. Treat this as a candidate source until independent "
                "telemetry confirms or rules it out."
            ),
            "priority": "high",
            "owner_role": "SRE",
            "evidence_refs": first_refs,
        },
        {
            "title": "Correlate downstream symptoms",
            "description": (
                f"Compare downstream evidence for {downstream_description} with the candidate "
                "source timing, request identifiers, traces, and retry behavior where available."
            ),
            "priority": "medium",
            "owner_role": "Developer",
            "evidence_refs": second_refs,
        },
    ]
    if _first_line_matching(packet, _RESOURCE_KEYWORDS) is None:
        return actions
    actions.append(
        {
            "title": "Validate dependency or resource pressure",
            "description": (
                "Review capacity, dependency, retry, and saturation metrics associated with the "
                "referenced evidence to determine whether pressure amplified the incident."
            ),
            "priority": "medium",
            "owner_role": "SRE",
            "evidence_refs": second_refs,
        }
    )
    return actions


def _fallback_summary(
    *,
    packet: SummaryEvidencePacket,
    evidence_refs: list[EvidenceRef],
    reason: str,
) -> CausalSummary:
    signals = _detected_signals(packet)
    source_signal = _primary_source_signal(packet)
    source_description = _signal_descriptor(source_signal)
    next_actions = _fallback_next_actions(packet=packet, refs=evidence_refs)
    chain_lines = [
        _edge_line(index, edge) for index, edge in enumerate(packet.causal_edges[:5], start=1)
    ]
    if not chain_lines:
        chain_lines.append(
            "No candidate causal chain met the confidence threshold; more evidence is needed."
        )

    candidate_lines = [
        (
            f"- {_template_descriptor(candidate)}: candidate root-cause signal, "
            f"score {candidate.confidence:.2f}, needs validation."
        )
        for candidate in packet.root_cause_candidates[:3]
    ]
    evidence_lines = [
        f"- log_id `{line.log_id}`, line {line.line_number}, template `{line.template_id}`, "
        f"service `{line.service or 'unknown'}`, time `{line.time or 'unknown'}`"
        for line in packet.evidence_lines[:12]
    ]
    uncertainty_lines = [
        "Candidate edges need validation with service metrics, traces, and deployment context.",
        "Clock skew, missing timestamps, and sparse windows may affect causal ordering.",
        (
            "Fallback summary was generated from structured evidence only because the LLM output "
            "was unavailable or invalid."
        ),
    ]
    signal_lines = [f"- {signal}" for signal in signals] or [
        (
            "- Structured evidence contains candidate service and template relationships, but no "
            "explicit source, downstream, or dependency/resource signal was strong enough to "
            "summarize."
        )
    ]
    next_action_lines = [
        f"- {action['title']}: {action['description']}" for action in next_actions
    ]
    markdown = "\n".join(
        [
            "# Incident Diagnosis Summary",
            "",
            "## 1. Overview",
            (
                "Evidence suggests a candidate incident chain, not a definitive root cause. "
                "The finding needs validation before it is used for final RCA."
            ),
            "",
            "## 2. Observed Evidence Signals",
            *signal_lines,
            "",
            "## 3. Candidate Causal Chain",
            *chain_lines,
            "",
            "## 4. Candidate Root Cause",
            *(
                candidate_lines
                or ["- No root cause candidate exceeded the minimum evidence threshold."]
            ),
            "",
            "## 5. Evidence References",
            *(evidence_lines or ["- No evidence refs available."]),
            "",
            "## 6. Uncertainties",
            *[f"- {line}" for line in uncertainty_lines],
            "",
            "## 7. Next Validation Actions",
            *next_action_lines,
            "",
            "## 8. Customer-safe Update",
            (
                "Evidence suggests a likely upstream or underlying issue contributed to the "
                "observed symptoms. Engineering is validating the candidate cause and mitigation "
                "steps."
            ),
        ]
    )
    edge_confidence = [edge.confidence for edge in packet.causal_edges[:3]]
    confidence = (
        round(sum(edge_confidence) / len(edge_confidence), 4) if edge_confidence else 0.0
    )
    claim_refs = _claim_ref_ids(evidence_refs)
    return CausalSummary(
        summary_markdown=markdown,
        customer_update_markdown=(
            "Evidence suggests a likely upstream or underlying issue contributed to the observed "
            "symptoms. Engineering is validating the candidate cause and mitigation steps."
        ),
        next_actions=next_actions,
        evidence_refs=evidence_refs[:12],
        evidence_claims=[
            {
                "claim": (
                    f"Candidate source signal {source_description} may be an early contributing "
                    "signal and needs validation."
                ),
                "evidence_refs": claim_refs,
                "confidence": confidence,
                "needs_validation": True,
            }
        ],
        uncertainties=uncertainty_lines,
        details={
            "source": "fallback",
            "fallback_reason": reason,
            "prompt_version": PROMPT_VERSION,
            "evidence_packet_counts": {
                "evidence_lines": len(packet.evidence_lines),
                "causal_edges": len(packet.causal_edges),
                "root_cause_candidates": len(packet.root_cause_candidates),
            },
            "detected_signals": signals,
        },
        confidence=confidence,
    )


def _load_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return (
            "Generate a cautious incident diagnosis from structured evidence only. "
            "Return valid JSON with internal RCA markdown, customer update markdown, "
            "evidence claims, next validation steps, uncertainties, and confidence."
        )


async def _call_gateway(
    *,
    gateway: ModelGateway,
    packet: SummaryEvidencePacket,
    case_context: dict[str, Any] | None,
) -> dict[str, Any]:
    response = await gateway.responses(
        user_id=(case_context or {}).get("user_id", "local"),
        model=(case_context or {}).get("model", "gpt-5.4"),
        instructions=_load_prompt(),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(packet.model_dump(mode="json"), sort_keys=True),
                    }
                ],
            }
        ],
        stream=False,
        metadata={
            "case_id": packet.case_context.get("case_id"),
            "analysis_run_id": packet.case_context.get("analysis_run_id"),
            "purpose": "causal_summary",
            "prompt_version": PROMPT_VERSION,
        },
        reasoning_effort="high",
        response_format={"type": "json_object"},
    )
    if isinstance(response, AsyncIterator):
        raise ValueError("causal summary gateway unexpectedly returned a stream")
    return response


def _sanitize_output_text(value: str) -> str:
    # Sanitize line by line so markdown structure (headings, lists, and blank
    # lines between paragraphs) survives; _safe_text collapses all whitespace.
    lines = str(value or "").splitlines()
    sanitized = "\n".join(_safe_text(line, max_length=2000) for line in lines)
    if len(sanitized) > 12000:
        return f"{sanitized[:11997]}..."
    return sanitized


def _valid_ref_ids(ref_ids: list[str], ref_by_log_id: dict[str, EvidenceRef]) -> list[str]:
    valid: list[str] = []
    for ref_id in ref_ids:
        if ref_id in ref_by_log_id and ref_id not in valid:
            valid.append(ref_id)
    return valid


def _next_action_refs(
    ref_ids: list[str],
    ref_by_log_id: dict[str, EvidenceRef],
    fallback_refs: list[EvidenceRef],
) -> list[dict[str, Any]]:
    selected = [ref_by_log_id[ref_id] for ref_id in _valid_ref_ids(ref_ids, ref_by_log_id)]
    if not selected:
        selected = fallback_refs[:3]
    return [ref.model_dump(mode="json") for ref in selected[:5]]


def parse_causal_summary_model_output(
    *,
    raw: Any,
    packet: SummaryEvidencePacket,
    evidence_refs: list[EvidenceRef],
    ref_by_log_id: dict[str, EvidenceRef],
) -> CausalSummary:
    parsed = CausalSummaryModelOutput.model_validate(raw)
    sanitized_claims: list[dict[str, Any]] = []
    for claim in parsed.evidence_claims:
        valid_refs = _valid_ref_ids(claim.evidence_refs, ref_by_log_id)
        if not valid_refs:
            raise ValueError("causal summary claim did not cite provided evidence")
        sanitized_claims.append(
            {
                "claim": _sanitize_output_text(claim.claim),
                "evidence_refs": valid_refs,
                "confidence": round(claim.confidence, 4),
                "needs_validation": True,
            }
        )

    next_actions = [
        {
            "title": _sanitize_output_text(step.title),
            "description": _sanitize_output_text(step.description),
            "priority": step.priority,
            "owner_role": _sanitize_output_text(step.owner_role),
            "evidence_refs": _next_action_refs(step.evidence_refs, ref_by_log_id, evidence_refs),
        }
        for step in parsed.next_validation_steps
    ]
    uncertainties = [_sanitize_output_text(item) for item in parsed.uncertainties if item.strip()]
    summary_markdown = _sanitize_output_text(parsed.internal_rca_markdown)
    lowered_markdown = summary_markdown.lower()
    if "candidate" not in lowered_markdown or "needs validation" not in lowered_markdown:
        summary_markdown += (
            "\n\nCandidate findings above need validation with service metrics, traces, "
            "and deployment context."
        )
    return CausalSummary(
        summary_markdown=summary_markdown,
        customer_update_markdown=_sanitize_output_text(parsed.customer_update_markdown),
        next_actions=next_actions,
        evidence_refs=evidence_refs[:12],
        evidence_claims=sanitized_claims,
        uncertainties=uncertainties,
        details={
            "source": "llm",
            "prompt_version": PROMPT_VERSION,
            "evidence_packet_counts": {
                "evidence_lines": len(packet.evidence_lines),
                "causal_edges": len(packet.causal_edges),
                "root_cause_candidates": len(packet.root_cause_candidates),
            },
        },
        confidence=round(parsed.confidence, 4),
    )


async def render_causal_summary(
    *,
    causal_graph: CausalGraph,
    templates: list[LogTemplate],
    logs: list[NormalizedLogLine],
    case_context: dict[str, Any] | None = None,
    gateway: ModelGateway | None = None,
) -> CausalSummary:
    packet = build_causal_summary_evidence_packet(
        causal_graph=causal_graph,
        templates=templates,
        logs=logs,
        case_context=case_context,
    )
    evidence_refs, ref_by_log_id = _evidence_refs_from_packet(packet, logs)
    if gateway is None:
        return _fallback_summary(
            packet=packet,
            evidence_refs=evidence_refs,
            reason="gateway_unavailable",
        )

    try:
        response = await _call_gateway(gateway=gateway, packet=packet, case_context=case_context)
        raw = response.get("output_json", response) if isinstance(response, dict) else response
        return parse_causal_summary_model_output(
            raw=raw,
            packet=packet,
            evidence_refs=evidence_refs,
            ref_by_log_id=ref_by_log_id,
        )
    except (ValidationError, ValueError, TypeError, AttributeError, RuntimeError):
        return _fallback_summary(
            packet=packet,
            evidence_refs=evidence_refs,
            reason="gateway_unavailable_or_invalid_model_output",
        )
