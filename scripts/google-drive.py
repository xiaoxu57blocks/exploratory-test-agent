#!/usr/bin/env python3
"""
google-drive — minimal OAuth-authenticated Google Drive client used by the
fixture pipeline. Three subcommands: auth, find, download.

Why a hand-rolled script and not `google-api-python-client`?
- Adds zero pip deps. The full Google client library + its OAuth helper
  pulls 30+ transitive packages; we only need three HTTPS calls (token,
  files.list, files.get?alt=media). 200 lines of stdlib does it.
- Token cache layout matches the rest of this repo's "ad-hoc OAuth caches
  on disk" pattern (Linear MCP, GitHub MCP both do something similar).

Files this script touches:
  .claude/google-oauth-client.json   (input — created by the human in GCP Console; gitignored)
  .claude/google-oauth-token.json    (output — created on first auth(); gitignored)

Usage:
  scripts/google-drive.py auth
      First-run interactive flow. Opens the browser; on success writes
      .claude/google-oauth-token.json and exits 0. Re-running is idempotent
      — if the cached token still refreshes, it just confirms 'ok'.

  scripts/google-drive.py find --folder-id <id> [--name-contains <substr>]
      List files inside a Drive folder (Shared drive folders included).
      Prints one JSON line per file: {id, name, mimeType, modifiedTime, size}.
      With --name-contains, filters server-side via Drive's q= parameter.

  scripts/google-drive.py download --file-id <id> --out <path>
      Stream the file's bytes to <path>. Auto-refreshes the token if
      expired. Prints one JSON line: {ok, path, size, file_id}.

Exit codes: 0 ok, 2 bad args / setup, 3 API/network failure, 4 auth needed
(no cached token; user should run `auth` once).
"""

from __future__ import annotations

import argparse
import http.server
import json
import secrets
import socketserver
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_PATH = REPO_ROOT / ".claude" / "google-oauth-client.json"
TOKEN_PATH = REPO_ROOT / ".claude" / "google-oauth-token.json"

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
LOCALHOST_PORT = 8765  # arbitrary; the redirect_uris in the GCP client config must include http://localhost (Google accepts any port for desktop apps).


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def emit(d: dict, code: int = 0) -> None:
    print(json.dumps(d))
    sys.exit(code)


def die(code: int, msg: str) -> None:
    print(f"google-drive: {msg}", file=sys.stderr)
    sys.exit(code)


def load_client() -> dict:
    if not CLIENT_PATH.exists():
        die(2, f"OAuth client config missing at {CLIENT_PATH}. See README's Google Drive setup section.")
    data = json.loads(CLIENT_PATH.read_text())
    inner = data.get("installed") or data.get("web")
    if not inner:
        die(2, f"{CLIENT_PATH}: expected 'installed' or 'web' top-level key (Desktop app client?)")
    if not inner.get("client_id") or not inner.get("client_secret"):
        die(2, f"{CLIENT_PATH}: missing client_id or client_secret")
    return inner


def load_token() -> dict | None:
    if not TOKEN_PATH.exists():
        return None
    return json.loads(TOKEN_PATH.read_text())


def save_token(tok: dict) -> None:
    TOKEN_PATH.write_text(json.dumps(tok, indent=2))
    TOKEN_PATH.chmod(0o600)


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Single-shot HTTP handler that captures the OAuth redirect query."""
    captured: dict = {}

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.captured = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if "code" in _CallbackHandler.captured:
            body = "<h1>Authorization received.</h1><p>You can close this tab.</p>"
        else:
            body = f"<h1>Authorization failed.</h1><pre>{json.dumps(_CallbackHandler.captured, indent=2)}</pre>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, fmt: str, *args: Any) -> None:  # silence access logs
        return


def _exchange_code_for_token(client: dict, code: str, redirect_uri: str) -> dict:
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    req = urllib.request.Request(
        client.get("token_uri", "https://oauth2.googleapis.com/token"),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        die(3, f"token exchange failed: HTTP {e.code} - {e.read().decode('utf-8','replace')[:300]}")
    data["obtained_at"] = int(time.time())
    return data


def _refresh_access_token(client: dict, token: dict) -> dict:
    if not token.get("refresh_token"):
        die(4, "cached token has no refresh_token; re-run `auth`")
    body = urllib.parse.urlencode({
        "refresh_token": token["refresh_token"],
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "grant_type": "refresh_token",
    }).encode("utf-8")
    req = urllib.request.Request(
        client.get("token_uri", "https://oauth2.googleapis.com/token"),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            new = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        die(3, f"token refresh failed: HTTP {e.code} - {e.read().decode('utf-8','replace')[:300]}")
    # refresh response usually omits refresh_token; preserve the existing one
    new.setdefault("refresh_token", token["refresh_token"])
    new["obtained_at"] = int(time.time())
    return new


def _ensure_fresh_access_token() -> tuple[dict, str]:
    client = load_client()
    token = load_token()
    if not token:
        die(4, "no cached token; run `scripts/google-drive.py auth` first")
    expires_at = token.get("obtained_at", 0) + token.get("expires_in", 3600) - 60  # 60s safety margin
    if time.time() >= expires_at:
        token = _refresh_access_token(client, token)
        save_token(token)
    return token, token["access_token"]


def cmd_auth() -> None:
    client = load_client()

    # If there's already a cached token, try to refresh — many invocations
    # call `auth` defensively at script start. Don't force the human
    # through the browser if we don't have to.
    existing = load_token()
    if existing and existing.get("refresh_token"):
        try:
            new = _refresh_access_token(client, existing)
            save_token(new)
            emit({"ok": True, "msg": "existing token refreshed", "scope": new.get("scope")}, 0)
        except SystemExit:
            # die(3) above bubbles SystemExit; fall through to interactive
            pass

    # Interactive desktop flow — start a localhost listener, open the
    # consent URL, wait for the redirect carrying ?code=...
    redirect_uri = f"http://localhost:{LOCALHOST_PORT}"
    state = secrets.token_urlsafe(16)
    auth_url = (
        client.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")
        + "?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": client["client_id"],
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "access_type": "offline",   # required for refresh_token
            "prompt": "consent",        # force re-consent so refresh_token comes back even on re-auth
            "state": state,
        })
    )

    print(f"Opening browser for Google Drive authorization (port {LOCALHOST_PORT}).", file=sys.stderr)
    print(f"If the browser doesn't open, visit:\n  {auth_url}\n", file=sys.stderr)
    webbrowser.open(auth_url)

    # Single-shot httpd; handle one request, then move on.
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", LOCALHOST_PORT), _CallbackHandler) as httpd:
        httpd.timeout = 300  # 5 minutes for the user to consent
        httpd.handle_request()

    captured = _CallbackHandler.captured
    if captured.get("state") != state:
        die(3, f"OAuth state mismatch (got {captured.get('state')!r}, expected {state!r}) - possible replay")
    if captured.get("error"):
        die(3, f"OAuth error: {captured['error']} - {captured.get('error_description', '')}")
    if "code" not in captured:
        die(3, f"no `code` in callback; got keys {list(captured.keys())}")

    token = _exchange_code_for_token(client, captured["code"], redirect_uri)
    save_token(token)
    emit({"ok": True, "msg": "token cached", "scope": token.get("scope"), "expires_in": token.get("expires_in")}, 0)


# ---------------------------------------------------------------------------
# Drive API helpers
# ---------------------------------------------------------------------------

DRIVE_API = "https://www.googleapis.com/drive/v3"


def _drive_get(path: str, access_token: str, params: dict | None = None, stream_to: Path | None = None) -> Any:
    url = f"{DRIVE_API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            if stream_to:
                stream_to.parent.mkdir(parents=True, exist_ok=True)
                with stream_to.open("wb") as f:
                    while True:
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                return None
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        die(3, f"Drive API {path} -> HTTP {e.code}: {body[:400]}")


def cmd_find(args: argparse.Namespace) -> None:
    if not args.folder_id:
        die(2, "find: --folder-id is required")
    _, access = _ensure_fresh_access_token()

    # Build q=. Note Drive ignores trashed by default so we ask for it explicitly off.
    q_parts = [f"'{args.folder_id}' in parents", "trashed = false"]
    if args.name_contains:
        # Escape single quotes for Drive's query syntax
        safe = args.name_contains.replace("'", "\\'")
        q_parts.append(f"name contains '{safe}'")
    q = " and ".join(q_parts)

    page_token = None
    rows: list[dict] = []
    while True:
        params = {
            "q": q,
            "fields": "nextPageToken, files(id, name, mimeType, modifiedTime, size, parents)",
            "pageSize": "200",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
            "corpora": "allDrives",
        }
        if page_token:
            params["pageToken"] = page_token
        page = _drive_get("/files", access, params)
        rows.extend(page.get("files", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            break

    for row in rows:
        print(json.dumps(row))
    sys.exit(0)


def cmd_download(args: argparse.Namespace) -> None:
    if not args.file_id or not args.out:
        die(2, "download: --file-id and --out are required")
    _, access = _ensure_fresh_access_token()
    out = Path(args.out)
    _drive_get(
        f"/files/{args.file_id}",
        access,
        params={"alt": "media", "supportsAllDrives": "true"},
        stream_to=out,
    )
    size = out.stat().st_size
    emit({"ok": True, "path": str(out), "size": size, "file_id": args.file_id}, 0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth", help="run the interactive OAuth flow (first-time setup, or re-auth on revoke)")

    p_find = sub.add_parser("find", help="list files in a Drive folder")
    p_find.add_argument("--folder-id", required=True, help="Drive folder id (the slug after /folders/ in the URL)")
    p_find.add_argument("--name-contains", help="substring filter applied server-side via Drive's q= 'name contains'")

    p_dl = sub.add_parser("download", help="download a file by id")
    p_dl.add_argument("--file-id", required=True)
    p_dl.add_argument("--out", required=True, help="output path; parent dir is created if missing")

    args = p.parse_args()

    if args.cmd == "auth":
        cmd_auth()
    elif args.cmd == "find":
        cmd_find(args)
    elif args.cmd == "download":
        cmd_download(args)


if __name__ == "__main__":
    main()
