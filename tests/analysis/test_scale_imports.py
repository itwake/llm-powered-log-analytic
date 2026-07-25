from __future__ import annotations

import importlib
import sys


def test_scale_module_imports_when_resource_is_unavailable() -> None:
    sentinel = object()
    original_scale = sys.modules.get("logan_analysis.evaluation.scale", sentinel)
    original_resource = sys.modules.get("resource", sentinel)
    sys.modules.pop("logan_analysis.evaluation.scale", None)
    sys.modules["resource"] = None

    try:
        module = importlib.import_module("logan_analysis.evaluation.scale")

        assert module.resource_module is None
        assert module._peak_rss_bytes() is None
    finally:
        sys.modules.pop("logan_analysis.evaluation.scale", None)
        if original_scale is not sentinel:
            sys.modules["logan_analysis.evaluation.scale"] = original_scale
        if original_resource is sentinel:
            sys.modules.pop("resource", None)
        else:
            sys.modules["resource"] = original_resource
