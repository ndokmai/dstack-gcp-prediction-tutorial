# Module 2's runtime and dependencies; replace only the identity/startup layer.
FROM python@sha256:dbbe4ceb97851e2e5fa83798b239811f871cb743b259ba3563737349f6bcfaa0
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir --require-hashes -r requirements.txt
COPY server.py model.py tls_identity.py gunicorn_attested.py start.sh /app/
# The base image must provide OpenSSL; fail the build visibly if it does not.
RUN openssl version
EXPOSE 8000
# Keys are generated at runtime; neither server.crt nor server.key is copied.
CMD ["sh", "/app/start.sh"]
