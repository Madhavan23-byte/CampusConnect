FROM python:3.12-slim

# Install system dependencies for python-magic (libmagic) and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create uploads directory (mounted as volume in production)
RUN mkdir -p /app/uploads

# Run as non-root user for security
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app /app/uploads
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
