"""open_pr.py — push + draft PR (Hub) or commit (OSS)."""
from __future__ import annotations
import argparse
import json
import sys
from typing import Optional
from scripts import _gh, _git


def detect_fork(*, upstream: str) -> Optional[str]:
    user = _gh.current_user_login()
    repos = _gh.run_json([
        "repo", "list", user, "--fork",
        "--json", "name,parent",
    ])
    for r in repos:
        parent = (r.get("parent") or {}).get("nameWithOwner", "")
        if parent == upstream:
            return f"{user}/{r['name']}"
    return None
