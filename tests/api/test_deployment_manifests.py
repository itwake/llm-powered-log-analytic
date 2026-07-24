from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVED_UBUNTU_2404_BASE_IMAGE = "mirror.gcr.io/library/ubuntu:24.04"


def test_web_client_uses_same_origin_api_by_default() -> None:
    api_client = (REPO_ROOT / "apps" / "web" / "src" / "lib" / "api" / "http.ts").read_text(
        encoding="utf-8"
    )

    assert 'process.env.NEXT_PUBLIC_API_BASE_URL || ""' in api_client
    assert "http://localhost:8000" not in api_client


def test_compose_is_the_single_local_stack() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "LOGAN_DATABASE_URL: sqlite:////data/logan.db" in compose
    assert "LOGAN_LOCAL_OBJECT_STORE_DIR: /data/object-store" in compose
    assert 'LOGAN_SSO_MOCK_ENABLED: "true"' in compose
    assert "api:" in compose
    assert "web:" in compose
    assert "worker:" not in compose


def test_ci_validates_the_single_compose_stack() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "docker compose config -q" in workflow
    assert "docker compose build" in workflow
    assert "full-stack-smoke" not in workflow


def test_api_container_can_enable_debug_logging() -> None:
    dockerfile = (REPO_ROOT / "infra" / "docker" / "api.Dockerfile").read_text(encoding="utf-8")

    assert "--log-level ${LOGAN_LOG_LEVEL:-info}" in dockerfile


def test_dockerfiles_use_ubuntu_2404_external_base_images() -> None:
    dockerfiles = [
        REPO_ROOT / "infra" / "docker" / "api.Dockerfile",
        REPO_ROOT / "infra" / "docker" / "web.Dockerfile",
    ]

    for dockerfile in dockerfiles:
        content = dockerfile.read_text(encoding="utf-8")
        stage_aliases = {
            line.split()[3]
            for line in content.splitlines()
            if line.startswith("FROM ")
            and len(line.split()) >= 4
            and line.split()[2].upper() == "AS"
        }
        from_images = [line.split()[1] for line in content.splitlines() if line.startswith("FROM ")]

        assert from_images
        for image in from_images:
            if image not in stage_aliases:
                assert image == APPROVED_UBUNTU_2404_BASE_IMAGE
