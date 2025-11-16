FROM python:3.13-slim
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen --no-cache

# Copy application code
COPY . .

# Create non-root user and change ownership
RUN adduser --disabled-password --gecos "" myuser && \
    chown -R myuser:myuser /app

USER myuser

ENV PATH="/app/.venv/bin:$PATH"

CMD ["sh", "-c", "uv run uvicorn main:app --host 0.0.0.0 --port $PORT"]