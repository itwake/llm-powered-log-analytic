from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_kubernetes_migration_job_uses_project_runner() -> None:
    manifest = (REPO_ROOT / "infra" / "k8s" / "migration-job.yaml").read_text(encoding="utf-8")

    assert "scripts/run_migrations.py" in manifest
    assert "alembic" not in manifest.lower()


def test_kubernetes_config_exposes_deployment_runtime_settings() -> None:
    manifest = (REPO_ROOT / "infra" / "k8s" / "configmap.yaml").read_text(encoding="utf-8")

    assert "LOGAN_CORS_ALLOWED_ORIGINS" in manifest
    assert "LOGAN_API_WORKERS" in manifest


def test_docker_compose_preserves_postgres_default_despite_local_sqlite_env() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert (
        "LOGAN_COMPOSE_DATABASE_URL:-postgresql+psycopg://logan:logan@postgres:5432/logan"
        in compose
    )
    assert "LOGAN_DATABASE_URL: ${LOGAN_DATABASE_URL" not in compose


def test_dockerfiles_use_ubuntu_2404_external_base_images() -> None:
    dockerfiles = [
        REPO_ROOT / "infra" / "docker" / "api.Dockerfile",
        REPO_ROOT / "infra" / "docker" / "worker.Dockerfile",
        REPO_ROOT / "infra" / "docker" / "web.Dockerfile",
    ]

    for dockerfile in dockerfiles:
        content = dockerfile.read_text(encoding="utf-8")
        from_images = [
            line.split()[1]
            for line in content.splitlines()
            if line.startswith("FROM ")
        ]

        assert from_images
        assert "alpine" not in content
        assert "python:3.12-slim" not in content
        assert "node:24-alpine" not in content
        for image in from_images:
            if image == "node-base":
                continue
            assert image == "mirror.gcr.io/library/ubuntu:24.04"
