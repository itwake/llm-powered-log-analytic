from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


class ModelGateway(Protocol):
    """Minimal model boundary used by the analysis engine."""

    async def responses(
        self,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        ...
