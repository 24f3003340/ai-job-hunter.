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
ap.add_argument("--cert", required=True)
ap.add_argument("--key", required=True)
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


ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(a.cert, a.key)
Controller(Sink(), hostname="127.0.0.1", port=a.port, tls_context=ctx, require_starttls=True,
           authenticator=auth, auth_required=True).start()
print(f"smtp sink on 127.0.0.1:{a.port} -> {out}", flush=True)
asyncio.new_event_loop().run_forever()
