FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BLOG_DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Versioned SQL migrations are applied explicitly (scripts/db.py) or on the
# first start of an empty database; they are not optional build assets.
COPY migrations ./migrations
COPY scripts ./scripts
RUN mkdir -p /app/data

EXPOSE 8000

# `--proxy-headers --forwarded-allow-ips` trusts X-Forwarded-* only from the
# single ingress (operator nginx). A client-supplied X-Forwarded-For from any
# other peer is ignored, so rate-limit buckets cannot be forged.
# `--no-server-header` keeps the server fingerprint out of responses.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=${BLOG_TRUSTED_PROXY:-127.0.0.1} --no-server-header"]
