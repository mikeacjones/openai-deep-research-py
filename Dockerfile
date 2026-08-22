FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN pip install --no-cache-dir uv \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=app:app activities ./activities
COPY --chown=app:app agents ./agents
COPY --chown=app:app workflows ./workflows
COPY --chown=app:app config.py worker.py start_workflow.py README.md ./

USER app

CMD ["python", "worker.py"]
