FROM mirror.gcr.io/library/ubuntu:24.04

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
        python3.12 \
        python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml README.md constraints.txt ./
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir . -c constraints.txt
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"
CMD ["sh", "-c", "uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000 --workers ${LOGAN_API_WORKERS:-1} --log-level ${LOGAN_LOG_LEVEL:-info}"]
