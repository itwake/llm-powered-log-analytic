# Minimal single-container LogAn: API and web workbench in one image.
#
#   docker build -f infra/docker/standalone.Dockerfile -t logan-standalone .
#   docker run --rm -p 8000:8000 -p 3000:3000 -v logan-data:/data logan-standalone
#
# Defaults are self-contained: SQLite metadata and the local object store on
# /data, deterministic mock LLM analysis, and mock SSO sign-in. Intended for
# demos and single-user evaluation; production deployments use the separate
# api/web/worker images.

FROM mirror.gcr.io/library/ubuntu:24.04 AS base

ARG UBUNTU_APT_MIRROR=http://mirrors.aliyun.com/ubuntu
ARG UBUNTU_SECURITY_APT_MIRROR=http://mirrors.aliyun.com/ubuntu

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN sed -i \
        -e "s|http://archive.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
        -e "s|http://security.ubuntu.com/ubuntu|${UBUNTU_SECURITY_APT_MIRROR}|g" \
        /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        python3.12 \
        python3.12-venv \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_24.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

FROM base AS web-builder

WORKDIR /app
# Inlined into the client bundle at build time; the browser reaches the API on
# its published host port.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm ci
COPY apps/web ./apps/web
RUN npm run build --workspace @logan/web

FROM base AS runner

WORKDIR /app
RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    NODE_ENV=production

COPY pyproject.toml README.md constraints.txt ./
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir . -c constraints.txt

COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm ci --omit=dev
COPY --from=web-builder /app/apps/web/.next ./apps/web/.next
COPY --from=web-builder /app/apps/web/next.config.ts ./apps/web/next.config.ts

COPY infra/docker/standalone-entrypoint.sh /usr/local/bin/standalone-entrypoint.sh
RUN chmod +x /usr/local/bin/standalone-entrypoint.sh && mkdir -p /data

# Self-contained single-user defaults; override any of these at run time.
ENV LOGAN_ENV=development \
    LOGAN_LLM_PROVIDER=mock \
    LOGAN_STORE_BACKEND=auto \
    LOGAN_DATABASE_URL=sqlite:////data/logan.db \
    LOGAN_OBJECT_STORE_BACKEND=local \
    LOGAN_LOCAL_OBJECT_STORE_DIR=/data/object-store \
    LOGAN_ANALYSIS_INPUT_TMP_DIR=/tmp/logan-analysis-inputs \
    LOGAN_ANALYSIS_ORCHESTRATOR=local \
    LOGAN_SSO_ENABLED=true \
    LOGAN_SSO_MOCK_ENABLED=true \
    LOGAN_SSO_AUTHORIZE_URL=http://localhost:8000/api/auth/sso/mock/authorize \
    LOGAN_SSO_TOKEN_URL=http://localhost:8000/api/auth/sso/mock/token \
    LOGAN_CORS_ALLOWED_ORIGINS=http://localhost:3000 \
    LOGAN_WEB_BASE_URL=http://localhost:3000 \
    NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

VOLUME /data
EXPOSE 8000 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 CMD \
    python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()" \
    && node -e "fetch('http://127.0.0.1:3000/healthz').then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"
CMD ["/usr/local/bin/standalone-entrypoint.sh"]
