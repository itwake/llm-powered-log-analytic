from __future__ import annotations


def pagerank(
    nodes: list[str],
    edges: list[tuple[str, str, float]],
    *,
    iterations: int = 30,
    damping: float = 0.85,
) -> dict[str, float]:
    if not nodes:
        return {}
    scores = {node: 1.0 / len(nodes) for node in nodes}
    outgoing: dict[str, list[tuple[str, float]]] = {node: [] for node in nodes}
    for source, target, weight in edges:
        if source in outgoing and target in scores:
            outgoing[source].append((target, max(weight, 0.001)))

    for _ in range(iterations):
        next_scores = {node: (1.0 - damping) / len(nodes) for node in nodes}
        for source, links in outgoing.items():
            if not links:
                share = scores[source] / len(nodes)
                for node in nodes:
                    next_scores[node] += damping * share
                continue
            weight_sum = sum(weight for _, weight in links)
            for target, weight in links:
                next_scores[target] += damping * scores[source] * (weight / weight_sum)
        scores = next_scores
    return scores
