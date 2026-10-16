#!/bin/sh
# Request a fresh RA-TLS identity at container startup from the dstack guest.
# Nothing here deploys a VM or generates application/configuration source files.
# Running without a real guest agent fails; no local identity fallback exists.
set -eu
umask 077
mkdir -p /run/sec304-tls
chmod 700 /run/sec304-tls
# Inspect tls_identity.py: /GetTlsKey embeds evidence in the returned certificate.
# Restart to renew the one-day certificate; never bake keys into the image.
python3 tls_identity.py
# Standard TLS remains Gunicorn/OpenSSL's responsibility.
exec gunicorn --config gunicorn_attested.py server:app
