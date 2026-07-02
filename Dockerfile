# Multi-stage build: frontend bundle, then Python wheel, then runtime.

# ---- Frontend build ------------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /app/web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- Python build --------------------------------------------------------
FROM python:3.12-slim AS pybuild
WORKDIR /app
RUN pip install --no-cache-dir build hatchling
COPY pyproject.toml README.md LICENSE BRANDING.md CHANGELOG.md ./
COPY src/ ./src/
# Vite writes to src/clean_evals/web/static (see web/vite.config.ts); the
# wheel packages that directory as a hatch artifact.
COPY --from=frontend /app/src/clean_evals/web/static ./src/clean_evals/web/static
RUN python -m build --wheel --outdir /wheels

# ---- Runtime -------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Non-root user (security hygiene)
RUN groupadd --system --gid 1000 cleanevals \
 && useradd  --system --uid 1000 --gid cleanevals --create-home cleanevals \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=pybuild /wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl[postgres] && rm /tmp/*.whl

# Working dir for artifacts (mountable volume)
RUN mkdir -p /app/clean-evals-data/artifacts \
 && chown -R cleanevals:cleanevals /app

USER cleanevals

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

ENTRYPOINT ["clean-evals"]
# 0.0.0.0 binds inside the container only; publish the port to loopback on
# the host (-p 127.0.0.1:8080:8080), as docker-compose.yml does.
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
