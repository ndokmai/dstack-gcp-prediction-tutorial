# Build from this server directory; client and owner files are outside its context.
# This pinned base contains the interpreter; no Python compilation is required.
FROM python@sha256:dbbe4ceb97851e2e5fa83798b239811f871cb743b259ba3563737349f6bcfaa0

WORKDIR /app
# Exported from uv.lock with hashes pinning the installed distributions.
COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir --require-hashes -r requirements.txt
COPY server.py model.py /app/
# The image contains no weights. The owner provisions them after startup.

ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
# One worker keeps provisioned weights in a single process. Threads share the
# state using the Flask app's lock; multiple workers would have separate models.
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8000", "server:app"]
