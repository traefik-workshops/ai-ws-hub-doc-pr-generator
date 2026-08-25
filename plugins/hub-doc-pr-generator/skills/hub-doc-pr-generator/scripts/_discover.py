"""_discover.py — locate local hub-doc clone and the OSS impl repo from cwd.

Discovery is best-effort. If hub-doc can't be auto-found, the orchestrator
prompts the engineer via AskUserQuestion and calls persist_hub_doc() with the
answer so future runs skip discovery.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from scripts import _git

HUB_DOC_URL_RE = re.compile(
    r"github\.com[:/](?P<owner>[^/]+)/hub-doc(?:\.git)?/?$"
)

CONFIG_PATH = Path.home() / ".config" / "hub-doc-pr-generator" / "config.json"

COMMON_PARENTS = [
    Path.home() / "code",
    Path.home() / "dev",
    Path.home() / "src",
    Path.home() / "Developer",
    Path.home() / "workspace",
    Path.home() / "projects",
    Path.home() / "git",
]


def _is_hub_doc_clone(path: Path) -> bool:
    """True iff path is a git repo whose origin matches traefik/hub-doc or a fork of it."""
    if not (path / ".git").exists():
        return False
    try:
        url = _git.run(str(path), ["config", "--get", "remote.origin.url"]).strip()
    except _git.GitError:
        return False
    return bool(HUB_DOC_URL_RE.search(url))


def _load_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _siblings_of(cwd: Path, depth: int = 5) -> list[Path]:
    """Walk up cwd looking for a sibling 'hub-doc' directory at each level."""
    found: list[Path] = []
    seen: set[Path] = set()
    p = cwd.resolve()
    for _ in range(depth):
        for candidate in (p / "hub-doc", p.parent / "hub-doc"):
            if candidate.is_dir() and candidate not in seen:
                seen.add(candidate)
                found.append(candidate)
        if p.parent == p:
            break
        p = p.parent
    return found


def _scan_common_parents() -> list[Path]:
    """Look for a 'hub-doc' directory under common workspace dirs (one level deep + one nested)."""
    found: list[Path] = []
    for parent in COMMON_PARENTS:
        if not parent.is_dir():
            continue
        try:
            for child in parent.iterdir():
                if not child.is_dir():
                    continue
                if child.name == "hub-doc":
                    found.append(child)
                else:
                    nested = child / "hub-doc"
                    if nested.is_dir():
                        found.append(nested)
        except OSError:
            continue
    return found


def discover_hub_doc(*, cwd: Optional[str] = None, env: Optional[dict] = None) -> Optional[str]:
    """Return an absolute path to a local hub-doc clone, or None if not found.

    Search order:
      1. $HUB_DOC_PATH env var (escape hatch)
      2. Persisted config at ~/.config/hub-doc-pr-generator/config.json
      3. Sibling dirs of cwd (walks up to depth 5)
      4. Common workspace parents (~/code, ~/dev, ~/src, ~/Developer, etc.)
    """
    env_map = env if env is not None else os.environ
    cwd_p = Path(cwd) if cwd else Path.cwd()

    explicit = env_map.get("HUB_DOC_PATH")
    if explicit and _is_hub_doc_clone(Path(explicit)):
        return str(Path(explicit).resolve())

    saved = _load_config().get("hub_doc_path")
    if saved and _is_hub_doc_clone(Path(saved)):
        return str(Path(saved).resolve())

    for cand in _siblings_of(cwd_p):
        if _is_hub_doc_clone(cand):
            return str(cand.resolve())

    for cand in _scan_common_parents():
        if _is_hub_doc_clone(cand):
            return str(cand.resolve())

    return None


def persist_hub_doc(path: str) -> None:
    """Save a confirmed hub-doc path so future runs skip discovery."""
    cfg = _load_config()
    cfg["hub_doc_path"] = str(Path(path).resolve())
    _save_config(cfg)


def discover_python_path() -> Optional[str]:
    """A previously-resolved Python 3.11+ interpreter path, if one was saved
    after the default `python3` on PATH turned out to be too old."""
    return _load_config().get("python_path")


def persist_python_path(path: str) -> None:
    """Save a confirmed Python 3.11+ interpreter path so future runs (and the
    rest of this run's script invocations) don't have to rediscover it."""
    cfg = _load_config()
    cfg["python_path"] = path
    _save_config(cfg)


# Kept in sync with setup.py's check_python_version()/find_compatible_python()
# gate -- this is the same minimum, just consulted by the re-exec guard below
# instead of by the interactive preflight check.
MIN_PYTHON = (3, 11)


def reexec_target(*, current_version: tuple[int, int],
                   persisted_path: Optional[str],
                   current_executable: Optional[str] = None) -> Optional[str]:
    """Pure decision function: which interpreter path (if any) a script
    running under `current_version` should re-exec itself under.

    Extracted from the actual re-exec side effect (os.execv, in
    maybe_reexec() below) so the decision itself -- "should I re-exec, and to
    what path" -- is unit-testable without actually replacing the process.

    Returns None (no re-exec) when:
    - `current_version` already meets MIN_PYTHON (nothing to fix), or
    - no `persisted_path` is on file (setup.py's preflight hasn't discovered
      and saved one yet -- nothing to re-exec to), or
    - `persisted_path` is the same interpreter already running (would
      re-exec into an identical, still-too-old process forever)."""
    if current_version >= MIN_PYTHON:
        return None
    if not persisted_path:
        return None
    if current_executable and persisted_path == current_executable:
        return None
    return persisted_path


def maybe_reexec() -> None:
    """Startup guard a script can call before doing any real work: if running
    under a Python older than MIN_PYTHON and a persisted `python_path` exists
    (saved by setup.py's check_python_version() after a previous run
    discovered it), transparently re-exec the exact same invocation under
    that interpreter via os.execv, so a stray `python3 -m scripts.foo`
    self-corrects instead of failing outright or requiring the operator to
    remember and retype the full interpreter path every session (see
    traefik-hub#1435 finding #6).

    Deliberately narrow: this does not restructure the CLI surface or change
    argv in any way, and does nothing at all when there's no persisted path
    to fall back to -- the existing "Python 3.11+ required" error from
    setup.py's own preflight still fires normally in that case."""
    target = reexec_target(
        current_version=sys.version_info[:2],
        persisted_path=discover_python_path(),
        current_executable=sys.executable,
    )
    if target is None:
        return
    os.execv(target, [target, *sys.argv])


def discover_oss(*, cwd: Optional[str] = None) -> Optional[str]:
    """Return the OSS impl repo root by walking up from cwd. None if cwd isn't in a git repo."""
    cwd_p = Path(cwd) if cwd else Path.cwd()
    try:
        return _git.run(str(cwd_p), ["rev-parse", "--show-toplevel"]).strip()
    except _git.GitError:
        return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Locate local clones used by the skill.")
    sub = parser.add_subparsers(dest="target", required=True)
    sub.add_parser("hub-doc", help="Print path to local hub-doc clone, or exit 2 if not found.")
    sub.add_parser("oss", help="Print the OSS impl repo root from cwd, or exit 2 if cwd isn't a git repo.")
    save = sub.add_parser("save-hub-doc", help="Persist a hub-doc path for future runs.")
    save.add_argument("path")
    args = parser.parse_args(argv)

    if args.target == "hub-doc":
        path = discover_hub_doc()
        if path is None:
            print("hub-doc clone not found", file=sys.stderr)
            return 2
        print(path)
        return 0
    if args.target == "oss":
        path = discover_oss()
        if path is None:
            print("not a git repo (cwd)", file=sys.stderr)
            return 2
        print(path)
        return 0
    if args.target == "save-hub-doc":
        persist_hub_doc(args.path)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
