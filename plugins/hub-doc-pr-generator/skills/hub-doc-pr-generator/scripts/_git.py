"""Thin wrapper around `git -C <path>`. Never `cd`s."""
from __future__ import annotations
import subprocess


class GitError(RuntimeError):
    pass


def run(repo_path: str, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed in {repo_path}: {proc.stderr.strip()}")
    return proc.stdout


def head_branch(repo_path: str) -> str:
    return run(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def is_dirty(repo_path: str) -> bool:
    return bool(run(repo_path, ["status", "--porcelain"]).strip())


def show_many(repo_path: str, specs: list[str]) -> dict[str, str | None]:
    """Batch-fetch multiple blob contents (e.g. "HEAD:docs/foo.md") in a
    single `git cat-file --batch` subprocess, instead of one `git show`
    process per spec -- a PR that overwrites several existing pages
    previously paid one blocking subprocess spawn per file just for this.

    Returns {spec: content}; a spec git reports as `missing` (e.g. the path
    doesn't exist at that ref, as for a brand-new file) maps to None rather
    than raising, since "not present at this ref" is an expected outcome
    here, not an error."""
    if not specs:
        return {}
    proc = subprocess.run(
        ["git", "-C", repo_path, "cat-file", "--batch"],
        input=("\n".join(specs) + "\n").encode(),
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        raise GitError(
            f"git cat-file --batch failed in {repo_path}: "
            f"{proc.stderr.decode(errors='replace').strip()}"
        )
    out = proc.stdout
    results: dict[str, str | None] = {}
    pos = 0
    spec_iter = iter(specs)
    while pos < len(out):
        nl = out.index(b"\n", pos)
        header = out[pos:nl].decode()
        spec = next(spec_iter)
        if header.endswith(" missing"):
            results[spec] = None
            pos = nl + 1
            continue
        # header is "<sha> <type> <size>"; content is exactly <size> bytes,
        # followed by one trailing newline before the next object's header.
        size = int(header.rsplit(" ", 1)[-1])
        content_start = nl + 1
        content_end = content_start + size
        results[spec] = out[content_start:content_end].decode("utf-8", errors="replace")
        pos = content_end + 1
    return results
