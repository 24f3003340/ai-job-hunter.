#!/usr/bin/env python3
"""TEST-ONLY SMTP sink: accepts mail over STARTTLS + AUTH and writes each message to <dir>/*.eml (like Mailpit, no UI).
Used by scripts/staging_local.sh so the backend's real production SMTP path (TLS, verification, AUTH) is exercised.
    smtp_sink.py --port 2525 --cert cert.pem --key key.pem --user mailer --password sinkpw --dir ./mail
"""
import argparse
import asyncio
import secrets
import ssl
from pathlib import Path

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=2525)
ap.add_argument("--bind", default="127.0.0.1")
ap.add_argument("--cert")
ap.add_argument("--key")
ap.add_argument("--cert-dir", help="generate a self-signed cert into this directory (SAN = --host-name)")
ap.add_argument("--host-name", default="localhost")
ap.add_argument("--user", required=True)
ap.add_argument("--password", required=True)
ap.add_argument("--dir", required=True)
a = ap.parse_args()
out = Path(a.dir)
out.mkdir(parents=True, exist_ok=True)


class Sink:
    async def handle_DATA(self, server, session, envelope):
        (out / f"{secrets.token_hex(6)}.eml").write_bytes(envelope.content)
        return "250 OK"


def auth(server, session, envelope, mechanism, data):
    ok = isinstance(data, LoginPassword) and data.login == a.user.encode() and data.password == a.password.encode()
    return AuthResult(success=ok, handled=ok)


if a.cert_dir:
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    d = Path(a.cert_dir)
    d.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, a.host_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=7))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(a.host_name)]), critical=False).sign(key, hashes.SHA256()))
    (d / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (d / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    (d / "cert.pem").chmod(0o644)
    a.cert, a.key = str(d / "cert.pem"), str(d / "key.pem")
if not (a.cert and a.key):
    ap.error("provide --cert and --key, or --cert-dir")
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(a.cert, a.key)
Controller(Sink(), hostname=a.bind, port=a.port, tls_context=ctx, require_starttls=True,
           authenticator=auth, auth_required=True).start()
print(f"smtp sink on {a.bind}:{a.port} -> {out}", flush=True)
asyncio.new_event_loop().run_forever()
