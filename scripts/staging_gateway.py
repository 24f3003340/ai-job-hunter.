#!/usr/bin/env python3
"""TEST-ONLY stand-in for the Caddy front door (deploy/Caddyfile) so a staging-like stack can run without Docker/Caddy.
It does NOT replace Caddy: it reproduces the behaviours the app depends on, and takes the CSP from the real Caddyfile
so the two cannot drift:
  * TLS termination (run under uvicorn with --ssl-keyfile/--ssl-certfile)
  * static SPA with index fallback, long-cache assets
  * /api/* reverse proxy, 6 MB body limit, X-Forwarded-For OVERWRITTEN with the real client address
  * security headers incl. CSP; /health/ready hidden from the outside
    UPSTREAM=http://127.0.0.1:8021 DIST=frontend/dist uvicorn --app-dir scripts staging_gateway:app --port 8443 --ssl-keyfile k --ssl-certfile c
"""
import os
import re
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.routing import Route

UPSTREAM = os.environ.get("UPSTREAM", "http://127.0.0.1:8021")
DIST = Path(os.environ.get("DIST", "frontend/dist")).resolve()
CADDYFILE = Path(__file__).resolve().parent.parent / "deploy" / "Caddyfile"
CSP = re.search(r'Content-Security-Policy "([^"]+)"', CADDYFILE.read_text()).group(1)
MAX_BODY = 6 * 1024 * 1024
HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-authorization", "te", "trailers", "host",
       "content-length", "x-forwarded-for", "x-real-ip"}
SEC = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains", "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()", "Content-Security-Policy": CSP,
}
client = httpx.AsyncClient(base_url=UPSTREAM, timeout=60, follow_redirects=False)


def secure(r: Response) -> Response:
    for k, v in SEC.items():
        r.headers[k] = v
    return r


async def api(request: Request):
    body = await request.body()
    if len(body) > MAX_BODY:
        return secure(PlainTextResponse("Request entity too large", status_code=413))
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    headers["X-Forwarded-For"] = request.client.host if request.client else "unknown"  # overwrite, never append
    up = await client.request(request.method, request.url.path + (f"?{request.url.query}" if request.url.query else ""),
                              headers=headers, content=body)
    drop = {"content-length", "transfer-encoding", "connection", "server", "content-encoding"}
    resp = Response(up.content, status_code=up.status_code, headers={k: v for k, v in up.headers.items() if k.lower() not in drop})
    return secure(resp)


async def health(request: Request):
    if request.url.path == "/health/ready":
        return secure(PlainTextResponse("", status_code=404))
    up = await client.get("/health")
    return secure(Response(up.content, status_code=up.status_code, media_type="application/json"))


async def static(request: Request):
    rel = request.url.path.lstrip("/")
    f = (DIST / rel).resolve()
    if not (rel and f.is_file() and DIST in f.parents):
        f = DIST / "index.html"
    r = FileResponse(f)
    r.headers["Cache-Control"] = "public, max-age=31536000, immutable" if rel.startswith("assets/") else "no-store"
    return secure(r)


app = Starlette(routes=[
    Route("/api/{path:path}", api, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
    Route("/health", health), Route("/health/ready", health),
    Route("/{path:path}", static, methods=["GET", "HEAD"]),
])
