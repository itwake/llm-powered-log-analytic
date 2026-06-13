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
COPY pyproject.toml README.md ./
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir .
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -m logan_workers.healthcheck --timeout 3
CMD ["python", "-m", "logan_workers.temporal_worker"]
