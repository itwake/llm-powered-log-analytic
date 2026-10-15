"""GitHub Copilot pass-through: two routes that relay a caller's own tokens to GitHub and the
Copilot API from a host that can reach them. ``service.py`` states the contract."""

from app.copilot_passthrough.router import router
from app.copilot_passthrough.service import (
    MAX_REQUEST_BODY_BYTES,
    CopilotPassThrough,
    copilot_api_base_url,
)

__all__ = ["CopilotPassThrough", "MAX_REQUEST_BODY_BYTES", "copilot_api_base_url", "router"]
