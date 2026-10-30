"""A local page for the owner to label transcripts Pass / Fail, one per screen.

Labels go to `<name>.labels.jsonl` beside the transcripts, append-only with a UTC timestamp;
the latest label for an index wins, so changing your mind never rewrites history. The server
binds 127.0.0.1 and refuses any other Host header (no DNS-rebinding reads of real transcripts).
Everything from a transcript is HTML-escaped: answers and tool output are untrusted text.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs

HOST = "127.0.0.1"
PORT = 8770
Verdict = Literal["pass", "fail"]


def labels_path(transcripts: Path) -> Path:
    return Path(transcripts).with_suffix(".labels.jsonl")


def _rows(transcripts: Path) -> list[dict]:
    return [json.loads(line) for line in Path(transcripts).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def current_labels(transcripts: Path) -> dict[int, dict]:
    path = labels_path(transcripts)
    if not path.exists():
        return {}
    labels: dict[int, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            labels[int(row["index"])] = row
    return labels


def next_unlabelled(transcripts: Path) -> int | None:
    done = current_labels(transcripts)
    return next((i for i in range(len(_rows(transcripts))) if i not in done), None)


def save_label(transcripts: Path, index: int, verdict: Verdict, note: str) -> None:
    if verdict not in ("pass", "fail"):
        raise ValueError(f"verdict must be pass or fail, not {verdict!r}")
    row = _rows(transcripts)[index]
    record = {"index": index, "case_id": row.get("case_id"), "trial": row.get("trial", 0),
              "verdict": verdict, "note": note,
              "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    with labels_path(transcripts).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


_STYLE = """
body{font:16px/1.5 system-ui,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;
color:#1d1d1f;background:#fafafa}
.meta{color:#666;font-size:14px}.q{font-size:20px;font-weight:600;margin:12px 0}
.a{white-space:pre-wrap;background:#fff;border:1px solid #ddd;border-radius:8px;padding:14px}
pre{white-space:pre-wrap;font-size:13px;background:#f1f1f1;padding:8px;border-radius:6px}
button{font-size:16px;padding:10px 22px;margin-right:8px;border-radius:8px;border:1px solid #999}
.pass{background:#d9f2df}.fail{background:#f9dcdc}textarea{width:100%;height:70px}
.label{font-weight:600}
@media (prefers-color-scheme:dark){body{background:#151515;color:#eee}
.a{background:#1f1f1f;border-color:#333}pre{background:#262626}.meta{color:#aaa}}
"""

_KEYS = """
<script>
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'p') document.getElementById('pass').click();
  if (e.key === 'f') document.getElementById('fail').click();
  if (e.key === 'n') { e.preventDefault(); document.getElementById('note').focus(); }
});
</script>
"""


def render(transcripts: Path, index: int) -> str:
    rows = _rows(transcripts)
    row = rows[index]
    labels = current_labels(transcripts)
    done = len(labels)
    prior = labels.get(index)
    calls = "".join(
        f"<details><summary>{escape(str(c.get('name', '?')))}</summary>"
        f"<pre>args: {escape(json.dumps(c.get('args'), ensure_ascii=False, indent=1))}\n"
        f"response: {escape(json.dumps(c.get('response'), ensure_ascii=False, indent=1)[:4000])}"
        f"</pre></details>" for c in row.get("tool_calls", []))
    receipts = ", ".join(escape(str(r)) for r in row.get("receipts", [])) or "none"
    status = row.get("status", "ok")
    prior_html = (f"<p class='label'>Current label: {escape(prior['verdict'])}"
                  f"{' — ' + escape(prior['note']) if prior.get('note') else ''}</p>"
                  if prior else "")
    nav = (f"<a href='/i/{index - 1}'>&larr; prev</a> " if index > 0 else "") + (
        f"<a href='/i/{index + 1}'>next &rarr;</a>" if index + 1 < len(rows) else "")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Transcript review</title><style>{_STYLE}</style></head><body>
<p class="meta">{index + 1} of {len(rows)} &middot; {done} labelled &middot;
case {escape(str(row.get('case_id', '')))} &middot; trial {escape(str(row.get('trial', 0)))}
&middot; status {escape(str(status))} &middot; {nav}</p>
<div class="q">{escape(str(row.get('question', '')))}</div>
<div class="a">{escape(str(row.get('answer', '')))}</div>
<p class="meta">receipts: {receipts}</p>
<h3>Tool calls ({len(row.get('tool_calls', []))})</h3>{calls or '<p class="meta">none</p>'}
{prior_html}
<form method="post" action="/label">
<input type="hidden" name="index" value="{index}">
<textarea id="note" name="note" placeholder="What went wrong? (n to focus)"></textarea><p>
<button id="pass" class="pass" name="verdict" value="pass">Pass (p)</button>
<button id="fail" class="fail" name="verdict" value="fail">Fail (f)</button></p>
</form>{_KEYS}</body></html>"""


def _done_page(transcripts: Path) -> str:
    n = len(_rows(transcripts))
    return (f"<!doctype html><meta charset='utf-8'><title>Transcript review</title>"
            f"<p>All {n} transcripts labelled. <a href='/i/0'>Review again</a></p>")


def make_server(transcripts: Path, port: int = PORT) -> ThreadingHTTPServer:
    transcripts = Path(transcripts)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # keep transcript text out of the console
            pass

        def _local(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host in (HOST, "localhost"):
                return True
            self.send_error(403)
            return False

        def _send(self, body: str, code: int = 200) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "script-src 'unsafe-inline'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self, to: str) -> None:
            self.send_response(303)
            self.send_header("Location", to)
            self.end_headers()

        def do_GET(self) -> None:
            if not self._local():
                return
            if self.path == "/":
                nxt = next_unlabelled(transcripts)
                self._redirect(f"/i/{nxt}" if nxt is not None else "/done")
            elif self.path == "/done":
                self._send(_done_page(transcripts))
            elif self.path.startswith("/i/") and self.path[3:].isdigit():
                index = int(self.path[3:])
                if index >= len(_rows(transcripts)):
                    self.send_error(404)
                    return
                self._send(render(transcripts, index))
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if not self._local():
                return
            if self.path != "/label":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            form = parse_qs(self.rfile.read(min(length, 100_000)).decode("utf-8"))
            try:
                index = int(form["index"][0])
                verdict = form["verdict"][0]
                save_label(transcripts, index, verdict, form.get("note", [""])[0])  # type: ignore[arg-type]
            except (KeyError, ValueError, IndexError):
                self.send_error(400)
                return
            nxt = next_unlabelled(transcripts)
            self._redirect(f"/i/{nxt}" if nxt is not None else "/done")

    return ThreadingHTTPServer((HOST, port), Handler)


def serve(transcripts: Path, port: int = PORT) -> None:
    server = make_server(transcripts, port)
    print(f"Review page: http://{HOST}:{server.server_address[1]}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
