from __future__ import annotations

import html
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from .store import JsonStore

STORE = JsonStore()


def dashboard_html(projects: list[dict]) -> str:
    rows = []
    for project in projects:
        rows.append(
            "<tr>"
            f"<td>{html.escape(project['name'])}</td>"
            f"<td>{html.escape(project['status'])}</td>"
            f"<td>{int(project['progress'])}%</td>"
            f"<td>{html.escape(project.get('source_filename') or '—')}</td>"
            f"<td>{html.escape(project.get('youtube_upload_status') or 'Not uploaded')}</td>"
            "</tr>"
        )
    body_rows = "".join(rows) or '<tr><td colspan="5" class="empty">No projects yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Factory</title>
<style>
body{{font-family:Arial,sans-serif;background:#0b0d12;color:#f5f7fb;margin:0}}
main{{max-width:1100px;margin:0 auto;padding:32px}}
nav{{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px}}
.brand{{font-size:24px;font-weight:700}} .muted{{color:#9aa4b2}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.card{{background:#151923;border:1px solid #242b38;border-radius:16px;padding:22px}}
input,select{{width:100%;box-sizing:border-box;background:#0f131b;color:#fff;border:1px solid #30394a;border-radius:10px;padding:12px;margin:6px 0 14px}}
button{{background:#fff;color:#111;border:0;border-radius:10px;padding:12px 18px;font-weight:700;cursor:pointer}}
table{{width:100%;border-collapse:collapse;margin-top:12px}} th,td{{text-align:left;padding:12px;border-bottom:1px solid #252c39}} th{{color:#9aa4b2;font-size:13px}} .empty{{text-align:center;color:#9aa4b2;padding:28px}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body><main>
<nav><div><div class="brand">YouTube Factory</div><div class="muted">Funny Reaction Long Video V1</div></div><div class="muted">Milestone 1</div></nav>
<div class="grid">
<section class="card">
<h2>Create Project</h2>
<form method="post" action="/projects">
<label>Project name</label><input name="name" placeholder="Funniest gym fails reaction" required>
<label>Topic</label><input name="topic" placeholder="Optional topic idea">
<label>Target length</label><select name="target_length"><option value="">Auto</option><option>8</option><option>10</option><option>12</option><option>15</option></select>
<button type="submit">Create Video Project</button>
</form>
</section>
<section class="card"><h2>V1 Pipeline</h2><p class="muted">Project → Upload → Normalize → Transcribe → Analyze → Edit → Render → Thumbnail → Metadata → YouTube.</p><p>Current build locks down the project/job state before media processing is added.</p></section>
</div>
<section class="card" style="margin-top:18px"><h2>Projects</h2><table><thead><tr><th>Project</th><th>Status</th><th>Progress</th><th>Source</th><th>YouTube</th></tr></thead><tbody>{body_rows}</tbody></table></section>
</main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send_text(self, text: str, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        payload = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/":
            self.send_text(dashboard_html(STORE.list_projects()))
            return
        if self.path == "/api/projects":
            self.send_text(json.dumps(STORE.list_projects()), content_type="application/json")
            return
        self.send_text("Not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        if self.path != "/projects":
            self.send_text("Not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        target_raw = form.get("target_length", [""])[0]
        target = int(target_raw) if target_raw.isdigit() else None
        STORE.create_project(
            name=form.get("name", ["Untitled reaction video"])[0],
            topic=form.get("topic", [""])[0],
            target_length_minutes=target,
        )
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


def run(host: str = "127.0.0.1", port: int = 8787) -> None:
    print(f"YouTube Factory dashboard: http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    run()
