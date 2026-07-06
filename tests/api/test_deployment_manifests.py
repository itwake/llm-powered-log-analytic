from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVED_UBUNTU_2404_BASE_IMAGES = {
    "mirror.gcr.io/library/ubuntu:24.04",
    "mirror.gcr.io/library/ubuntu:24.04",
}


def test_kubernetes_migration_job_uses_project_runner() -> None:
    manifest = (REPO_ROOT / "infra" / "k8s" / "migration-job.yaml").read_text(encoding="utf-8")

    assert "scripts/run_migrations.py" in manifest
    assert "alembic" not in manifest.lower()


def test_kubernetes_config_exposes_deployment_runtime_settings() -> None:
    manifest = (REPO_ROOT / "infra" / "k8s" / "configmap.yaml").read_text(encoding="utf-8")

    assert "LOGAN_CORS_ALLOWED_ORIGINS" in manifest
    assert "LOGAN_SSO_ENABLED" in manifest
    assert "LOGAN_SSO_AUTHORIZE_URL" in manifest
    assert "LOGAN_WEB_BASE_URL" in manifest
    assert "LOGAN_API_WORKERS" in manifest
    assert 'FORWARDED_ALLOW_IPS: "*"' in manifest
    assert "LOGAN_LOG_LEVEL" in manifest
    assert 'NEXT_PUBLIC_API_BASE_URL: ""' in manifest
    assert "NEXT_PUBLIC_AUTH_MODE" not in manifest


def test_eks_config_trusts_forwarded_proxy_headers() -> None:
    manifest = (REPO_ROOT / "infra" / "eks" / "logan-configmap.yaml").read_text(
        encoding="utf-8"
    )

    assert 'FORWARDED_ALLOW_IPS: "*"' in manifest


def test_web_client_uses_same_origin_api_by_default() -> None:
    api_client = (REPO_ROOT / "apps" / "web" / "src" / "lib" / "api.ts").read_text(
        encoding="utf-8"
    )

    assert 'process.env.NEXT_PUBLIC_API_BASE_URL || ""' in api_client
    assert "http://localhost:8000" not in api_client


def test_api_container_can_enable_debug_logging() -> None:
    dockerfile = (REPO_ROOT / "infra" / "docker" / "api.Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "--log-level ${LOGAN_LOG_LEVEL:-info}" in dockerfile


def test_docker_compose_preserves_postgres_default_despite_local_sqlite_env() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert (
        "LOGAN_COMPOSE_DATABASE_URL:-postgresql+psycopg://logan:logan@postgres:5432/logan"
        in compose
    )
    assert "LOGAN_DATABASE_URL: ${LOGAN_DATABASE_URL" not in compose


def test_docker_compose_full_stack_enables_mock_sso_for_smoke() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'LOGAN_WEB_BASE_URL: ${LOGAN_WEB_BASE_URL:-http://localhost:3000}' in compose
    assert 'LOGAN_SSO_ENABLED: "true"' in compose
    assert (
        "LOGAN_SSO_AUTHORIZE_URL: ${LOGAN_SSO_AUTHORIZE_URL:-http://localhost:8000/api/auth/sso/mock/authorize}"
        in compose
    )
    assert (
        "LOGAN_SSO_TOKEN_URL: ${LOGAN_SSO_TOKEN_URL:-http://localhost:8000/api/auth/sso/mock/token}"
        in compose
    )
    assert 'LOGAN_SSO_MOCK_ENABLED: "true"' in compose


def test_dockerfiles_use_ubuntu_2404_external_base_images() -> None:
    dockerfiles = [
        REPO_ROOT / "infra" / "docker" / "api.Dockerfile",
        REPO_ROOT / "infra" / "docker" / "worker.Dockerfile",
        REPO_ROOT / "infra" / "docker" / "web.Dockerfile",
        REPO_ROOT / "infra" / "docker" / "standalone.Dockerfile",
    ]

    for dockerfile in dockerfiles:
        content = dockerfile.read_text(encoding="utf-8")
        stage_aliases = {
            line.split()[3]
            for line in content.splitlines()
            if line.startswith("FROM ") and len(line.split()) >= 4 and line.split()[2].upper() == "AS"
        }
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
            if image in stage_aliases:
                continue
            assert image in APPROVED_UBUNTU_2404_BASE_IMAGES
