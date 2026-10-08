FROM python:3.12-slim

# System dependencies:
#   wget      — the mirror engine shells out to it
#   curl      — healthchecks and the curl-cffi fallback
#   ca-certificates — TLS for every outbound request
# Playwright's own system libraries come from its installer below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the metadata first so the dependency layer is cached independently of src/.
COPY pyproject.toml README.md ./
COPY src/ src/

# Install the package (this pulls cryptography, playwright, litellm, …).
RUN pip install --no-cache-dir .

# Install the browser and its system libraries. This is the slow layer; keep it
# after the pip install so a source change does not re-download Chromium.
RUN playwright install --with-deps chromium

# Playwright installs browsers to /root/.cache when run as root; relocate for runtime user.
ENV PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright
RUN mkdir -p /app/ms-playwright && \
    if [ -d /root/.cache/ms-playwright ]; then mv /root/.cache/ms-playwright/* /app/ms-playwright/ 2>/dev/null || true; fi && \
    chown -R 10001:10001 /app/ms-playwright 2>/dev/null || true
# Every store writes under this root (see ZFROG_DATA_DIR in config.py), so a single
# volume mount keeps keys, users, sessions, versions and indexes across restarts.
ENV ZFROG_DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1
RUN mkdir -p /app/data

# Run as a non-root user: the container downloads and stores untrusted content.
RUN useradd --create-home --uid 10001 zfrog \
    && chown -R zfrog:zfrog /app
USER zfrog

EXPOSE 8000

# The compose file overrides this with the API or the Celery command.
CMD ["uvicorn", "zfrog.api:app", "--host", "0.0.0.0", "--port", "8000"]
