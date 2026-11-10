# Backend image: used for both the API and the analysis worker.
# Scanner binaries are copied from their official, version-pinned images.
FROM zricethezav/gitleaks:v8.30.1 AS gitleaks
FROM ghcr.io/google/osv-scanner:v2.7.0 AS osv
FROM aquasec/trivy:0.76.1 AS trivy

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=gitleaks /usr/bin/gitleaks /usr/local/bin/gitleaks
COPY --from=osv /osv-scanner /usr/local/bin/osv-scanner
COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Semgrep is a scanner binary for the worker, not an app dependency, so it is installed here only.
RUN uv sync --frozen --no-dev --no-install-project \
 && uv pip install --python /app/.venv/bin/python --no-cache semgrep==1.182.0
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY scripts ./scripts

RUN useradd --system --uid 10001 --home /home/auditor --create-home auditor \
 && mkdir -p /data/workspaces && chown -R auditor /data
USER auditor
ENV PATH="/app/.venv/bin:$PATH" AUDITOR_WORKSPACE_ROOT=/data/workspaces
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
