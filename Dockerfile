FROM python:3.13-slim

WORKDIR /app

# Build deps for numpy/scipy/arch wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure alert and data dirs exist at image build time
RUN mkdir -p execution_engine/data/alerts

# Engine writes healthcheck.ts on every tick; Docker reads it here
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=90s \
    CMD python execution_engine/healthcheck.py

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "execution_engine.main"]
