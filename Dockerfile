FROM python:3.12-slim

RUN useradd -m appuser

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create log directory and ensure appuser can write to it
RUN mkdir -p /app/data/logs && \
    chown -R appuser:appuser /app/data

ENV PYTHONUNBUFFERED=1

USER appuser

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "app.main"]
