from __future__ import annotations

import html
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from .media import save_project_upload
from .models import ProjectStatus
from .store import JsonStore

app = FastAPI(title="YouTube Factory V1")
STORE = JsonStore()


STYLE = """
<style>
body{font-family:Arial,sans-serif;background:#0b0d12;color:#f5f7fb;margin:0}main{max-width:1100px;margin:0 auto;padding:32px}nav{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px}.brand{font-size:24px;font-weight:700}.muted{color:#9aa4b2}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.card{background:#151923;border:1px solid #242b38;border-radius:16px;padding:22px}input,select{width:100%;box-sizing:border-box;background:#0f131b;color:#fff;border:1px solid #30394a;border-radius:10px;padding:12px;margin:6px 0 14px}button,.button{display:inline-block;background:#fff;color:#111;border:0;border-radius:10px;padding:12px 18px;font-weight:700;cursor:pointer;text-decoration:none}table{width:100%;border-collapse:collapse;margin-top:12px}th,td{text-align:left;padding:12px;border-bottom:1px solid #252c39}th{color:#9aa4b2;font-size:13px}.empty{text-align:center;color:#9aa4b2;padding:28px}.ok{color:#86efac}.warn{color:#fcd34d}@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style>
"""


def page(title: str, body: str) -> str:
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>{STYLE}</head><body><main>{body}</main></body></html>"


def dashboard_html() -> str:
    rows = []
    for project in STORE.list_projects():
        pid = html.escape(project["id"])
        rows.append(
            "<tr>"
            f"<td><a href='/projects/{pid}' style='color:white'>{html.escape(project['name'])}</a></td>"
            f"<td>{html.escape(project['status'])}</td>"
            f"<td>{int(project['progress'])}%</td>"
            f"<td>{html.escape(project.get('source_filename') or '—')}</td>"
            f"<td>{html.escape(project.get('reaction_filename') or '—')}</td>"
            "</tr>"
        )
    body_rows = "".join(rows) or '<tr><td colspan="5" class="empty">No projects yet.</td></tr>'
    body = f"""
<nav><div><div class='brand'>YouTube Factory</div><div class='muted'>Funny Reaction Long Video V1</div></div><div class='muted'>Milestone 2</div></nav>
<div class='grid'>
<section class='card'><h2>Create Project</h2><form method='post' action='/projects'><label>Project name</label><input name='name' placeholder='Funniest gym fails reaction' required><label>Topic</label><input name='topic' placeholder='Optional topic idea'><label>Target length</label><select name='target_length'><option value=''>Auto</option><option>8</option><option>10</option><option>12</option><option>15</option></select><button type='submit'>Create Video Project</button></form></section>
<section class='card'><h2>V1 Pipeline</h2><p class='muted'>Project → Upload → Normalize → Transcribe → Analyze → Edit → Render → Thumbnail → Metadata → YouTube.</p><p>Current milestone accepts and stores the two original videos safely per project.</p></section>
</div>
<section class='card' style='margin-top:18px'><h2>Projects</h2><table><thead><tr><th>Project</th><th>Status</th><th>Progress</th><th>Source</th><th>Reaction</th></tr></thead><tbody>{body_rows}</tbody></table></section>
"""
    return page("YouTube Factory", body)


def project_html(project: dict) -> str:
    source = html.escape(project.get("source_filename") or "Not uploaded")
    reaction = html.escape(project.get("reaction_filename") or "Not uploaded")
    ready = bool(project.get("source_filename") and project.get("reaction_filename"))
    status_note = "Both videos are uploaded. Ready for FFmpeg normalization." if ready else "Upload both videos to continue."
    body = f"""
<nav><div><div class='brand'>YouTube Factory</div><div class='muted'>{html.escape(project['name'])}</div></div><a class='button' href='/'>Dashboard</a></nav>
<div class='grid'>
<section class='card'><h2>Source Video</h2><p class='muted'>Current: {source}</p><form method='post' action='/projects/{html.escape(project['id'])}/upload/source' enctype='multipart/form-data'><input type='file' name='video' accept='.mp4,.mov,video/mp4,video/quicktime' required><button type='submit'>Upload Source</button></form></section>
<section class='card'><h2>Reaction Video</h2><p class='muted'>Current: {reaction}</p><form method='post' action='/projects/{html.escape(project['id'])}/upload/reaction' enctype='multipart/form-data'><input type='file' name='video' accept='.mp4,.mov,video/mp4,video/quicktime' required><button type='submit'>Upload Reaction</button></form></section>
</div>
<section class='card' style='margin-top:18px'><h2>Status</h2><p class='{'ok' if ready else 'warn'}'>{html.escape(status_note)}</p><p>Status: {html.escape(project['status'])} · Progress: {int(project['progress'])}%</p></section>
"""
    return page(project["name"], body)


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return dashboard_html()


@app.post("/projects")
def create_project(name: str = Form(...), topic: str = Form(""), target_length: str = Form("")) -> RedirectResponse:
    target = int(target_length) if target_length.isdigit() else None
    project = STORE.create_project(name=name, topic=topic, target_length_minutes=target)
    return RedirectResponse(f"/projects/{project['id']}", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(project_id: str) -> str:
    project = STORE.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project_html(project)


@app.post("/projects/{project_id}/upload/{role}")
async def upload_video(project_id: str, role: str, video: UploadFile = File(...)) -> RedirectResponse:
    project = STORE.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if role not in {"source", "reaction"}:
        raise HTTPException(400, "Invalid upload role")

    try:
        saved = await save_project_upload(project_id, role, video)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    changes = {
        f"{role}_filename": saved.filename,
        f"{role}_path": saved.path,
        f"{role}_size_bytes": saved.size_bytes,
    }
    current = STORE.update_project(project_id, **changes)
    if current.get("source_filename") and current.get("reaction_filename"):
        STORE.update_project(project_id, status=ProjectStatus.UPLOADED.value, progress=10)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@app.get("/api/projects")
def api_projects() -> list[dict]:
    return STORE.list_projects()


@app.get("/api/projects/{project_id}")
def api_project(project_id: str) -> dict:
    project = STORE.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def run(host: str = "127.0.0.1", port: int = 8787) -> None:
    import uvicorn

    uvicorn.run("youtube_factory.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
