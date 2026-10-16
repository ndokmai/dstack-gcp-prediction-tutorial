# Updated from module 1: same application/dependencies, with TLS startup below.
FROM python@sha256:dbbe4ceb97851e2e5fa83798b239811f871cb743b259ba3563737349f6bcfaa0
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir --require-hashes -r requirements.txt
COPY server.py model.py /app/
# New: public certificate and TLS configuration, never a private key.
COPY server.crt gunicorn_tls.py /app/
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["gunicorn", "--config", "gunicorn_tls.py", "server:app"]
