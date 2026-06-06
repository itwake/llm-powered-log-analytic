export const caseId = "fixture-case";
export const runId = "fixture-run";

export const cases = [
  {
    case_id: caseId,
    case_key: "LOGAN-20260606-0001",
    title: "Checkout API intermittent 500 errors",
    status: "ready",
    product: "commerce-platform",
    service: "checkout",
    environment: "production"
  }
];

export const summaryItems = [
  {
    template_id: "auth-pool",
    representative_message: "WARN auth-service db connection pool exhausted active=50 max=50",
    golden_signal: "saturation",
    fault_categories: ["resource", "database"],
    occurrence_count: 1,
    first_seen: "2026-06-06T10:11:30Z",
    services: ["auth-service"],
    confidence: 0.92
  },
  {
    template_id: "payment-timeout",
    representative_message: "ERROR payment-service timeout calling auth-service after 30000ms",
    golden_signal: "availability",
    fault_categories: ["dependency", "timeout"],
    occurrence_count: 2,
    first_seen: "2026-06-06T10:12:01Z",
    services: ["payment-service"],
    confidence: 0.91
  },
  {
    template_id: "gateway-500",
    representative_message: "ERROR gateway POST /checkout failed status=500 duration_ms=31000",
    golden_signal: "error",
    fault_categories: ["application"],
    occurrence_count: 2,
    first_seen: "2026-06-06T10:12:31Z",
    services: ["gateway"],
    confidence: 0.89
  }
];

export const temporalSeries = [
  {name: "saturation", points: [{window_start: "10:11", count: 1}]},
  {name: "availability", points: [{window_start: "10:12", count: 2}, {window_start: "10:13", count: 2}]},
  {name: "error", points: [{window_start: "10:12", count: 1}, {window_start: "10:13", count: 1}]}
];

export const logs = [
  {
    timestamp: "2026-06-06T10:11:30Z",
    level: "WARN",
    service: "auth-service",
    file_path: "auth.log",
    line_number: 1,
    message: "WARN auth-service db connection pool exhausted active=50 max=50",
    golden_signal: "saturation"
  },
  {
    timestamp: "2026-06-06T10:12:01Z",
    level: "ERROR",
    service: "payment-service",
    file_path: "payment.log",
    line_number: 2,
    message: "ERROR payment-service timeout calling auth-service after 30000ms request_id=<UUID>",
    golden_signal: "availability"
  },
  {
    timestamp: "2026-06-06T10:12:31Z",
    level: "ERROR",
    service: "gateway",
    file_path: "gateway.log",
    line_number: 2,
    message: "ERROR gateway POST /checkout failed status=500 duration_ms=31000",
    golden_signal: "error"
  }
];

export const graph = {
  nodes: [
    {id: "auth-pool", label: "auth-service connection pool exhausted", rank_score: 0.91},
    {id: "payment-timeout", label: "payment-service timeout calling auth-service", rank_score: 0.79},
    {id: "gateway-500", label: "gateway checkout failed 500", rank_score: 0.61}
  ],
  edges: [
    {source: "auth-pool", target: "payment-timeout", confidence: 0.78, needs_validation: true},
    {source: "payment-timeout", target: "gateway-500", confidence: 0.74, needs_validation: true}
  ]
};

export const summaryMarkdown = `# Incident Diagnosis Summary

## 1. Overview
Evidence suggests a likely upstream dependency saturation contributed to checkout failures. This remains a candidate cause and needs validation.

## 3. Candidate Causal Chain
1. auth-service connection pool saturation may have preceded payment-service auth timeouts.
2. payment-service timeouts may have preceded gateway checkout 500 responses.

## 6. Uncertainties
- Clock skew and missing service metrics are not ruled out.
- The causal graph is candidate evidence, not definitive proof.`;
