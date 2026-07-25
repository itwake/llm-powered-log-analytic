from __future__ import annotations

from logan_analysis.algorithms.representative_sampling import select_representative_samples
from logan_analysis.models import LogTemplate, NormalizedLogLine, RepresentativeSample


def select_samples(
    logs: list[NormalizedLogLine],
    templates: list[LogTemplate],
    *,
    max_samples_per_template: int = 5,
) -> list[RepresentativeSample]:
    return select_representative_samples(
        logs, templates, max_samples_per_template=max_samples_per_template
    )
