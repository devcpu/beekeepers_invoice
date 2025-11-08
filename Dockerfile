# Dockerfile für Rechnungsverwaltung
FROM python:3.11-slim

# Arbeitsverzeichnis
WORKDIR /app

# System-Dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python-Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Gunicorn für Production
RUN pip install --no-cache-dir gunicorn gevent

# App-Dateien kopieren
COPY . .

# Nicht-root User erstellen
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Port exposieren
EXPOSE 8000

# Health Check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=2)" || exit 1

# Startup-Script
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--worker-class", "gevent", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]
