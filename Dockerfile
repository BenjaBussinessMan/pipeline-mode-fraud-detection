# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12

# Stage 1: resolve and install dependencies into an isolated virtualenv.
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN pip install -r requirements.txt

# Stage 2: test image. Run with `docker build --target test .`
FROM builder AS test

COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt

WORKDIR /app
COPY pyproject.toml .
COPY src ./src
COPY tests ./tests
RUN pytest

# Stage 3: minimal runtime. Only the venv and the source, no build tooling or tests.
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --system --uid 10001 --no-create-home appuser

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=appuser src ./src

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "fraud.api.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
