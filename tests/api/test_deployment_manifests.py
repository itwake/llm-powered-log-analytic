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
