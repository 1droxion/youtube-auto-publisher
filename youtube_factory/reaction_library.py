from __future__ import annotations

import json
import os
import random
import shutil
from pathlib import Path
from typing import Any

# Reuse the same label buckets already proven in Reaction Factory.
BUCKETS = [
    (("fail", "fall", "funny", "lol", "prank", "oops"), ("laugh", "funny", "lol")),
    (("wow", "crazy", "unbelievable", "shock"), ("shock", "wow", "surprised")),
    (("cute", "baby", "dog", "cat", "sweet"), ("smile", "cute", "happy")),
    (("awkward", "cringe", "weird"), ("cringe", "confused")),
]


def _candidate_roots() -> list[Path]:
    configured = os.getenv("REACTION_FACTORY_ROOT", "").strip()
    roots: list[Path] = []
    if configured:
        roots.append(Path(configured).expanduser())
    # Common sibling-clone layouts. These are only fallbacks; no hard dependency.
    here = Path(__file__).resolve()
    roots.extend(
        [
            here.parents[2] / "fb-reaction-factoryr" / "fb-reaction-factory",
            here.parents[1] / "fb-reaction-factory",
            Path.cwd() / "fb-reaction-factory",
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def find_reaction_factory_root() -> Path | None:
    for root in _candidate_roots():
        if (root / "reactions").is_dir() or (root / "data" / "reactions.json").exists():
            return root
    return None


def load_reactions() -> list[dict[str, Any]]:
    root = find_reaction_factory_root()
    if not root:
        return []

    index_path = root / "data" / "reactions.json"
    items: list[dict[str, Any]] = []
    if index_path.exists():
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                items = [dict(item) for item in raw if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            items = []

    # If the old index is unavailable, still expose video files as unlabeled clips.
    if not items:
        reactions_dir = root / "reactions"
        if reactions_dir.is_dir():
            for path in sorted(reactions_dir.iterdir()):
                if path.suffix.lower() in {".mp4", ".mov", ".m4v"}:
                    items.append({"id": path.stem, "label": "reaction", "path": str(path), "notes": ""})

    normalized: list[dict[str, Any]] = []
    for item in items:
        raw_path = Path(str(item.get("path") or ""))
        if not raw_path.is_absolute():
            raw_path = root / raw_path
        if not raw_path.exists():
            fallback = root / "reactions" / raw_path.name
            if fallback.exists():
                raw_path = fallback
        if raw_path.exists() and raw_path.suffix.lower() in {".mp4", ".mov", ".m4v"}:
            normalized.append(
                {
                    "id": str(item.get("id") or raw_path.stem),
                    "label": str(item.get("label") or "reaction").lower().strip(),
                    "path": str(raw_path),
                    "notes": str(item.get("notes") or ""),
                }
            )
    return normalized


def choose_reaction(context: str = "", preferred: str = "auto") -> dict[str, Any]:
    items = load_reactions()
    if not items:
        raise RuntimeError(
            "No Reaction Factory clips were found. Set REACTION_FACTORY_ROOT to the existing Reaction Factory folder, or upload a reaction video."
        )

    preferred = (preferred or "auto").lower().strip()
    if preferred != "auto":
        matches = [item for item in items if item["label"] == preferred or item["id"] == preferred]
        if matches:
            return random.choice(matches)

    text = (context or "").lower()
    for keywords, labels in BUCKETS:
        if any(keyword in text for keyword in keywords):
            matches = [item for item in items if item["label"] in labels]
            if matches:
                return random.choice(matches)
    return random.choice(items)


def copy_reaction_to_project(project_id: str, context: str = "", preferred: str = "auto") -> dict[str, Any]:
    chosen = choose_reaction(context=context, preferred=preferred)
    source = Path(chosen["path"])
    project_dir = Path(__file__).resolve().parent / "data" / "projects" / project_id / "original"
    project_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower() if source.suffix.lower() in {".mp4", ".mov", ".m4v"} else ".mp4"
    destination = project_dir / f"reaction{suffix}"
    shutil.copy2(source, destination)
    return {
        "filename": source.name,
        "path": str(destination),
        "size_bytes": destination.stat().st_size,
        "reaction_factory_id": chosen["id"],
        "reaction_factory_label": chosen["label"],
    }
