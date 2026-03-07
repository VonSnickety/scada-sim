FROM python:3.14-slim

WORKDIR /app

# Install dependencies first — Docker caches this layer separately.
# If you only change app code, Docker skips this step on rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Run as a non-root user — if the container is ever compromised,
# the attacker has limited privileges inside it.
RUN useradd -m appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
