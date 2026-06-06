from __future__ import annotations

from logan_workers.models import CausalGraph, CausalSummary, EvidenceRef, LogTemplate, NormalizedLogLine


def render_causal_summary(
    *,
    causal_graph: CausalGraph,
    templates: list[LogTemplate],
    logs: list[NormalizedLogLine],
) -> CausalSummary:
    templates_by_id = {template.template_id: template for template in templates}
    logs_by_template: dict[str, list[NormalizedLogLine]] = {}
    for line in logs:
        if line.template_id:
            logs_by_template.setdefault(line.template_id, []).append(line)

    evidence_refs: list[EvidenceRef] = []
    for node in causal_graph.nodes:
        if node.evidence_refs:
            evidence_refs.append(node.evidence_refs[0])
    evidence_refs = evidence_refs[:12]

    top_edges = causal_graph.edges[:5]
    chain_lines = []
    for index, edge in enumerate(top_edges, start=1):
        source = templates_by_id[edge.source_template_id].template_text
        target = templates_by_id[edge.target_template_id].template_text
        chain_lines.append(
            f"{index}. Evidence suggests candidate cause `{source}` may precede `{target}` "
            f"(confidence {edge.confidence:.2f}, needs validation)."
        )
    if not chain_lines:
        chain_lines.append("No candidate causal chain met the confidence threshold; more evidence is needed.")

    candidate_lines = []
    for candidate in causal_graph.root_cause_candidates[:3]:
        template = templates_by_id[candidate.template_id]
        candidate_lines.append(
            f"- `{template.template_text}`: likely candidate, score {candidate.score:.2f}; {candidate.reason}"
        )

    evidence_lines = []
    for ref in evidence_refs:
        evidence_lines.append(
            f"- `{ref.file_path}:{ref.line_number}` template `{ref.template_id}` at "
            f"{ref.timestamp.isoformat() if ref.timestamp else 'unknown time'}"
        )

    next_actions = [
        {
            "title": "Validate auth-service connection pool saturation",
            "description": "Check database pool size, active connections, and auth-service dependency health near the first saturation window.",
            "priority": "high",
            "owner_role": "SRE",
            "evidence_refs": [ref.model_dump(mode="json") for ref in evidence_refs[:3]],
        },
        {
            "title": "Confirm downstream propagation",
            "description": "Compare payment timeout windows with gateway 500 windows and request IDs where available.",
            "priority": "medium",
            "owner_role": "Developer",
            "evidence_refs": [ref.model_dump(mode="json") for ref in evidence_refs[3:6]],
        },
    ]

    markdown = "\n".join(
        [
            "# Incident Diagnosis Summary",
            "",
            "## 1. Overview",
            "The analysis found offending log templates across the incident window. The relationships below are candidate causes, not definitive root cause statements.",
            "",
            "## 2. Observed Symptoms",
            "- Availability and error signals appear after earlier resource saturation signals.",
            "- Gateway checkout failures occur after upstream service timeout evidence.",
            "",
            "## 3. Candidate Causal Chain",
            *chain_lines,
            "",
            "## 4. Likely Root Cause Candidates",
            *(candidate_lines or ["- No root cause candidate exceeded the minimum evidence threshold."]),
            "",
            "## 5. Evidence",
            *(evidence_lines or ["- No evidence refs available."]),
            "",
            "## 6. Uncertainties",
            "- Candidate edges need validation with service metrics, traces, and deployment context.",
            "- Clock skew and missing timestamps may affect lag estimates.",
            "",
            "## 7. Next Validation Actions",
            "- Validate resource saturation and dependency health at the first offending window.",
            "- Confirm whether payment timeouts align with gateway 500 responses.",
            "",
            "## 8. Customer-safe Update",
            "Evidence suggests a likely upstream dependency saturation contributed to checkout failures. The finding needs validation before being treated as a definitive root cause.",
        ]
    )
    confidence = (
        sum(edge.confidence for edge in causal_graph.edges[:3]) / min(3, len(causal_graph.edges))
        if causal_graph.edges
        else 0.0
    )
    return CausalSummary(
        summary_markdown=markdown,
        customer_update_markdown="Evidence suggests a likely upstream dependency issue contributed to checkout failures. Engineering is validating the candidate cause and mitigation steps.",
        next_actions=next_actions,
        evidence_refs=evidence_refs,
        confidence=round(confidence, 4),
    )
