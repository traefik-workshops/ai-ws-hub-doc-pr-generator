"""classify.py — heuristics for: needs_release_note?, needs_screenshots?, doc_kind.

Single entry point is `classify(bundle, grounding, hub_doc_path=None)`; returns a dict
shaped as described in spec.md §6.3.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

_PREFIX_RE = re.compile(r"^(?P<type>feat|fix|chore|refactor|test|docs|style|perf|build|ci)\b")


def feature_type(title: str) -> str:
    m = _PREFIX_RE.match(title.strip().lower())
    return m["type"] if m else "other"


def needs_release_note(pr: dict, *, impl_repo: str) -> dict:
    if impl_repo != "traefik/traefik-hub":
        return {
            "verdict": "no",
            "signals": ["oss-short-circuit"],
            "proposed_shape": None,
            "proposed_section_heading": None,
        }

    title = (pr.get("title") or "").lower()
    body = (pr.get("body") or "").lower()
    labels = {l.lower() for l in pr.get("labels", [])}
    signals: list[str] = []
    shape: str | None = None

    if "breaking-change" in labels or "breaking change:" in body:
        signals.append("breaking-change-signal")
        shape = "breaking-subsection"
    elif any(k in title or k in body for k in ("graduates to ga", "general availability", " ga ", "now generally available")):
        signals.append("ga-graduation-signal")
        shape = "ga-bullet"
    elif feature_type(title) == "feat":
        signals.append("feat-prefix")
        if "feature" in labels or "enhancement" in labels:
            signals.append("feature-label")
        shape = "ea-subsection"
    elif feature_type(title) in {"fix", "chore", "refactor", "test", "docs", "style", "perf", "build", "ci"}:
        return {
            "verdict": "no",
            "signals": [f"{feature_type(title)}-prefix"],
            "proposed_shape": None,
            "proposed_section_heading": None,
        }
    else:
        return {
            "verdict": "ask",
            "signals": ["no-conclusive-signal"],
            "proposed_shape": None,
            "proposed_section_heading": None,
        }

    return {
        "verdict": "yes",
        "signals": signals,
        "proposed_shape": shape,
        "proposed_section_heading": _title_to_heading(pr.get("title", "")),
    }


def _title_to_heading(title: str) -> str:
    # Strip "feat: " / "fix: " etc.; Title-Case the remainder.
    stripped = _PREFIX_RE.sub("", title, count=1).lstrip(":").strip()
    return stripped[:1].upper() + stripped[1:] if stripped else ""


_UI_MARKER_RE = re.compile(r"<BrowserWindow\b|!\[[^\]]*\]\(/img/")


def needs_screenshots(*, neighbor_paths: list[str], touched_paths: list[str]) -> dict:
    signals: list[str] = []
    ui_touch = any(
        p.startswith("hub/dashboard/") or p.startswith("hub/portal/")
        for p in touched_paths
    )
    if ui_touch:
        signals.append("ui-code-touched")
        return {"verdict": "yes", "signals": signals}

    if not neighbor_paths:
        return {"verdict": "no", "signals": ["no-neighbors"]}

    hits = 0
    for p in neighbor_paths:
        try:
            text = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _UI_MARKER_RE.search(text):
            hits += 1

    ratio = hits / len(neighbor_paths)
    signals.append(f"neighbor-ui-ratio={ratio:.2f}")
    if ratio >= 0.5:
        return {"verdict": "yes", "signals": signals}
    return {"verdict": "no", "signals": signals}
