#!/usr/bin/env python3
"""
attach-screenshot-to-comment — compress a screenshot, upload to Linear, embed
in an existing comment, then delete the attachment record so the issue's
Resources panel stays clean.

Why this is a script and not agent work:
- The base64 encoded jpeg is ~225KB. Holding that string in an agent's
  context — even a sub-agent's — costs ~50K tokens per image and the agent
  doesn't make any decisions while moving those bytes around.

Usage (one screenshot per call):

  scripts/attach-screenshot-to-comment.py \\
    --issue SUP-7623 \\
    --comment-id 35b3fffd-... \\
    --source artifacts/<run-id>/04-run-unit-1/screenshots/04-after-close-and-reload.png \\
    --scenario s4 \\
    --verdict PASS \\
    --title "Close persists across refresh" \\
    --caption "Click close → panel hides; localStorage key written; after F5 reload panel stays hidden."

Behavior:
  1. Reads source PNG (or JPEG/WebP) from --source.
  2. If it's a PNG, compresses to JPEG q=30 in <source-dir>/compressed/. If
     it's already a jpeg, skips compression. Pass --keep-png to use the file
     verbatim — for pixel-sensitive layout regressions where JPEG would
     introduce edge artifacts.
  3. Uploads via Linear MCP `create_attachment`. Filename is built as
     <ticket-lower>-<scenario>-<VERDICT>-<slug>.<ext> so a downloaded file
     keeps the verdict legible out of context.
  4. Fetches the existing comment body via `list_comments`, appends to (or
     creates) the `### Evidence` section just above the footer, and updates
     via `save_comment`. Caption format is `**[VERDICT] Scenario N — title**`
     so PASS and FAIL evidence interleave readably in one section.
  5. Deletes the attachment record. The asset URL survives — verified — so
     the inline image keeps rendering.
  6. Prints one JSON line summarizing the result.

Exit codes:
  0  success
  2  bad arguments
  3  Linear API failure (auth, network, 4xx/5xx)
  4  comment edit failed mid-flight (attachment uploaded but comment update
     failed — caller may want to retry the edit only)
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

LINEAR_MCP_URL = "https://mcp.linear.app/mcp"
TOKEN_CACHE_DIR = Path.home() / ".mcp-auth" / "mcp-remote-0.1.37"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def load_bearer_token() -> str:
    """Find the cached Linear MCP OAuth bearer token.

    The mcp-remote client writes tokens to ~/.mcp-auth/mcp-remote-<ver>/<hash>_tokens.json.
    There's typically one cache file per remote; we pick the most recently
    modified one to be robust across MCP client upgrades that change the
    directory's version suffix.
    """
    candidates = sorted(
        TOKEN_CACHE_DIR.glob("*_tokens.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        # Try one level up in case mcp-remote-<other-version>/
        for parent in (TOKEN_CACHE_DIR.parent.glob("mcp-remote-*")):
            cand = sorted(parent.glob("*_tokens.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if cand:
                candidates = cand
                break
    if not candidates:
        die(3, f"no Linear MCP token cache found under {TOKEN_CACHE_DIR.parent}")

    with candidates[0].open() as f:
        data = json.load(f)
    token = data.get("access_token")
    if not token:
        die(3, f"token cache at {candidates[0]} has no access_token")
    return token


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

_RPC_ID = 0


def call_tool(token: str, name: str, arguments: dict) -> dict:
    """Call an MCP tool over JSON-RPC. Returns the parsed `result` field."""
    global _RPC_ID
    _RPC_ID += 1
    payload = {
        "jsonrpc": "2.0",
        "id": _RPC_ID,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    req = urllib.request.Request(
        LINEAR_MCP_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        die(3, f"HTTP {e.code} on tools/call({name}): {body[:500]}")
    except urllib.error.URLError as e:
        die(3, f"network error on tools/call({name}): {e}")

    parsed = _parse_mcp_response(raw)
    if "error" in parsed:
        die(3, f"tools/call({name}) returned error: {parsed['error']}")
    return parsed.get("result", {})


def _parse_mcp_response(raw: str) -> dict:
    """The Linear MCP server may respond as plain JSON or as an SSE stream
    (when Accept includes text/event-stream). Handle both.
    """
    raw = raw.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    # SSE: lines like `event: message` then `data: {...}`. Find the first
    # `data:` line that parses as JSON-RPC.
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue
    die(3, f"could not parse MCP response: {raw[:300]}")


def extract_text_content(rpc_result: dict) -> str:
    """MCP tool results come wrapped as `{"content": [{"type":"text","text":"..."}]}`.
    Pull out the text payload (which is itself JSON for these tools).
    """
    content = rpc_result.get("content") or []
    for c in content:
        if c.get("type") == "text":
            return c.get("text", "")
    return ""


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------

def compress_to_jpeg(src: Path, quality: int = 30) -> Path:
    """Compress src (PNG) to JPEG with the given quality. Output goes into
    <src.parent>/compressed/<src.stem>.jpg. Returns the output path.
    """
    out_dir = src.parent / "compressed"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{src.stem}.jpg"
    if shutil.which("sips") is None:
        die(3, "sips not found (this script currently targets macOS). On Linux, install ImageMagick and adapt.")
    subprocess.run(
        ["sips", "-s", "format", "jpeg", "-s", "formatOptions", str(quality), str(src), "--out", str(out)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return out


# ---------------------------------------------------------------------------
# Filename / slug
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:60]


def build_filename(ticket: str, scenario: str, verdict: str, source: Path) -> str:
    slug = slugify(source.stem)
    ext = source.suffix.lstrip(".")
    return f"{ticket.lower()}-{scenario}-{verdict.upper()}-{slug}.{ext}"


# ---------------------------------------------------------------------------
# Comment body editing
# ---------------------------------------------------------------------------

# The Evidence section holds one captioned image per scenario, regardless of
# whether the scenario passed or failed. Each caption begins with `**[PASS]`
# or `**[FAIL]` so a reader scanning the section can sort by verdict at a
# glance. Older runs may have used `### Screenshot` / `### Screenshots` as the
# heading; the parser accepts those for back-compat but new content is always
# written under `### Evidence`.
EVIDENCE_HEADING_RE = re.compile(r"\n### (?:Evidence|Screenshots?)\n", re.MULTILINE)
# Footer block to keep at the very bottom of the comment. The reporter template
# emits `---\n*Generated by exploratory-test-agent...*` as the closing line, so
# we recognise the horizontal rule + italicised attribution as the footer
# boundary and insert new content above it.
FOOTER_BOUNDARY_RE = re.compile(r"\n---\s*\n\s*\*Generated by exploratory-test-agent[^\n]*\*\s*$", re.MULTILINE)


def upsert_screenshot_section(body: str, caption_block: str) -> str:
    """Insert `caption_block` (which starts with `**[VERDICT] Scenario N — ...**`)
    into the Evidence section of `body`, keeping the section *above* the
    `---` / `*Generated by ...*` footer.

    - If no Evidence section exists yet: create it just above the footer
      (or at the end of the body when no footer is present).
    - If the section already exists (under `### Evidence` or the legacy
      `### Screenshot[s]` heading), append the new caption block to the
      end of that section.
    """
    body = body.rstrip()

    # Split body into (above_footer, footer) so we always insert above it.
    footer_match = FOOTER_BOUNDARY_RE.search(body)
    if footer_match:
        above = body[: footer_match.start()].rstrip()
        footer = body[footer_match.start():].lstrip("\n")
    else:
        above = body
        footer = ""

    m = EVIDENCE_HEADING_RE.search(above)
    if not m:
        # No section yet — create it just above the footer.
        new_above = above + f"\n\n### Evidence\n\n{caption_block.strip()}"
    else:
        # Section exists in `above`. Append caption_block at end of above.
        new_above = above + "\n\n" + caption_block.strip()

    if footer:
        return new_above + "\n\n" + footer + "\n"
    return new_above + "\n"


def build_caption_block(verdict: str, scenario: str, title: str, caption: str, image_url: str, alt: str) -> str:
    return (
        f"**[{verdict.upper()}] Scenario {scenario.lstrip('s').lstrip('S')} — {title}**\n"
        f"{caption}\n\n"
        f"![{alt}]({image_url})"
    )


# ---------------------------------------------------------------------------
# Linear ops
# ---------------------------------------------------------------------------

def upload_attachment(token: str, *, issue: str, filename: str, jpeg_path: Path, title: str, subtitle: str) -> tuple[str, str]:
    """Upload a JPEG as a Linear attachment. Returns (attachment_id, asset_url)."""
    b64 = base64.b64encode(jpeg_path.read_bytes()).decode("ascii")
    args = {
        "issue": issue,
        "filename": filename,
        "contentType": "image/jpeg",
        "base64Content": b64,
        "title": title,
        "subtitle": subtitle,
    }
    result = call_tool(token, "create_attachment", args)
    text = extract_text_content(result)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        die(3, f"create_attachment returned non-JSON text: {text[:300]}")
    # Linear's MCP returns a structure like {"attachment": {...}} or the
    # attachment fields directly. Be permissive.
    a = data.get("attachment") or data
    att_id = a.get("id")
    url = a.get("url") or (a.get("subtitle") if False else None)
    if not att_id or not url:
        die(3, f"could not find id/url in create_attachment result: {data}")
    return att_id, url


def fetch_comment_body(token: str, *, issue: str, comment_id: str) -> str:
    """Fetch the body of comment `comment_id` on `issue`. Uses list_comments
    (no get_comment in Linear MCP) and filters by id.
    """
    result = call_tool(token, "list_comments", {"issueId": issue})
    text = extract_text_content(result)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        die(3, f"list_comments returned non-JSON: {text[:300]}")
    comments = data.get("comments") or data.get("items") or data
    if isinstance(comments, dict) and "nodes" in comments:
        comments = comments["nodes"]
    for c in comments:
        if c.get("id") == comment_id:
            return c.get("body", "")
    die(3, f"comment {comment_id} not found on issue {issue}")


def update_comment(token: str, *, comment_id: str, body: str) -> None:
    call_tool(token, "save_comment", {"id": comment_id, "body": body})


def delete_attachment(token: str, *, attachment_id: str) -> None:
    call_tool(token, "delete_attachment", {"id": attachment_id})


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def die(code: int, msg: str) -> None:
    print(f"attach-screenshot: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--issue", required=True, help="Linear issue id (e.g. SUP-7623)")
    p.add_argument("--comment-id", required=True, help="existing comment id to edit")
    p.add_argument("--source", required=True, type=Path, help="source screenshot path (PNG or JPEG)")
    p.add_argument("--scenario", required=True, help="scenario id, e.g. s4")
    p.add_argument("--verdict", default="PASS", help="verdict tag for the caption: PASS or FAIL (default PASS)")
    p.add_argument("--title", required=True, help="short scenario title for caption + attachment title")
    p.add_argument("--caption", required=True, help="one-or-two-sentence caption describing what the picture proves")
    p.add_argument("--quality", type=int, default=30, help="JPEG quality 1-100 (default 30)")
    p.add_argument("--keep-png", action="store_true", help="upload source as-is without compressing (for layout regressions)")
    p.add_argument("--no-delete", action="store_true", help="leave the attachment record on the issue (default: delete it)")
    args = p.parse_args()

    if not args.source.exists():
        die(2, f"source not found: {args.source}")
    verdict = args.verdict.upper()
    if verdict not in ("PASS", "FAIL"):
        die(2, f"--verdict must be PASS or FAIL (got '{args.verdict}')")

    token = load_bearer_token()

    # 1. Compress (or skip)
    if args.keep_png or args.source.suffix.lower() in (".jpg", ".jpeg"):
        upload_path = args.source
    else:
        upload_path = compress_to_jpeg(args.source, quality=args.quality)

    # 2. Upload
    filename = build_filename(args.issue, args.scenario, verdict, upload_path)
    title_text = f"[{verdict}] Scenario {args.scenario.lstrip('s').lstrip('S')} — {args.title}"
    att_id, asset_url = upload_attachment(
        token,
        issue=args.issue,
        filename=filename,
        jpeg_path=upload_path,
        title=title_text,
        subtitle=args.caption,
    )

    # 3. Fetch + edit comment
    body = fetch_comment_body(token, issue=args.issue, comment_id=args.comment_id)
    caption_block = build_caption_block(
        verdict=verdict,
        scenario=args.scenario,
        title=args.title,
        caption=args.caption,
        image_url=asset_url,
        alt=f"{args.issue.lower()}-{args.scenario}-{verdict}",
    )
    new_body = upsert_screenshot_section(body, caption_block)

    try:
        update_comment(token, comment_id=args.comment_id, body=new_body)
    except SystemExit:
        # update_comment raised die(3). Don't delete the attachment — caller
        # may want to retry the edit, in which case the attachment is needed.
        print(json.dumps({
            "ok": False,
            "stage": "update_comment",
            "attachment_id": att_id,
            "asset_url": asset_url,
            "comment_id": args.comment_id,
            "note": "attachment uploaded but comment edit failed; not deleting so you can retry --no-upload step",
        }))
        sys.exit(4)

    # 4. Delete attachment record (asset URL survives)
    deleted = False
    if not args.no_delete:
        delete_attachment(token, attachment_id=att_id)
        deleted = True

    print(json.dumps({
        "ok": True,
        "attachment_id": att_id,
        "asset_url": asset_url,
        "comment_id": args.comment_id,
        "filename": filename,
        "compressed": not (args.keep_png or args.source.suffix.lower() in (".jpg", ".jpeg")),
        "attachment_deleted": deleted,
    }))


if __name__ == "__main__":
    main()
