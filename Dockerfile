FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --upgrade pip && \
    python -m pip wheel --wheel-dir /wheels .


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system traceaid && \
    useradd --system --gid traceaid --home-dir /app --shell /usr/sbin/nologin traceaid

COPY --from=builder /wheels /wheels
RUN python -m pip install /wheels/*.whl && rm -rf /wheels

USER traceaid

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"]

CMD ["uvicorn", "traceaid.main:app", "--host", "0.0.0.0", "--port", "8000"]
