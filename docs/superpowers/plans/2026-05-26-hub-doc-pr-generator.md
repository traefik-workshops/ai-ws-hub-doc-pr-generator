# Hub-doc PR Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill that turns an implementation PR in `traefik/traefik-hub` or `traefik/traefik` into a fully-drafted documentation PR (Hub flow) or doc commit on the impl PR branch (OSS flow), following the conventions and grounding sources defined in `spec.md`.

**Architecture:** A `SKILL.md` orchestrator that pipes deterministic Python (stdlib) helper scripts (`fetch_pr.py`, `fetch_grounding.py`, `classify.py`, `locate_targets.py`, `preview.py`, `open_pr.py`). The LLM does the prose-writing and judgment calls; the helpers do all GitHub I/O via `gh` shell-outs, JSON serialization, and rule-based classification. Each helper has a stable JSON contract and is independently testable.

**Tech Stack:** Python 3.11+ (stdlib only — `subprocess`, `argparse`, `json`, `re`, `pathlib`, `urllib.request`, `unittest`). `gh` CLI for all GitHub access. Markdown for SKILL.md and templates. `bash` for the install/test runner shim.

---

## File Structure

Files created (paths relative to `ai-ws-hub-doc-pr-generator/`):

```
SKILL.md                              # orchestrator; auto-discovered by Claude Code
README.md                             # install + invocation docs for engineers
.gitignore                            # ignore __pycache__, .venv, *.pyc, /tmp/
Makefile                              # `make test` / `make lint` shortcuts

scripts/
├── __init__.py                       # makes scripts/ a package for tests
├── _gh.py                            # thin wrapper around `gh` (auth check + subprocess)
├── _git.py                           # thin wrapper around `git -C <path>` calls
├── fetch_pr.py                       # gh → pr-bundle.json (single + multi-PR)
├── fetch_grounding.py                # traefik/reference → grounding.json
├── classify.py                       # heuristics → classify.json
├── locate_targets.py                 # candidate paths + neighbors → locate.json
├── preview.py                        # write files + git diff + lint
├── open_pr.py                        # fork detect + push + draft PR (Hub) / commit (OSS)
└── tests/
    ├── __init__.py
    ├── fixtures/
    │   ├── gh_pr_view_hub_feat.json
    │   ├── gh_pr_diff_hub_feat.patch
    │   ├── gh_pr_view_oss_feat.json
    │   ├── gh_sub_issues.json
    │   ├── reference_INDEX.md
    │   ├── reference_DOC_INDEX.json
    │   ├── hub_doc_release_notes_excerpt.mdx
    │   └── hub_doc_neighbor_middleware.md
    ├── test_fetch_pr.py
    ├── test_fetch_grounding.py
    ├── test_classify.py
    ├── test_locate_targets.py
    ├── test_preview.py
    └── test_open_pr.py

templates/
├── hub-page.md.tmpl                  # Docusaurus front matter + skeleton
├── oss-page.md.tmpl                  # MkDocs front matter + skeleton
├── sidebar-entry.json.tmpl           # sidebars.js snippet
├── release-note-ea.mdx.tmpl          # EA subsection
├── release-note-ga-subsection.mdx.tmpl
├── release-note-ga-bullet.mdx.tmpl
├── release-note-breaking.mdx.tmpl
└── pr-body.md.tmpl                   # doc-PR body

references/
├── hub-doc-conventions.md            # convention catalog (loaded on demand)
├── oss-doc-conventions.md
├── screenshot-heuristics.md
└── release-note-heuristics.md
```

**Responsibility boundaries:**
- `_gh.py` / `_git.py`: only the shell-out plumbing. Shared by every other helper.
- Each `<thing>.py` in `scripts/`: takes JSON input or CLI flags, emits a single JSON document to stdout, exits non-zero on hard failures. Pure data-in/data-out.
- `SKILL.md`: the only file that knows the overall workflow. It tells the LLM: "run this helper, read its JSON, ask the engineer X, then run that helper."
- `templates/`: static markdown/mdx scaffolds. No logic.
- `references/`: prose documentation about conventions, loaded on demand by the LLM.

---

## Phase 0: Repo bootstrap

### Task 0.1: Initialize the repo layout

**Files:**
- Create: `.gitignore`
- Create: `Makefile`
- Create: `scripts/__init__.py`
- Create: `scripts/tests/__init__.py`
- Create: `scripts/tests/fixtures/.gitkeep`
- Create: `templates/.gitkeep`
- Create: `references/.gitkeep`

- [ ] **Step 1: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.python-version
/tmp/
.DS_Store
*.swp
.pytest_cache/
.coverage
```

- [ ] **Step 2: Create `Makefile`**

```makefile
.PHONY: test lint format help

PYTHON ?= python3

help:
	@echo "make test    - run unit tests"
	@echo "make lint    - run pyflakes on scripts/"
	@echo "make format  - reformat with ruff if available"

test:
	$(PYTHON) -m unittest discover -s scripts/tests -t . -v

lint:
	$(PYTHON) -m pyflakes scripts/ || true

format:
	@command -v ruff >/dev/null 2>&1 && ruff format scripts/ || echo "ruff not installed; skipping"
```

- [ ] **Step 3: Create empty `__init__.py` files and `.gitkeep` placeholders**

All three `__init__.py` files are empty. `.gitkeep` files are empty.

- [ ] **Step 4: Verify the layout**

Run: `find . -type f -not -path './.git/*' | sort`
Expected: lists `.gitignore`, `Makefile`, `scripts/__init__.py`, `scripts/tests/__init__.py`, `scripts/tests/fixtures/.gitkeep`, `templates/.gitkeep`, `references/.gitkeep`, `spec.md`, `docs/superpowers/plans/2026-05-26-hub-doc-pr-generator.md`.

- [ ] **Step 5: Commit**

```bash
git add .gitignore Makefile scripts/__init__.py scripts/tests/__init__.py \
        scripts/tests/fixtures/.gitkeep templates/.gitkeep references/.gitkeep
git commit -m "chore: scaffold repo layout"
```

---

### Task 0.2: Add shared `_gh.py` and `_git.py` helpers

**Files:**
- Create: `scripts/_gh.py`
- Create: `scripts/_git.py`
- Test: `scripts/tests/test_gh.py`, `scripts/tests/test_git.py`

- [ ] **Step 1: Write the failing test for `_gh.py`**

`scripts/tests/test_gh.py`:

```python
import unittest
from unittest.mock import patch
from scripts import _gh


class TestGh(unittest.TestCase):
    def test_run_json_parses_stdout(self):
        with patch("scripts._gh._run") as mock_run:
            mock_run.return_value = '{"number": 42}'
            result = _gh.run_json(["pr", "view", "42"])
        self.assertEqual(result, {"number": 42})

    def test_run_text_returns_raw_stdout(self):
        with patch("scripts._gh._run") as mock_run:
            mock_run.return_value = "raw patch text\n"
            result = _gh.run_text(["pr", "diff", "42"])
        self.assertEqual(result, "raw patch text\n")

    def test_assert_auth_raises_on_missing(self):
        with patch("scripts._gh._run") as mock_run:
            mock_run.side_effect = _gh.GhError("not logged in")
            with self.assertRaises(_gh.GhError):
                _gh.assert_auth()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_gh -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts._gh'`.

- [ ] **Step 3: Implement `_gh.py`**

```python
"""Thin wrapper around the `gh` CLI. All GitHub I/O in this skill goes through here."""
from __future__ import annotations
import json
import shutil
import subprocess
from typing import Any


class GhError(RuntimeError):
    """Raised when `gh` fails or is not usable."""


def _run(args: list[str]) -> str:
    if shutil.which("gh") is None:
        raise GhError("gh CLI not found on PATH. Install: https://cli.github.com/")
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise GhError(f"gh {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def run_json(args: list[str]) -> Any:
    return json.loads(_run(args))


def run_text(args: list[str]) -> str:
    return _run(args)


def assert_auth() -> None:
    try:
        _run(["auth", "status"])
    except GhError as e:
        raise GhError(f"gh not authenticated. Run `gh auth login`. ({e})") from e


def current_user_login() -> str:
    return run_json(["api", "user", "--jq", "{login: .login}"])["login"]
```

- [ ] **Step 4: Write the failing test for `_git.py`**

`scripts/tests/test_git.py`:

```python
import unittest
from unittest.mock import patch
from scripts import _git


class TestGit(unittest.TestCase):
    def test_run_in_dir_uses_minus_C(self):
        with patch("scripts._git.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "abc123\n"
            mock_run.return_value.stderr = ""
            _git.run("/repo", ["rev-parse", "HEAD"])
        called_args = mock_run.call_args[0][0]
        self.assertEqual(called_args[:3], ["git", "-C", "/repo"])

    def test_run_raises_on_nonzero(self):
        with patch("scripts._git.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "fatal: not a git repo"
            with self.assertRaises(_git.GitError):
                _git.run("/notrepo", ["status"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_git -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 6: Implement `_git.py`**

```python
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
```

- [ ] **Step 7: Run all tests**

Run: `python3 -m unittest discover -s scripts/tests -v`
Expected: 5 tests pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/_gh.py scripts/_git.py scripts/tests/test_gh.py scripts/tests/test_git.py
git commit -m "feat: add shared gh and git helpers with tests"
```

---

## Phase 1: `fetch_pr.py` — normalize PRs into a JSON bundle

### Task 1.1: Parse PR input (URL, number, or current branch)

**Files:**
- Create: `scripts/fetch_pr.py` (initial skeleton)
- Test: `scripts/tests/test_fetch_pr.py` (input parsing only for now)

- [ ] **Step 1: Write failing tests for input parsing**

`scripts/tests/test_fetch_pr.py`:

```python
import unittest
from scripts.fetch_pr import parse_pr_inputs, PrRef


class TestParsePrInputs(unittest.TestCase):
    def test_url_form(self):
        refs = parse_pr_inputs(
            ["https://github.com/traefik/traefik-hub/pull/1234"], cwd_remote=None
        )
        self.assertEqual(refs, [PrRef("traefik/traefik-hub", 1234)])

    def test_multiple_urls(self):
        refs = parse_pr_inputs(
            [
                "https://github.com/traefik/traefik-hub/pull/1234",
                "https://github.com/traefik/traefik-hub/pull/1240",
            ],
            cwd_remote=None,
        )
        self.assertEqual(
            refs,
            [PrRef("traefik/traefik-hub", 1234), PrRef("traefik/traefik-hub", 1240)],
        )

    def test_number_uses_cwd_remote(self):
        refs = parse_pr_inputs(["1234"], cwd_remote="traefik/traefik-hub")
        self.assertEqual(refs, [PrRef("traefik/traefik-hub", 1234)])

    def test_number_without_cwd_raises(self):
        with self.assertRaises(ValueError):
            parse_pr_inputs(["1234"], cwd_remote=None)

    def test_mixed_repos_raises(self):
        with self.assertRaises(ValueError):
            parse_pr_inputs(
                [
                    "https://github.com/traefik/traefik-hub/pull/1234",
                    "https://github.com/traefik/traefik/pull/9999",
                ],
                cwd_remote=None,
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.fetch_pr'`.

- [ ] **Step 3: Implement parsing**

`scripts/fetch_pr.py`:

```python
"""fetch_pr.py — gather PR + linked issues + sub-issues + diff into a JSON bundle.

Usage:
  python -m scripts.fetch_pr --repo traefik/traefik-hub --pr 1234 [--pr 1240 ...]
  python -m scripts.fetch_pr --auto-detect          # cwd must be a checked-out PR branch
  python -m scripts.fetch_pr --url https://github.com/owner/repo/pull/N [...]

Emits a single JSON document on stdout.
"""
from __future__ import annotations
import argparse
import re
import sys
from dataclasses import dataclass
from typing import Optional


_PR_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<num>\d+)/?$"
)


@dataclass(frozen=True)
class PrRef:
    repo: str   # "owner/name"
    number: int


def parse_pr_inputs(args: list[str], cwd_remote: Optional[str]) -> list[PrRef]:
    refs: list[PrRef] = []
    for arg in args:
        m = _PR_URL_RE.match(arg)
        if m:
            refs.append(PrRef(f"{m['owner']}/{m['repo']}", int(m["num"])))
            continue
        if arg.isdigit():
            if cwd_remote is None:
                raise ValueError(
                    f"PR number {arg!r} given without a cwd remote — pass a full URL "
                    "or run from inside the impl repo."
                )
            refs.append(PrRef(cwd_remote, int(arg)))
            continue
        raise ValueError(f"unrecognized PR input: {arg!r}")

    if not refs:
        raise ValueError("no PRs given")

    repos = {ref.repo for ref in refs}
    if len(repos) > 1:
        raise ValueError(
            f"cross-repo multi-PR not supported (got {sorted(repos)}). "
            "Run the skill once per impl repo."
        )
    return refs


def main(argv: list[str]) -> int:
    # Filled in by later tasks.
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", action="append", default=[])
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--repo", default=None)
    parser.add_argument("--auto-detect", action="store_true")
    parser.parse_args(argv)
    print("{}", file=sys.stdout)  # placeholder
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_pr.py scripts/tests/test_fetch_pr.py
git commit -m "feat: parse PR URL/number inputs in fetch_pr"
```

---

### Task 1.2: Fetch single-PR data from `gh`

**Files:**
- Modify: `scripts/fetch_pr.py`
- Modify: `scripts/tests/test_fetch_pr.py`
- Create: `scripts/tests/fixtures/gh_pr_view_hub_feat.json`
- Create: `scripts/tests/fixtures/gh_pr_diff_hub_feat.patch`

- [ ] **Step 1: Create the PR view fixture**

`scripts/tests/fixtures/gh_pr_view_hub_feat.json`:

```json
{
  "number": 1234,
  "title": "feat: add onDenyResponse to token ratelimit middleware",
  "body": "Adds customizable deny responses.\n\nCloses #5678\nRelated to #5680",
  "labels": [{"name": "feature"}, {"name": "ai-gateway"}],
  "author": {"login": "octocat"},
  "headRefName": "feat/token-ratelimit-deny",
  "baseRefName": "master",
  "headRefOid": "abc1234567890",
  "isDraft": false,
  "mergeable": "MERGEABLE",
  "files": [
    {"path": "hub/pkg/middleware/tokenratelimit/config.go", "additions": 42, "deletions": 3},
    {"path": "hub/pkg/middleware/tokenratelimit/middleware.go", "additions": 80, "deletions": 5}
  ],
  "closingIssuesReferences": {"nodes": [{"number": 5678}]}
}
```

- [ ] **Step 2: Create the PR diff fixture**

`scripts/tests/fixtures/gh_pr_diff_hub_feat.patch`:

```diff
diff --git a/hub/pkg/middleware/tokenratelimit/config.go b/hub/pkg/middleware/tokenratelimit/config.go
index 1111111..2222222 100644
--- a/hub/pkg/middleware/tokenratelimit/config.go
+++ b/hub/pkg/middleware/tokenratelimit/config.go
@@ -1,5 +1,8 @@
 package tokenratelimit

 type Config struct {
+	OnDenyResponse *aiformat.DenyResponse `json:"onDenyResponse,omitempty"`
 }
```

- [ ] **Step 3: Write the failing test for single-PR fetch**

Append to `scripts/tests/test_fetch_pr.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch
from scripts.fetch_pr import fetch_single

FIXTURES = Path(__file__).parent / "fixtures"


class TestFetchSingle(unittest.TestCase):
    def test_fetch_single_returns_normalized_shape(self):
        view = json.loads((FIXTURES / "gh_pr_view_hub_feat.json").read_text())
        diff = (FIXTURES / "gh_pr_diff_hub_feat.patch").read_text()
        with patch("scripts.fetch_pr._gh.run_json", return_value=view), \
             patch("scripts.fetch_pr._gh.run_text", return_value=diff):
            result = fetch_single(PrRef("traefik/traefik-hub", 1234))
        self.assertEqual(result["number"], 1234)
        self.assertEqual(result["title"], view["title"])
        self.assertIn("Closes #5678", result["body"])
        self.assertEqual(result["base"], "master")
        self.assertFalse(result["diff_truncated"])
        self.assertEqual(len(result["files_changed"]), 2)
        self.assertEqual(result["files_changed"][0]["path"],
                         "hub/pkg/middleware/tokenratelimit/config.go")
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: FAIL — `fetch_single` not defined.

- [ ] **Step 5: Implement `fetch_single` in `scripts/fetch_pr.py`**

Add near the top of the file (after the dataclass):

```python
from scripts import _gh

DIFF_LINE_CAP = 2000


def fetch_single(ref: PrRef) -> dict:
    owner_repo = ref.repo
    view = _gh.run_json([
        "pr", "view", str(ref.number),
        "--repo", owner_repo,
        "--json",
        "number,title,body,labels,author,headRefName,baseRefName,headRefOid,"
        "isDraft,mergeable,files,closingIssuesReferences",
    ])
    diff_text = _gh.run_text(["pr", "diff", str(ref.number), "--repo", owner_repo, "--patch"])
    diff_lines = diff_text.splitlines()
    truncated = len(diff_lines) > DIFF_LINE_CAP
    diff_capped = "\n".join(diff_lines[:DIFF_LINE_CAP])

    return {
        "number": view["number"],
        "title": view["title"],
        "body": view.get("body") or "",
        "labels": [l["name"] for l in view.get("labels", [])],
        "author": (view.get("author") or {}).get("login", ""),
        "branch": view["headRefName"],
        "base": view["baseRefName"],
        "head": view["headRefOid"],
        "isDraft": view.get("isDraft", False),
        "mergeable": view.get("mergeable", "UNKNOWN"),
        "diff": diff_capped,
        "diff_truncated": truncated,
        "files_changed": [
            {"path": f["path"], "additions": f["additions"], "deletions": f["deletions"]}
            for f in view.get("files", [])
        ],
        "closingIssuesReferences": [
            n["number"] for n in (view.get("closingIssuesReferences") or {}).get("nodes", [])
        ],
    }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: 6 tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/fetch_pr.py scripts/tests/test_fetch_pr.py scripts/tests/fixtures/
git commit -m "feat: fetch single PR view + diff into normalized shape"
```

---

### Task 1.3: Resolve linked issues, sub-issues, and comments

**Files:**
- Modify: `scripts/fetch_pr.py`
- Modify: `scripts/tests/test_fetch_pr.py`
- Create: `scripts/tests/fixtures/gh_sub_issues.json`
- Create: `scripts/tests/fixtures/gh_issue_5678.json`

- [ ] **Step 1: Create sub-issues fixture**

`scripts/tests/fixtures/gh_sub_issues.json`:

```json
[
  {"number": 5681, "title": "Add config knob", "body": "Implementation detail."}
]
```

- [ ] **Step 2: Create issue fixture**

`scripts/tests/fixtures/gh_issue_5678.json`:

```json
{
  "number": 5678,
  "title": "Customizable deny response for guards",
  "body": "Agentic clients break on 403. We need configurable status + body.",
  "comments": [
    {"author": {"login": "alice"}, "body": "I have a draft of the YAML shape."},
    {"author": {"login": "dependabot[bot]"}, "body": "Bumping deps..."},
    {"author": {"login": "bob"}, "body": ""}
  ]
}
```

- [ ] **Step 3: Write the failing test**

Append to `scripts/tests/test_fetch_pr.py`:

```python
from scripts.fetch_pr import collect_issues, _BODY_LINK_RE


class TestCollectIssues(unittest.TestCase):
    def test_body_regex_finds_all_forms(self):
        body = "Closes #1\nfixes #2 and Resolves: #3"
        nums = sorted(int(m.group(1)) for m in _BODY_LINK_RE.finditer(body))
        self.assertEqual(nums, [1, 2, 3])

    def test_collect_issues_merges_closes_and_subissues(self):
        issue = json.loads((FIXTURES / "gh_issue_5678.json").read_text())
        subissues = json.loads((FIXTURES / "gh_sub_issues.json").read_text())

        def fake_json(args):
            if "sub_issues" in " ".join(args):
                return subissues
            return issue

        with patch("scripts.fetch_pr._gh.run_json", side_effect=fake_json):
            issues = collect_issues(
                repo="traefik/traefik-hub",
                pr_body="Closes #5678",
                closing_refs=[5678],
            )
        nums = {i["number"] for i in issues}
        self.assertEqual(nums, {5678, 5681})

    def test_comments_drop_bots_and_empty(self):
        issue = json.loads((FIXTURES / "gh_issue_5678.json").read_text())
        with patch("scripts.fetch_pr._gh.run_json", return_value=issue), \
             patch("scripts.fetch_pr._fetch_sub_issues", return_value=[]):
            issues = collect_issues(
                repo="traefik/traefik-hub", pr_body="", closing_refs=[5678]
            )
        authors = [c["author"] for c in issues[0]["comments"]]
        self.assertEqual(authors, ["alice"])
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: FAIL — `collect_issues` / `_BODY_LINK_RE` not defined.

- [ ] **Step 5: Implement issue + sub-issue collection**

Append to `scripts/fetch_pr.py`:

```python
_BODY_LINK_RE = re.compile(r"(?:Closes|Fixes|Resolves):?\s+#(\d+)", re.IGNORECASE)
_BOT_AUTHOR_RE = re.compile(r"\[bot\]$", re.IGNORECASE)


def _fetch_sub_issues(repo: str, issue_number: int) -> list[dict]:
    try:
        return _gh.run_json([
            "api", f"repos/{repo}/issues/{issue_number}/sub_issues",
        ])
    except _gh.GhError:
        return []  # endpoint not enabled for this repo


def _fetch_issue(repo: str, number: int) -> dict:
    return _gh.run_json([
        "issue", "view", str(number), "--repo", repo,
        "--json", "number,title,body,comments",
    ])


def collect_issues(repo: str, pr_body: str, closing_refs: list[int]) -> list[dict]:
    seen: set[int] = set()
    queue: list[int] = list(dict.fromkeys(closing_refs))
    for m in _BODY_LINK_RE.finditer(pr_body):
        n = int(m.group(1))
        if n not in queue:
            queue.append(n)

    out: list[dict] = []
    for num in queue:
        if num in seen:
            continue
        seen.add(num)
        raw = _fetch_issue(repo, num)
        comments = [
            {"author": (c.get("author") or {}).get("login", ""), "body": c.get("body", "")}
            for c in raw.get("comments", [])
            if c.get("body")
            and not _BOT_AUTHOR_RE.search((c.get("author") or {}).get("login", ""))
        ]
        out.append({
            "number": raw["number"],
            "title": raw["title"],
            "body": raw.get("body") or "",
            "comments": comments,
            "is_sub_issue": False,
        })
        for sub in _fetch_sub_issues(repo, num):
            if sub["number"] in seen:
                continue
            seen.add(sub["number"])
            out.append({
                "number": sub["number"],
                "title": sub.get("title", ""),
                "body": sub.get("body", ""),
                "comments": [],
                "is_sub_issue": True,
            })
    return out
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: 9 tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/fetch_pr.py scripts/tests/test_fetch_pr.py scripts/tests/fixtures/gh_sub_issues.json scripts/tests/fixtures/gh_issue_5678.json
git commit -m "feat: collect linked issues + one-level sub-issues, drop bot comments"
```

---

### Task 1.4: Aggregate multi-PR into merged view

**Files:**
- Modify: `scripts/fetch_pr.py`
- Modify: `scripts/tests/test_fetch_pr.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_fetch_pr.py`:

```python
from scripts.fetch_pr import merge_prs


class TestMergePrs(unittest.TestCase):
    def test_single_pr_primary_is_only_pr(self):
        prs = [{"number": 7, "files_changed": [{"path": "a.go", "additions": 3, "deletions": 0}],
                "title": "feat: A", "linked_issues": [], "sub_issues": []}]
        merged = merge_prs(prs)
        self.assertEqual(merged["primary_pr"], 7)
        self.assertEqual(merged["files_changed"][0]["path"], "a.go")

    def test_multi_pr_picks_largest_as_primary(self):
        prs = [
            {"number": 7, "files_changed": [{"path": "a.go", "additions": 3, "deletions": 0}],
             "title": "feat: A", "linked_issues": [], "sub_issues": []},
            {"number": 8, "files_changed": [{"path": "b.go", "additions": 50, "deletions": 0}],
             "title": "feat: B", "linked_issues": [], "sub_issues": []},
        ]
        merged = merge_prs(prs)
        self.assertEqual(merged["primary_pr"], 8)

    def test_files_changed_dedupes_by_path(self):
        prs = [
            {"number": 7, "files_changed": [{"path": "a.go", "additions": 3, "deletions": 0}],
             "title": "", "linked_issues": [], "sub_issues": []},
            {"number": 8, "files_changed": [{"path": "a.go", "additions": 5, "deletions": 1}],
             "title": "", "linked_issues": [], "sub_issues": []},
        ]
        merged = merge_prs(prs)
        paths = [f["path"] for f in merged["files_changed"]]
        self.assertEqual(paths, ["a.go"])
        # Sum additions when deduping
        self.assertEqual(merged["files_changed"][0]["additions"], 8)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: FAIL — `merge_prs` not defined.

- [ ] **Step 3: Implement `merge_prs`**

Append to `scripts/fetch_pr.py`:

```python
def merge_prs(prs: list[dict]) -> dict:
    if not prs:
        return {"files_changed": [], "linked_issues": [], "sub_issues": [],
                "primary_pr": None, "title_synthesis": ""}

    by_path: dict[str, dict] = {}
    for pr in prs:
        for f in pr.get("files_changed", []):
            entry = by_path.setdefault(
                f["path"], {"path": f["path"], "additions": 0, "deletions": 0}
            )
            entry["additions"] += f.get("additions", 0)
            entry["deletions"] += f.get("deletions", 0)

    seen_issue_nums: set[int] = set()
    linked_issues = []
    sub_issues = []
    for pr in prs:
        for iss in pr.get("linked_issues", []):
            if iss["number"] in seen_issue_nums:
                continue
            seen_issue_nums.add(iss["number"])
            (sub_issues if iss.get("is_sub_issue") else linked_issues).append(iss)

    primary = max(
        prs,
        key=lambda p: sum(f.get("additions", 0) for f in p.get("files_changed", [])),
    )

    return {
        "files_changed": list(by_path.values()),
        "linked_issues": linked_issues,
        "sub_issues": sub_issues,
        "primary_pr": primary["number"],
        "title_synthesis": " / ".join(p["title"] for p in prs),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_pr.py scripts/tests/test_fetch_pr.py
git commit -m "feat: aggregate multi-PR with deduped files and largest-as-primary"
```

---

### Task 1.5: Duplicate doc-PR detection

**Files:**
- Modify: `scripts/fetch_pr.py`
- Modify: `scripts/tests/test_fetch_pr.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_fetch_pr.py`:

```python
from scripts.fetch_pr import find_existing_doc_pr


class TestFindExistingDocPr(unittest.TestCase):
    def test_hub_returns_match(self):
        with patch("scripts.fetch_pr._gh.run_json",
                   return_value=[{"number": 999, "title": "docs: ...", "url": "..."}]):
            match = find_existing_doc_pr("traefik/traefik-hub", 1234)
        self.assertEqual(match["number"], 999)

    def test_hub_returns_none_when_empty(self):
        with patch("scripts.fetch_pr._gh.run_json", return_value=[]):
            match = find_existing_doc_pr("traefik/traefik-hub", 1234)
        self.assertIsNone(match)

    def test_oss_returns_none(self):
        # OSS does not file separate doc PRs — duplicate detection is the impl PR diff.
        match = find_existing_doc_pr("traefik/traefik", 1234)
        self.assertIsNone(match)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: FAIL.

- [ ] **Step 3: Implement `find_existing_doc_pr`**

Append to `scripts/fetch_pr.py`:

```python
def find_existing_doc_pr(impl_repo: str, pr_number: int) -> Optional[dict]:
    if impl_repo != "traefik/traefik-hub":
        return None
    short = impl_repo.split("/")[-1]
    results = _gh.run_json([
        "pr", "list", "--repo", "traefik/hub-doc",
        "--state", "open",
        "--search", f"{short}#{pr_number}",
        "--json", "number,title,url",
    ])
    return results[0] if results else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: 15 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_pr.py scripts/tests/test_fetch_pr.py
git commit -m "feat: detect existing doc PR in hub-doc for the same impl PR"
```

---

### Task 1.6: Wire up `main()` and the JSON envelope

**Files:**
- Modify: `scripts/fetch_pr.py`
- Modify: `scripts/tests/test_fetch_pr.py`

- [ ] **Step 1: Write the failing test for the envelope**

Append to `scripts/tests/test_fetch_pr.py`:

```python
from scripts.fetch_pr import build_bundle


class TestBuildBundle(unittest.TestCase):
    def test_envelope_shape(self):
        view = json.loads((FIXTURES / "gh_pr_view_hub_feat.json").read_text())
        diff = (FIXTURES / "gh_pr_diff_hub_feat.patch").read_text()
        issue = json.loads((FIXTURES / "gh_issue_5678.json").read_text())

        with patch("scripts.fetch_pr._gh.run_json") as mock_json, \
             patch("scripts.fetch_pr._gh.run_text", return_value=diff):
            def route(args):
                joined = " ".join(args)
                if "issues/" in joined and "sub_issues" in joined:
                    return []
                if "pr list" in joined or args[:2] == ["pr", "list"]:
                    return []
                if "issue view" in joined or args[:2] == ["issue", "view"]:
                    return issue
                return view
            mock_json.side_effect = route
            bundle = build_bundle([PrRef("traefik/traefik-hub", 1234)])
        self.assertEqual(bundle["impl_repo"], "traefik/traefik-hub")
        self.assertEqual(len(bundle["prs"]), 1)
        self.assertEqual(bundle["merged"]["primary_pr"], 1234)
        self.assertIsNone(bundle["existing_doc_pr"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: FAIL — `build_bundle` not defined.

- [ ] **Step 3: Implement `build_bundle` and complete `main`**

Replace the existing `main()` in `scripts/fetch_pr.py`:

```python
def build_bundle(refs: list[PrRef]) -> dict:
    impl_repo = refs[0].repo
    prs = []
    for ref in refs:
        pr = fetch_single(ref)
        pr["linked_issues"] = collect_issues(
            impl_repo, pr["body"], pr["closingIssuesReferences"]
        )
        pr["sub_issues"] = [i for i in pr["linked_issues"] if i.get("is_sub_issue")]
        pr["linked_issues"] = [i for i in pr["linked_issues"] if not i.get("is_sub_issue")]
        prs.append(pr)
    existing = find_existing_doc_pr(impl_repo, refs[0].number) if len(refs) == 1 else None
    return {
        "impl_repo": impl_repo,
        "prs": prs,
        "merged": merge_prs(prs),
        "existing_doc_pr": existing,
    }


def _cwd_remote() -> Optional[str]:
    from scripts import _git
    try:
        url = _git.run(".", ["config", "--get", "remote.origin.url"]).strip()
    except Exception:
        return None
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/\s]+?)(?:\.git)?$", url)
    return f"{m['owner']}/{m['name']}" if m else None


def main(argv: list[str]) -> int:
    import json as _json
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", action="append", default=[],
                        help="PR number or full URL; repeat for multi-PR")
    parser.add_argument("--repo", default=None,
                        help="Override owner/name; otherwise inferred from cwd remote")
    args = parser.parse_args(argv)
    cwd_remote = args.repo or _cwd_remote()
    refs = parse_pr_inputs(args.pr, cwd_remote)
    bundle = build_bundle(refs)
    print(_json.dumps(bundle, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_fetch_pr -v`
Expected: 16 tests pass.

- [ ] **Step 5: Smoke-test the CLI**

Run: `python3 -m scripts.fetch_pr --help`
Expected: argparse usage prints; exit code 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/fetch_pr.py scripts/tests/test_fetch_pr.py
git commit -m "feat: complete fetch_pr CLI with bundle envelope"
```

---

## Phase 2: `fetch_grounding.py` — pull from `traefik/reference`

### Task 2.1: Parse INDEX.md and match Go paths to concepts

**Files:**
- Create: `scripts/fetch_grounding.py`
- Create: `scripts/tests/test_fetch_grounding.py`
- Create: `scripts/tests/fixtures/reference_INDEX.md`
- Create: `scripts/tests/fixtures/reference_DOC_INDEX.json`

- [ ] **Step 1: Create the INDEX fixture**

`scripts/tests/fixtures/reference_INDEX.md`:

```markdown
# Traefik Reference

## OSS Concepts

### http.routers
- kind: router-http
- source: oss
- extracted_from:
  - pkg/config/dynamic/http_config.go#L85

## Hub Concepts

### hub.middleware.tokenratelimit
- kind: middleware-http
- source: hub
- extracted_from:
  - hub/pkg/middleware/tokenratelimit/config.go
```

- [ ] **Step 2: Create the DOC_INDEX fixture**

`scripts/tests/fixtures/reference_DOC_INDEX.json`:

```json
{
  "http.routers": {"narrative_doc": "traefik/reference/routing-configuration/http/routing/rules-and-priority.md", "source": "oss"},
  "hub.middleware.tokenratelimit": {"narrative_doc": "ai-gateway/middlewares/token-rate-limit.md", "source": "hub"}
}
```

- [ ] **Step 3: Write the failing test**

`scripts/tests/test_fetch_grounding.py`:

```python
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.fetch_grounding import (
    parse_index, concepts_for_paths, build_grounding,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseIndex(unittest.TestCase):
    def test_parse_index_extracts_entries(self):
        text = (FIXTURES / "reference_INDEX.md").read_text()
        entries = parse_index(text)
        ids = [e["id"] for e in entries]
        self.assertIn("http.routers", ids)
        self.assertIn("hub.middleware.tokenratelimit", ids)
        tr = next(e for e in entries if e["id"] == "hub.middleware.tokenratelimit")
        self.assertEqual(tr["source"], "hub")
        self.assertIn("hub/pkg/middleware/tokenratelimit/config.go", tr["extracted_from"])


class TestConceptsForPaths(unittest.TestCase):
    def test_matches_extracted_from_path(self):
        entries = parse_index((FIXTURES / "reference_INDEX.md").read_text())
        matches = concepts_for_paths(
            entries, ["hub/pkg/middleware/tokenratelimit/middleware.go",
                      "hub/pkg/middleware/tokenratelimit/config.go"]
        )
        self.assertEqual([m["id"] for m in matches], ["hub.middleware.tokenratelimit"])

    def test_no_matches_returns_empty(self):
        entries = parse_index((FIXTURES / "reference_INDEX.md").read_text())
        self.assertEqual(concepts_for_paths(entries, ["unrelated.go"]), [])


class TestBuildGrounding(unittest.TestCase):
    def test_envelope(self):
        index = (FIXTURES / "reference_INDEX.md").read_text()
        doc_index = json.loads((FIXTURES / "reference_DOC_INDEX.json").read_text())
        with patch("scripts.fetch_grounding._gh.run_text", return_value=index), \
             patch("scripts.fetch_grounding._gh.run_json", return_value=doc_index):
            g = build_grounding(["hub/pkg/middleware/tokenratelimit/config.go"])
        self.assertEqual(len(g["concepts"]), 1)
        self.assertEqual(g["concepts"][0]["narrative_doc"],
                         "ai-gateway/middlewares/token-rate-limit.md")
        self.assertEqual(g["llms_txt_url"], "https://doc.traefik.io/traefik-hub/llms.txt")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_fetch_grounding -v`
Expected: FAIL — module not defined.

- [ ] **Step 5: Implement `scripts/fetch_grounding.py`**

```python
"""fetch_grounding.py — load INDEX.md + DOC_INDEX.json from traefik/reference
and match concepts by Go source paths.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from scripts import _gh

REFERENCE_REPO = "traefik/reference"
INDEX_PATH = "INDEX.md"
DOC_INDEX_PATH = "DOC_INDEX.json"

_HEADER_RE = re.compile(r"^###\s+(?P<id>\S+)\s*$")
_FIELD_RE = re.compile(r"^-\s+(?P<key>\w+):\s*(?P<val>.+)$")
_BULLET_RE = re.compile(r"^\s+-\s+(?P<val>.+)$")


def parse_index(text: str) -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    in_extracted = False
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            if current:
                entries.append(current)
            current = {"id": m["id"], "extracted_from": []}
            in_extracted = False
            continue
        if current is None:
            continue
        m = _FIELD_RE.match(line)
        if m:
            key, val = m["key"], m["val"].strip()
            if key == "extracted_from":
                in_extracted = True
            else:
                current[key] = val
                in_extracted = False
            continue
        if in_extracted:
            m = _BULLET_RE.match(line)
            if m:
                # Strip line anchors like '#L85'
                p = m["val"].split("#", 1)[0].strip()
                current["extracted_from"].append(p)
    if current:
        entries.append(current)
    return entries


def concepts_for_paths(entries: list[dict], touched_paths: list[str]) -> list[dict]:
    touched = set(touched_paths)
    return [e for e in entries if any(p in touched for p in e.get("extracted_from", []))]


def _llms_txt_url_for(sources: set[str]) -> str:
    if "hub" in sources:
        return "https://doc.traefik.io/traefik-hub/llms.txt"
    if "oss" in sources:
        return "https://doc.traefik.io/traefik/llms.txt"
    return "https://doc.traefik.io/llms.txt"


def build_grounding(touched_paths: list[str]) -> dict:
    index_text = _gh.run_text([
        "api", f"repos/{REFERENCE_REPO}/contents/{INDEX_PATH}", "-H", "Accept: application/vnd.github.raw",
    ])
    entries = parse_index(index_text)
    matches = concepts_for_paths(entries, touched_paths)

    doc_index: dict = {}
    if matches:
        doc_index = _gh.run_json([
            "api", f"repos/{REFERENCE_REPO}/contents/{DOC_INDEX_PATH}",
            "--jq", ".content | @base64d | fromjson",
        ])

    enriched = []
    for m in matches:
        doc_entry = doc_index.get(m["id"], {})
        enriched.append({
            "id": m["id"],
            "kind": m.get("kind", ""),
            "source": m.get("source", ""),
            "extracted_from": m.get("extracted_from", []),
            "narrative_doc": doc_entry.get("narrative_doc"),
        })

    return {
        "concepts": enriched,
        "llms_txt_url": _llms_txt_url_for({c["source"] for c in enriched}),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--touched-files", nargs="+", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build_grounding(args.touched_files), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_fetch_grounding -v`
Expected: 4 tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/fetch_grounding.py scripts/tests/test_fetch_grounding.py scripts/tests/fixtures/reference_INDEX.md scripts/tests/fixtures/reference_DOC_INDEX.json
git commit -m "feat: parse traefik/reference INDEX.md and map Go paths to concepts"
```

---

## Phase 3: `classify.py` — heuristics

### Task 3.1: Feature-type classifier (from PR title prefix)

**Files:**
- Create: `scripts/classify.py`
- Create: `scripts/tests/test_classify.py`

- [ ] **Step 1: Write the failing test**

`scripts/tests/test_classify.py`:

```python
import unittest
from scripts.classify import feature_type


class TestFeatureType(unittest.TestCase):
    def test_feat_prefix(self):
        self.assertEqual(feature_type("feat: add X"), "feat")

    def test_fix_prefix(self):
        self.assertEqual(feature_type("fix(deps): bump"), "fix")

    def test_chore(self):
        self.assertEqual(feature_type("chore: lint"), "chore")

    def test_unknown(self):
        self.assertEqual(feature_type("Random text"), "other")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_classify -v`
Expected: FAIL — module not defined.

- [ ] **Step 3: Implement `feature_type`**

`scripts/classify.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_classify -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/classify.py scripts/tests/test_classify.py
git commit -m "feat: classify PR title prefix into feature_type"
```

---

### Task 3.2: Release-note heuristic (Hub-only)

**Files:**
- Modify: `scripts/classify.py`
- Modify: `scripts/tests/test_classify.py`

- [ ] **Step 1: Write the failing test (table-driven)**

Append to `scripts/tests/test_classify.py`:

```python
from scripts.classify import needs_release_note


class TestReleaseNote(unittest.TestCase):
    def _pr(self, title="", labels=None, body=""):
        return {"title": title, "labels": labels or [], "body": body}

    def test_oss_always_no(self):
        result = needs_release_note(self._pr(title="feat: add X"), impl_repo="traefik/traefik")
        self.assertEqual(result["verdict"], "no")
        self.assertIn("oss-short-circuit", result["signals"])

    def test_hub_feat_default_ea(self):
        result = needs_release_note(
            self._pr(title="feat: add X", labels=["feature"]),
            impl_repo="traefik/traefik-hub",
        )
        self.assertEqual(result["verdict"], "yes")
        self.assertEqual(result["proposed_shape"], "ea-subsection")

    def test_hub_ga_graduation_bullet(self):
        result = needs_release_note(
            self._pr(title="feat: X graduates to GA"),
            impl_repo="traefik/traefik-hub",
        )
        self.assertEqual(result["verdict"], "yes")
        self.assertEqual(result["proposed_shape"], "ga-bullet")

    def test_hub_breaking_label(self):
        result = needs_release_note(
            self._pr(title="feat: rename X", labels=["breaking-change"]),
            impl_repo="traefik/traefik-hub",
        )
        self.assertEqual(result["verdict"], "yes")
        self.assertEqual(result["proposed_shape"], "breaking-subsection")

    def test_hub_fix_no(self):
        result = needs_release_note(
            self._pr(title="fix: handle empty body"),
            impl_repo="traefik/traefik-hub",
        )
        self.assertEqual(result["verdict"], "no")

    def test_hub_chore_no(self):
        result = needs_release_note(
            self._pr(title="chore(deps): bump"),
            impl_repo="traefik/traefik-hub",
        )
        self.assertEqual(result["verdict"], "no")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_classify -v`
Expected: FAIL — `needs_release_note` not defined.

- [ ] **Step 3: Implement `needs_release_note`**

Append to `scripts/classify.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_classify -v`
Expected: 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/classify.py scripts/tests/test_classify.py
git commit -m "feat: classify release-note shape (Hub-only) with EA default"
```

---

### Task 3.3: Screenshot heuristic (neighbor-driven)

**Files:**
- Modify: `scripts/classify.py`
- Modify: `scripts/tests/test_classify.py`
- Create: `scripts/tests/fixtures/hub_doc_neighbor_middleware.md`
- Create: `scripts/tests/fixtures/hub_doc_neighbor_ui.mdx`

- [ ] **Step 1: Create neighbor fixtures**

`scripts/tests/fixtures/hub_doc_neighbor_middleware.md`:

```markdown
---
title: 'LLM Guard'
---

## Configuration

| Field | Type |
|---|---|
| name | string |

No screenshots here.
```

`scripts/tests/fixtures/hub_doc_neighbor_ui.mdx`:

```mdx
---
title: 'Dashboard'
---

<BrowserWindow url='https://hub.traefik.io/dashboard'>
![Dashboard](/img/admin/dashboard.png "Dashboard")
</BrowserWindow>

More UI here.
```

- [ ] **Step 2: Write the failing test**

Append to `scripts/tests/test_classify.py`:

```python
from scripts.classify import needs_screenshots
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


class TestScreenshots(unittest.TestCase):
    def test_ui_neighbors_yes(self):
        result = needs_screenshots(
            neighbor_paths=[str(FIXTURES / "hub_doc_neighbor_ui.mdx")] * 3
            + [str(FIXTURES / "hub_doc_neighbor_middleware.md")],
            touched_paths=["hub/dashboard/src/App.tsx"],
        )
        self.assertEqual(result["verdict"], "yes")

    def test_pure_reference_no(self):
        result = needs_screenshots(
            neighbor_paths=[str(FIXTURES / "hub_doc_neighbor_middleware.md")] * 4,
            touched_paths=["hub/pkg/middleware/tokenratelimit/config.go"],
        )
        self.assertEqual(result["verdict"], "no")

    def test_dashboard_code_strong_yes(self):
        # Even with no neighbors, touching dashboard code is a strong signal.
        result = needs_screenshots(
            neighbor_paths=[],
            touched_paths=["hub/dashboard/src/App.tsx"],
        )
        self.assertEqual(result["verdict"], "yes")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_classify -v`
Expected: FAIL — `needs_screenshots` not defined.

- [ ] **Step 4: Implement `needs_screenshots`**

Append to `scripts/classify.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_classify -v`
Expected: 13 tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/classify.py scripts/tests/test_classify.py scripts/tests/fixtures/hub_doc_neighbor_middleware.md scripts/tests/fixtures/hub_doc_neighbor_ui.mdx
git commit -m "feat: screenshot heuristic from neighbor pages and touched code"
```

---

### Task 3.4: User-guide vs. reference candidates

**Files:**
- Modify: `scripts/classify.py`
- Modify: `scripts/tests/test_classify.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_classify.py`:

```python
from scripts.classify import doc_kind_candidates


class TestDocKindCandidates(unittest.TestCase):
    def test_middleware_code_leans_reference(self):
        cands = doc_kind_candidates(
            title="feat: add onDenyResponse to token ratelimit middleware",
            touched_paths=["hub/pkg/middleware/tokenratelimit/config.go"],
            neighbor_paths=[],
        )
        top = cands[0]
        self.assertEqual(top["kind"], "reference")
        self.assertGreater(top["confidence"], 0.5)

    def test_dashboard_code_leans_user_guide(self):
        cands = doc_kind_candidates(
            title="feat: add quota panel",
            touched_paths=["hub/dashboard/src/QuotaPanel.tsx"],
            neighbor_paths=[],
        )
        self.assertEqual(cands[0]["kind"], "user-guide")

    def test_title_hint_guide(self):
        cands = doc_kind_candidates(
            title="feat: guide for setting up X",
            touched_paths=[],
            neighbor_paths=[],
        )
        self.assertEqual(cands[0]["kind"], "user-guide")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_classify -v`
Expected: FAIL.

- [ ] **Step 3: Implement `doc_kind_candidates`**

Append to `scripts/classify.py`:

```python
def doc_kind_candidates(
    *, title: str, touched_paths: list[str], neighbor_paths: list[str]
) -> list[dict]:
    title_l = title.lower()
    score_ref = 0.0
    score_guide = 0.0
    rationale_ref: list[str] = []
    rationale_guide: list[str] = []

    if any(p.startswith("hub/pkg/middleware/") or "/config.go" in p for p in touched_paths):
        score_ref += 0.6
        rationale_ref.append("touches config/middleware Go package")
    if any(p.startswith("hub/dashboard/") or p.startswith("hub/portal/") for p in touched_paths):
        score_guide += 0.6
        rationale_guide.append("touches UI code")
    if any(w in title_l for w in ("guide", "tutorial", "walkthrough", "setup")):
        score_guide += 0.4
        rationale_guide.append("title hints at guide")
    if "reference" in title_l or "crd" in title_l:
        score_ref += 0.4
        rationale_ref.append("title mentions reference/CRD")

    # Normalise to [0,1]
    total = max(score_ref + score_guide, 1.0)
    cands = [
        {"kind": "reference", "confidence": round(score_ref / total, 2),
         "rationale": "; ".join(rationale_ref) or "no signal"},
        {"kind": "user-guide", "confidence": round(score_guide / total, 2),
         "rationale": "; ".join(rationale_guide) or "no signal"},
    ]
    cands.sort(key=lambda c: c["confidence"], reverse=True)
    return cands
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_classify -v`
Expected: 16 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/classify.py scripts/tests/test_classify.py
git commit -m "feat: rank user-guide vs reference candidates by code+title signals"
```

---

### Task 3.5: Wire up `classify()` and CLI

**Files:**
- Modify: `scripts/classify.py`
- Modify: `scripts/tests/test_classify.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_classify.py`:

```python
from scripts.classify import classify


class TestClassify(unittest.TestCase):
    def test_envelope_combines_all_three(self):
        bundle = {
            "impl_repo": "traefik/traefik-hub",
            "prs": [{
                "title": "feat: add onDenyResponse to token ratelimit middleware",
                "labels": ["feature"],
                "body": "",
            }],
            "merged": {
                "files_changed": [
                    {"path": "hub/pkg/middleware/tokenratelimit/config.go"}
                ],
                "primary_pr": 1234,
            },
        }
        result = classify(bundle, grounding={"concepts": []}, neighbor_paths=[])
        self.assertEqual(result["feature_type"], "feat")
        self.assertEqual(result["needs_release_note"]["verdict"], "yes")
        self.assertEqual(result["needs_release_note"]["proposed_shape"], "ea-subsection")
        self.assertEqual(result["needs_screenshots"]["verdict"], "no")
        self.assertEqual(result["doc_kind_candidates"][0]["kind"], "reference")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_classify -v`
Expected: FAIL.

- [ ] **Step 3: Implement `classify` and CLI**

Append to `scripts/classify.py`:

```python
def classify(bundle: dict, *, grounding: dict, neighbor_paths: list[str]) -> dict:
    primary = next(
        (p for p in bundle["prs"] if p["number"] == bundle["merged"]["primary_pr"]),
        bundle["prs"][0],
    )
    touched = [f["path"] for f in bundle["merged"]["files_changed"]]
    return {
        "feature_type": feature_type(primary["title"]),
        "needs_release_note": needs_release_note(primary, impl_repo=bundle["impl_repo"]),
        "needs_screenshots": needs_screenshots(
            neighbor_paths=neighbor_paths, touched_paths=touched
        ),
        "doc_kind_candidates": doc_kind_candidates(
            title=primary["title"], touched_paths=touched, neighbor_paths=neighbor_paths
        ),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, help="path to pr-bundle.json")
    parser.add_argument("--grounding", required=True, help="path to grounding.json")
    parser.add_argument("--neighbor", action="append", default=[],
                        help="path to a neighbor doc file; repeat")
    args = parser.parse_args(argv)
    bundle = json.loads(Path(args.bundle).read_text())
    grounding = json.loads(Path(args.grounding).read_text())
    out = classify(bundle, grounding=grounding, neighbor_paths=args.neighbor)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_classify -v`
Expected: 17 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/classify.py scripts/tests/test_classify.py
git commit -m "feat: combine release-note + screenshot + kind into classify envelope"
```

---

## Phase 4: `locate_targets.py` — candidate paths + neighbors

### Task 4.1: Propose candidate file paths from chosen kind

**Files:**
- Create: `scripts/locate_targets.py`
- Create: `scripts/tests/test_locate_targets.py`

- [ ] **Step 1: Write the failing test**

`scripts/tests/test_locate_targets.py`:

```python
import unittest
from scripts.locate_targets import propose_paths


class TestProposePaths(unittest.TestCase):
    def test_hub_middleware_reference(self):
        cands = propose_paths(
            impl_repo="traefik/traefik-hub",
            doc_kind="reference",
            feature_slug="token-ratelimit-deny-response",
            touched_paths=["hub/pkg/middleware/tokenratelimit/config.go"],
        )
        paths = [c["path"] for c in cands]
        self.assertIn("docs/ai-gateway/middlewares/token-ratelimit-deny-response.md", paths)

    def test_hub_user_guide(self):
        cands = propose_paths(
            impl_repo="traefik/traefik-hub",
            doc_kind="user-guide",
            feature_slug="quota-panel",
            touched_paths=["hub/dashboard/src/QuotaPanel.tsx"],
        )
        self.assertTrue(any("guides" in c["path"] for c in cands))

    def test_oss_reference(self):
        cands = propose_paths(
            impl_repo="traefik/traefik",
            doc_kind="reference",
            feature_slug="encoded-characters-middleware",
            touched_paths=["pkg/middlewares/encodedcharacters/middleware.go"],
        )
        self.assertTrue(
            any(c["path"].startswith("docs/content/reference/") for c in cands)
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_locate_targets -v`
Expected: FAIL.

- [ ] **Step 3: Implement `propose_paths`**

`scripts/locate_targets.py`:

```python
"""locate_targets.py — propose candidate doc file paths and neighbor pages
for the LLM to mirror in tone/structure.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# A small static map of impl-repo Go-path prefixes → likely doc section.
_HUB_REF_MAP = {
    "hub/pkg/middleware/": ("docs/ai-gateway/middlewares/", "docs/api-gateway/reference/routing/http/middlewares/"),
    "hub/dashboard/":      ("docs/dashboard/",),
    "hub/portal/":         ("docs/portal/",),
}
_HUB_GUIDE_MAP = {
    "hub/dashboard/": ("docs/dashboard/guides/",),
    "hub/pkg/":       ("docs/ai-gateway/guides/", "docs/api-gateway/guides/"),
}
_OSS_REF_MAP = {
    "pkg/middlewares/": ("docs/content/reference/routing/http/middlewares/",),
    "pkg/provider/":    ("docs/content/reference/install-configuration/providers/",),
}


def _section_dirs(impl_repo: str, doc_kind: str, touched_paths: list[str]) -> list[str]:
    if impl_repo == "traefik/traefik-hub":
        m = _HUB_REF_MAP if doc_kind == "reference" else _HUB_GUIDE_MAP
    else:
        m = _OSS_REF_MAP
    dirs: list[str] = []
    for prefix, sections in m.items():
        if any(p.startswith(prefix) for p in touched_paths):
            dirs.extend(sections)
    # Generic fallback for Hub if nothing matched
    if not dirs and impl_repo == "traefik/traefik-hub":
        dirs = ["docs/ai-gateway/middlewares/"] if doc_kind == "reference" else ["docs/ai-gateway/guides/"]
    if not dirs and impl_repo == "traefik/traefik":
        dirs = ["docs/content/reference/"]
    return dirs


def propose_paths(*, impl_repo: str, doc_kind: str, feature_slug: str,
                  touched_paths: list[str]) -> list[dict]:
    section_dirs = _section_dirs(impl_repo, doc_kind, touched_paths)
    base = max(0.4, 1.0 / max(len(section_dirs), 1))
    out = []
    for i, d in enumerate(section_dirs):
        out.append({
            "path": f"{d}{feature_slug}.md",
            "confidence": round(base if i == 0 else base * 0.8, 2),
            "rationale": f"Inferred section dir {d} from touched paths",
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_locate_targets -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/locate_targets.py scripts/tests/test_locate_targets.py
git commit -m "feat: propose candidate doc paths from impl path + chosen kind"
```

---

### Task 4.2: Pick neighbor pages for the LLM to mirror

**Files:**
- Modify: `scripts/locate_targets.py`
- Modify: `scripts/tests/test_locate_targets.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_locate_targets.py`:

```python
import tempfile
from pathlib import Path
from scripts.locate_targets import select_neighbors


class TestSelectNeighbors(unittest.TestCase):
    def test_picks_up_to_five_md_files(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway/middlewares"
            d.mkdir(parents=True)
            for name in ("llm-guard.md", "token-rate-limit.md", "content-guard.md",
                         "parallel-llm-guard.md", "mcp.md", "extra.md"):
                (d / name).write_text("placeholder")
            picked = select_neighbors(
                doc_repo_root=td,
                target_path="docs/ai-gateway/middlewares/new-thing.md",
            )
        self.assertLessEqual(len(picked), 5)
        self.assertTrue(all(p.endswith(".md") for p in picked))

    def test_returns_empty_if_dir_missing(self):
        with tempfile.TemporaryDirectory() as td:
            picked = select_neighbors(
                doc_repo_root=td,
                target_path="docs/nope/x.md",
            )
        self.assertEqual(picked, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_locate_targets -v`
Expected: FAIL.

- [ ] **Step 3: Implement `select_neighbors`**

Append to `scripts/locate_targets.py`:

```python
def select_neighbors(*, doc_repo_root: str, target_path: str, limit: int = 5) -> list[str]:
    target_dir = Path(doc_repo_root) / Path(target_path).parent
    if not target_dir.is_dir():
        return []
    candidates = sorted(
        p for p in target_dir.iterdir()
        if p.is_file() and p.suffix in {".md", ".mdx"}
    )
    return [str(p.relative_to(doc_repo_root)) for p in candidates[:limit]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_locate_targets -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/locate_targets.py scripts/tests/test_locate_targets.py
git commit -m "feat: pick up to 5 neighbor pages in the target dir"
```

---

### Task 4.3: Find sidebars.js insertion point + CLI envelope

**Files:**
- Modify: `scripts/locate_targets.py`
- Modify: `scripts/tests/test_locate_targets.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_locate_targets.py`:

```python
from scripts.locate_targets import sidebar_insertion_point, build_locate


class TestSidebarInsertionPoint(unittest.TestCase):
    def test_finds_section_by_dir_prefix(self):
        sidebars_js = '''
const sidebars = {
  apiSidebar: [
    { type: "category", label: "AI Gateway", items: [
      "ai-gateway/middlewares/llm-guard",
      "ai-gateway/middlewares/content-guard",
    ]},
  ],
};
'''
        ins = sidebar_insertion_point(
            sidebars_js, target_path="docs/ai-gateway/middlewares/new-thing.md",
        )
        self.assertEqual(ins["after_id"], "ai-gateway/middlewares/content-guard")


class TestBuildLocate(unittest.TestCase):
    def test_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "docs/ai-gateway/middlewares").mkdir(parents=True)
            (Path(td) / "docs/ai-gateway/middlewares/llm-guard.md").write_text("x")
            (Path(td) / "sidebars.js").write_text(
                'const sidebars = { apiSidebar: ["ai-gateway/middlewares/llm-guard"] };'
            )
            out = build_locate(
                impl_repo="traefik/traefik-hub",
                doc_repo_root=td,
                doc_kind="reference",
                feature_slug="new-thing",
                touched_paths=["hub/pkg/middleware/newthing/config.go"],
            )
        self.assertTrue(out["candidates"][0]["path"].endswith("new-thing.md"))
        self.assertEqual(out["sidebar_insertion_point"]["file"], "sidebars.js")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_locate_targets -v`
Expected: FAIL.

- [ ] **Step 3: Implement and finish CLI**

Append to `scripts/locate_targets.py`:

```python
_SIDEBAR_ID_RE = re.compile(r'"([\w\-]+(?:/[\w\-]+)+)"')


def sidebar_insertion_point(sidebars_js: str, *, target_path: str) -> dict | None:
    # Convert e.g. "docs/ai-gateway/middlewares/new-thing.md" to id prefix
    # "ai-gateway/middlewares/" and find the last id in that section.
    rel = target_path.removeprefix("docs/").removesuffix(".md").removesuffix(".mdx")
    section_prefix = rel.rsplit("/", 1)[0] + "/"
    ids_in_section = [
        m.group(1) for m in _SIDEBAR_ID_RE.finditer(sidebars_js)
        if m.group(1).startswith(section_prefix)
    ]
    if not ids_in_section:
        return None
    return {"file": "sidebars.js", "after_id": ids_in_section[-1]}


def build_locate(*, impl_repo: str, doc_repo_root: str, doc_kind: str,
                 feature_slug: str, touched_paths: list[str]) -> dict:
    candidates = propose_paths(
        impl_repo=impl_repo, doc_kind=doc_kind,
        feature_slug=feature_slug, touched_paths=touched_paths,
    )
    target = candidates[0]["path"] if candidates else ""
    neighbors = select_neighbors(doc_repo_root=doc_repo_root, target_path=target)
    candidates[0]["neighbors"] = neighbors
    ins = None
    if impl_repo == "traefik/traefik-hub":
        sidebars = Path(doc_repo_root) / "sidebars.js"
        if sidebars.is_file():
            ins = sidebar_insertion_point(
                sidebars.read_text(), target_path=target
            )
    return {"candidates": candidates, "sidebar_insertion_point": ins}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--impl-repo", required=True)
    parser.add_argument("--doc-repo-root", required=True)
    parser.add_argument("--doc-kind", required=True, choices=["reference", "user-guide"])
    parser.add_argument("--feature-slug", required=True)
    parser.add_argument("--touched-files", nargs="+", required=True)
    args = parser.parse_args(argv)
    out = build_locate(
        impl_repo=args.impl_repo,
        doc_repo_root=args.doc_repo_root,
        doc_kind=args.doc_kind,
        feature_slug=args.feature_slug,
        touched_paths=args.touched_files,
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_locate_targets -v`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/locate_targets.py scripts/tests/test_locate_targets.py
git commit -m "feat: complete locate_targets with sidebar insertion point"
```

---

## Phase 5: Templates

### Task 5.1: Doc-page and PR-body templates

**Files:**
- Create: `templates/hub-page.md.tmpl`
- Create: `templates/oss-page.md.tmpl`
- Create: `templates/sidebar-entry.json.tmpl`
- Create: `templates/release-note-ea.mdx.tmpl`
- Create: `templates/release-note-ga-subsection.mdx.tmpl`
- Create: `templates/release-note-ga-bullet.mdx.tmpl`
- Create: `templates/release-note-breaking.mdx.tmpl`
- Create: `templates/pr-body.md.tmpl`

- [ ] **Step 1: Create `templates/hub-page.md.tmpl`**

```markdown
---
title: '{{title}}'
sidebar_label: '{{sidebar_label}}'
id: {{id}}
description: '{{description}}'
tags:
{{#each tags}}
- {{this}}
{{/each}}
toc_min_heading_level: 2
toc_max_heading_level: 4
---

## Overview

{{overview}}

## Configuration

{{configuration}}

## Examples

{{examples}}

## Reference

{{reference}}
```

- [ ] **Step 2: Create `templates/oss-page.md.tmpl`**

```markdown
---
title: "{{title}}"
description: "{{description}}"
---

# {{title}}

{{overview}}

## Configuration Example

```yaml tab="File (YAML)"
{{yaml_example}}
```

## Configuration Options

{{configuration}}
```

- [ ] **Step 3: Create `templates/sidebar-entry.json.tmpl`**

```json
{
  "type": "doc",
  "id": "{{id}}"
}
```

- [ ] **Step 4: Create `templates/release-note-ea.mdx.tmpl`**

```mdx
#### {{feature_name}}

:::warning Early Access
This feature is currently in early access.
:::

{{description}}

For configuration details and examples, see the [{{feature_name}}]({{relative_link}}) documentation.
```

- [ ] **Step 5: Create `templates/release-note-ga-subsection.mdx.tmpl`**

```mdx
#### {{feature_name}}

{{description}}

For configuration details, see the [{{feature_name}}]({{relative_link}}) documentation.
```

- [ ] **Step 6: Create `templates/release-note-ga-bullet.mdx.tmpl`**

```mdx
- **{{feature_name}}** is now generally available. See the [{{doc_title}}]({{relative_link}}) documentation.
```

- [ ] **Step 7: Create `templates/release-note-breaking.mdx.tmpl`**

```mdx
#### {{feature_name}} — Breaking Change

{{description}}

For migration details, see the [{{doc_title}}]({{relative_link}}) documentation.
```

- [ ] **Step 8: Create `templates/pr-body.md.tmpl`**

```markdown
## Source

{{source_lines}}

## Summary

{{summary}}

## Linked Issues

{{linked_issues}}

## Reviewer Checklist

- [ ] Doc reads cleanly to someone who hasn't seen the impl PR
- [ ] Config fields match `{{concept_id}}` in [traefik/reference](https://github.com/traefik/reference)
- [ ] Cross-links use relative paths consistent with neighbor pages
{{screenshot_checklist}}

---

_Generated by `ai-ws-hub-doc-pr-generator`. Drop the new page into an LLM via [llms.txt]({{llms_txt_url}})._
```

- [ ] **Step 9: Commit**

```bash
git add templates/
git commit -m "feat: add Hub/OSS page, sidebar, release-note, and PR-body templates"
```

---

## Phase 6: `preview.py` — write + diff + lint

### Task 6.1: Apply file edits to a working branch

**Files:**
- Create: `scripts/preview.py`
- Create: `scripts/tests/test_preview.py`

- [ ] **Step 1: Write the failing test**

`scripts/tests/test_preview.py`:

```python
import subprocess
import tempfile
import unittest
from pathlib import Path
from scripts.preview import apply_edits, FileEdit


def _init_git(d: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "--allow-empty", "-qm", "init"], cwd=d, check=True)


class TestApplyEdits(unittest.TestCase):
    def test_writes_new_file_and_returns_paths(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            edits = [FileEdit(path="docs/new.md", content="hello\n", mode="create")]
            written = apply_edits(repo_path=str(d), branch="docs/test", edits=edits)
            self.assertEqual(written, ["docs/new.md"])
            self.assertTrue((d / "docs/new.md").is_file())

    def test_updates_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            (d / "existing.md").write_text("old\n")
            subprocess.run(["git", "add", "existing.md"], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                            "commit", "-qm", "add"], cwd=d, check=True)
            edits = [FileEdit(path="existing.md", content="new\n", mode="overwrite")]
            apply_edits(repo_path=str(d), branch="docs/test", edits=edits)
            self.assertEqual((d / "existing.md").read_text(), "new\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_preview -v`
Expected: FAIL — module not defined.

- [ ] **Step 3: Implement `apply_edits`**

`scripts/preview.py`:

```python
"""preview.py — write generated files to a working branch, print diff, run linters."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from scripts import _git


@dataclass
class FileEdit:
    path: str
    content: str
    mode: Literal["create", "overwrite", "patch"] = "create"


def _checkout_branch(repo_path: str, branch: str) -> None:
    try:
        _git.run(repo_path, ["checkout", "-q", branch])
    except _git.GitError:
        _git.run(repo_path, ["checkout", "-q", "-b", branch])


def apply_edits(*, repo_path: str, branch: str, edits: list[FileEdit]) -> list[str]:
    _checkout_branch(repo_path, branch)
    written: list[str] = []
    for e in edits:
        dest = Path(repo_path) / e.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(e.content)
        written.append(e.path)
    return written


def git_diff(repo_path: str) -> str:
    return _git.run(repo_path, ["diff", "--no-color"])


def git_diff_stat(repo_path: str) -> str:
    return _git.run(repo_path, ["diff", "--stat", "--no-color"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_preview -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/preview.py scripts/tests/test_preview.py
git commit -m "feat: apply file edits to a working branch in preview.py"
```

---

### Task 6.2: Run linters for Hub and OSS

**Files:**
- Modify: `scripts/preview.py`
- Modify: `scripts/tests/test_preview.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_preview.py`:

```python
from unittest.mock import patch
from scripts.preview import run_linter, LintResult


class TestRunLinter(unittest.TestCase):
    def test_hub_invokes_yarn(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            result = run_linter(repo_path="/hub-doc", impl_repo="traefik/traefik-hub")
        self.assertIsInstance(result, LintResult)
        self.assertTrue(result.ok)
        first_call_args = mock_run.call_args_list[0][0][0]
        self.assertIn("yarn", first_call_args[0])

    def test_oss_invokes_mkdocs(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            result = run_linter(repo_path="/traefik", impl_repo="traefik/traefik")
        call_args = mock_run.call_args_list[0][0][0]
        self.assertIn("mkdocs", " ".join(call_args))

    def test_failure_captures_stderr(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "MD013 line too long"
            result = run_linter(repo_path="/hub-doc", impl_repo="traefik/traefik-hub")
        self.assertFalse(result.ok)
        self.assertIn("MD013", result.errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_preview -v`
Expected: FAIL.

- [ ] **Step 3: Implement `run_linter`**

Append to `scripts/preview.py`:

```python
@dataclass
class LintResult:
    ok: bool
    errors: str
    commands: list[str]


_HUB_LINT_COMMANDS = [["yarn", "docs:markdown"], ["yarn", "docs:alex"]]
_OSS_LINT_COMMANDS = [["mkdocs", "build", "--strict", "-d", "/tmp/.mkdocs-preview"]]


def run_linter(*, repo_path: str, impl_repo: str) -> LintResult:
    commands = _HUB_LINT_COMMANDS if impl_repo == "traefik/traefik-hub" else _OSS_LINT_COMMANDS
    all_errors: list[str] = []
    ran: list[str] = []
    for cmd in commands:
        ran.append(" ".join(cmd))
        proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            all_errors.append(f"$ {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")
    return LintResult(ok=not all_errors, errors="\n".join(all_errors), commands=ran)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--impl-repo", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--edits", required=True,
                        help="path to JSON file with [{path, content, mode}, ...]")
    args = parser.parse_args(argv)
    raw_edits = json.loads(Path(args.edits).read_text())
    edits = [FileEdit(**e) for e in raw_edits]
    written = apply_edits(repo_path=args.repo_path, branch=args.branch, edits=edits)
    stat = git_diff_stat(args.repo_path)
    diff = git_diff(args.repo_path)
    lint = run_linter(repo_path=args.repo_path, impl_repo=args.impl_repo)
    print(json.dumps({
        "written": written,
        "diff_stat": stat,
        "diff": diff,
        "lint_ok": lint.ok,
        "lint_errors": lint.errors,
        "lint_commands": lint.commands,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_preview -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/preview.py scripts/tests/test_preview.py
git commit -m "feat: run target-repo linter (yarn docs / mkdocs build --strict)"
```

---

## Phase 7: `open_pr.py` — push + draft PR (Hub) / commit (OSS)

### Task 7.1: Detect engineer's fork of hub-doc

**Files:**
- Create: `scripts/open_pr.py`
- Create: `scripts/tests/test_open_pr.py`

- [ ] **Step 1: Write the failing test**

`scripts/tests/test_open_pr.py`:

```python
import unittest
from unittest.mock import patch
from scripts.open_pr import detect_fork


class TestDetectFork(unittest.TestCase):
    def test_returns_fork_when_match(self):
        forks = [{"name": "hub-doc", "parent": {"nameWithOwner": "traefik/hub-doc"}}]
        with patch("scripts.open_pr._gh.run_json", return_value=forks), \
             patch("scripts.open_pr._gh.current_user_login", return_value="alice"):
            fork = detect_fork(upstream="traefik/hub-doc")
        self.assertEqual(fork, "alice/hub-doc")

    def test_returns_none_when_no_match(self):
        with patch("scripts.open_pr._gh.run_json", return_value=[]), \
             patch("scripts.open_pr._gh.current_user_login", return_value="alice"):
            fork = detect_fork(upstream="traefik/hub-doc")
        self.assertIsNone(fork)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_open_pr -v`
Expected: FAIL.

- [ ] **Step 3: Implement `detect_fork`**

`scripts/open_pr.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_open_pr -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/open_pr.py scripts/tests/test_open_pr.py
git commit -m "feat: detect engineer's hub-doc fork via gh repo list --fork"
```

---

### Task 7.2: Hub push + draft PR

**Files:**
- Modify: `scripts/open_pr.py`
- Modify: `scripts/tests/test_open_pr.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_open_pr.py`:

```python
from scripts.open_pr import open_hub_pr


class TestOpenHubPr(unittest.TestCase):
    def test_pushes_to_fork_and_calls_gh_pr_create(self):
        calls = []
        def fake_git_run(*a, **kw):
            calls.append(("git", a, kw))
            return ""
        def fake_gh_run_text(args):
            calls.append(("gh-text", args))
            return "https://github.com/traefik/hub-doc/pull/999"
        with patch("scripts.open_pr._git.run", side_effect=fake_git_run), \
             patch("scripts.open_pr._gh.run_text", side_effect=fake_gh_run_text):
            url = open_hub_pr(
                doc_repo_root="/hub-doc",
                fork="alice/hub-doc",
                branch="docs/x",
                title="docs: add X",
                body="...",
            )
        # First git call should be `git push <fork remote> <branch>:<branch>`.
        push_call = next(c for c in calls if c[0] == "git" and "push" in c[1][1])
        self.assertIn("alice/hub-doc", " ".join(push_call[1][1]) + " ".join(push_call[1][1]))
        self.assertEqual(url, "https://github.com/traefik/hub-doc/pull/999")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_open_pr -v`
Expected: FAIL.

- [ ] **Step 3: Implement `open_hub_pr`**

Append to `scripts/open_pr.py`:

```python
UPSTREAM_HUB_DOC = "traefik/hub-doc"


def open_hub_pr(*, doc_repo_root: str, fork: str, branch: str,
                title: str, body: str) -> str:
    fork_url = f"https://github.com/{fork}.git"
    # Add fork remote if missing; ignore failure if it already exists.
    try:
        _git.run(doc_repo_root, ["remote", "add", "fork", fork_url])
    except _git.GitError:
        _git.run(doc_repo_root, ["remote", "set-url", "fork", fork_url])
    _git.run(doc_repo_root, ["push", "-u", "fork", f"{branch}:{branch}"])
    url = _gh.run_text([
        "pr", "create",
        "--repo", UPSTREAM_HUB_DOC,
        "--base", "master",
        "--head", f"{fork.split('/')[0]}:{branch}",
        "--draft",
        "--title", title,
        "--body", body,
    ]).strip()
    return url
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_open_pr -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/open_pr.py scripts/tests/test_open_pr.py
git commit -m "feat: push to fork and open draft PR in hub-doc"
```

---

### Task 7.3: OSS commit-on-PR-branch (single and multi-PR)

**Files:**
- Modify: `scripts/open_pr.py`
- Modify: `scripts/tests/test_open_pr.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_open_pr.py`:

```python
from scripts.open_pr import commit_oss_docs


class TestCommitOssDocs(unittest.TestCase):
    def test_single_pr_commit_no_refs(self):
        with patch("scripts.open_pr._git.run") as g:
            commit_oss_docs(
                impl_repo_root="/traefik",
                title="add encoded characters middleware",
                doc_files=["docs/content/reference/x.md"],
                refs_other_prs=[],
            )
        commit_call = next(c for c in g.call_args_list if c[0][1][0] == "commit")
        cmd = " ".join(commit_call[0][1])
        self.assertIn("docs: add encoded characters middleware", cmd)
        self.assertNotIn("Refs:", cmd)

    def test_multi_pr_commit_has_refs(self):
        with patch("scripts.open_pr._git.run") as g:
            commit_oss_docs(
                impl_repo_root="/traefik",
                title="add encoded characters middleware",
                doc_files=["docs/content/reference/x.md"],
                refs_other_prs=[5678, 5680],
            )
        commit_call = next(c for c in g.call_args_list if c[0][1][0] == "commit")
        cmd = " ".join(commit_call[0][1])
        self.assertIn("Refs: traefik#5678, traefik#5680", cmd)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_open_pr -v`
Expected: FAIL.

- [ ] **Step 3: Implement `commit_oss_docs`**

Append to `scripts/open_pr.py`:

```python
def commit_oss_docs(*, impl_repo_root: str, title: str,
                    doc_files: list[str], refs_other_prs: list[int]) -> None:
    if doc_files:
        _git.run(impl_repo_root, ["add", *doc_files])
    msg_lines = [f"docs: {title}", ""]
    if refs_other_prs:
        msg_lines.append("Refs: " + ", ".join(f"traefik#{n}" for n in refs_other_prs))
        msg_lines.append("")
    msg_lines.append("Co-Authored-By: Claude <noreply@anthropic.com>")
    msg = "\n".join(msg_lines)
    _git.run(impl_repo_root, ["commit", "-m", msg])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_open_pr -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/open_pr.py scripts/tests/test_open_pr.py
git commit -m "feat: commit OSS docs with Refs trailer for multi-PR"
```

---

### Task 7.4: CLI envelope and push gate

**Files:**
- Modify: `scripts/open_pr.py`
- Modify: `scripts/tests/test_open_pr.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_open_pr.py`:

```python
from scripts.open_pr import branch_slug_from_title


class TestBranchSlug(unittest.TestCase):
    def test_strips_prefix_and_lowercases(self):
        self.assertEqual(
            branch_slug_from_title("feat: add onDenyResponse to ratelimit"),
            "docs/add-ondenyresponse-to-ratelimit",
        )

    def test_caps_length(self):
        title = "feat: " + "x" * 200
        slug = branch_slug_from_title(title)
        self.assertLessEqual(len(slug), 40 + len("docs/"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.tests.test_open_pr -v`
Expected: FAIL.

- [ ] **Step 3: Implement `branch_slug_from_title` and CLI**

Append to `scripts/open_pr.py`:

```python
import re

_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")


def branch_slug_from_title(title: str, *, prefix: str = "docs/") -> str:
    stripped = re.sub(r"^(feat|fix|chore|refactor|test|docs|style|perf|build|ci)(\([^)]+\))?:\s*", "", title, flags=re.IGNORECASE)
    slug = _NON_SLUG_RE.sub("-", stripped.lower()).strip("-")
    return prefix + slug[:40]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)

    hub = sub.add_parser("hub")
    hub.add_argument("--doc-repo-root", required=True)
    hub.add_argument("--branch", required=True)
    hub.add_argument("--title", required=True)
    hub.add_argument("--body-file", required=True)

    oss = sub.add_parser("oss")
    oss.add_argument("--impl-repo-root", required=True)
    oss.add_argument("--title", required=True)
    oss.add_argument("--doc-file", action="append", default=[])
    oss.add_argument("--ref-pr", type=int, action="append", default=[])

    args = parser.parse_args(argv)
    if args.mode == "hub":
        fork = detect_fork(upstream=UPSTREAM_HUB_DOC)
        if fork is None:
            print(json.dumps({"error": "no fork detected; manual fork required"}))
            return 2
        body = open(args.body_file).read()
        url = open_hub_pr(
            doc_repo_root=args.doc_repo_root,
            fork=fork, branch=args.branch,
            title=args.title, body=body,
        )
        print(json.dumps({"pr_url": url}))
        return 0
    else:
        commit_oss_docs(
            impl_repo_root=args.impl_repo_root,
            title=args.title,
            doc_files=args.doc_file,
            refs_other_prs=args.ref_pr,
        )
        print(json.dumps({"committed": True}))
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest scripts.tests.test_open_pr -v`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/open_pr.py scripts/tests/test_open_pr.py
git commit -m "feat: open_pr CLI with hub/oss subcommands and branch slug derivation"
```

---

## Phase 8: References (loaded on demand by SKILL.md)

### Task 8.1: Hub-doc conventions reference

**Files:**
- Create: `references/hub-doc-conventions.md`

- [ ] **Step 1: Write the file**

```markdown
# Hub-doc conventions

Cheat-sheet the LLM consults when generating pages for `traefik/hub-doc`.

## Engine

Docusaurus 3.9.x. Navigation in `sidebars.js`. Build with `yarn dev` (local), `yarn build` (prod).

## Front matter (required)

```yaml
---
title: 'Feature Name'
sidebar_label: 'Feature Name'
id: feature-id
description: 'One-sentence description for the page meta description.'
tags:
- Feature Area
- Sub-area
toc_min_heading_level: 2
toc_max_heading_level: 4
---
```

- `title`: page H1. Body **does not** repeat the title as `# H1`.
- `id`: matches the sidebars.js entry (e.g. `ai-gateway/middlewares/token-rate-limit`).
- `description`: under 160 chars; goes into `<meta name="description">`.

## Headings

H2 (`##`) for top-level sections (Overview, Configuration, Examples, Reference).
H3 (`###`) for sub-sections.
Never repeat the page title as an H1 in the body.

## Admonitions

```mdx
:::info ... :::
:::tip ... :::
:::warning ... :::    <!-- also used for ":::warning Early Access" -->
:::note ... :::
```

## Code blocks

````
```yaml showLineNumbers title="YAML"
...
```

```bash
$ kubectl apply -f ...
```
````

## Cross-links

Relative paths from the current file:

```markdown
[Token Rate Limit](../middlewares/token-rate-limit.md "Token Rate Limit")
```

## Screenshots

```mdx
<BrowserWindow url='https://hub.traefik.io/...'>
![Caption](/img/<feature>/<name>.png "Tooltip")
</BrowserWindow>
```

Images live under `/static/img/<feature>/`. Reference them as `/img/<feature>/...` (absolute).

## Linting

- `yarn docs:markdown` (markdownlint, MD013 line length 225)
- `yarn docs:alex` (inclusive language)
- `yarn build` (link integrity, only in CI; too slow for preview)

## Branch and PR

- Branch from `master` (not `main`)
- PR base: `master`
- Open as **draft** so screenshots can be added before review
- PR body must include `Source: traefik/traefik-hub#<N>` line
```

- [ ] **Step 2: Commit**

```bash
git add references/hub-doc-conventions.md
git commit -m "docs: add hub-doc conventions reference"
```

---

### Task 8.2: OSS-doc conventions reference

**Files:**
- Create: `references/oss-doc-conventions.md`

- [ ] **Step 1: Write the file**

```markdown
# OSS-doc conventions

For `traefik/traefik` (the proxy). Docs live in-repo at `docs/content/`.

## Engine

MkDocs (Material theme, `traefik-labs` fork). Build with `mkdocs build --strict`.

## Front matter

```yaml
---
title: "Page Title"
description: "SEO-friendly one-sentence description."
slug: optional-url-slug
---
```

## Headings

H1 (`# Title`) appears in the body. H2 for sections.

## Subtitle marker

```markdown
Listening for Incoming Connections/Requests
{: .subtitle }
```

## Code blocks with tabs

````
```yaml tab="File (YAML)"
...
```

```toml tab="File (TOML)"
...
```

```bash tab="CLI"
--entrypoints.web.address=:80
```
````

## Cross-links

Relative paths. Reference docs link to other reference docs by path:

```markdown
[See HTTP Routers](./reference/routing/http/routers.md)
```

## No release notes in this repo

OSS does not maintain `release-notes.mdx`. The skill must short-circuit release-note logic for `traefik/traefik` impl PRs.

## Branch and commit

- Engineer is already on the impl PR branch when the skill is invoked
- Add a new commit (do not `--amend`) with title `docs: <feature title>` and body trailers as needed
- Push to the existing PR branch (`git push origin <branch>`)
```

- [ ] **Step 2: Commit**

```bash
git add references/oss-doc-conventions.md
git commit -m "docs: add oss-doc conventions reference"
```

---

### Task 8.3: Heuristic catalogs

**Files:**
- Create: `references/screenshot-heuristics.md`
- Create: `references/release-note-heuristics.md`

- [ ] **Step 1: Write `references/screenshot-heuristics.md`**

```markdown
# Screenshot heuristics

The skill should insert screenshot placeholders when neighbor pages visualise UI.

## Inputs

- `neighbor_paths`: 3-5 files in the same target directory
- `touched_paths`: files changed in the impl PR

## Rules (first match wins)

1. Any `touched_paths` starts with `hub/dashboard/` or `hub/portal/` → **yes** (strong)
2. ≥50% of neighbor files contain `<BrowserWindow>` or `![...]( /img/ ...)` → **yes**
3. Target dir is `reference/`, `middlewares/`, or any pure API/CLI ref with no neighbor imagery → **no**
4. Mixed → **no** but insert a single `<!-- TODO(screenshot): consider this section -->` marker

## Placeholder shape

```mdx
<BrowserWindow url='https://hub.traefik.io/<surface>'>
<!-- TODO(screenshot): <caption>. Save to /static/img/<feature>/<name>.png -->
</BrowserWindow>
```

Add a matching PR-body checklist item: `- [ ] Capture screenshot for /img/<feature>/<name>.png — <caption>`.

The skill **never captures or modifies images**. Engineers replace placeholders before merging.
```

- [ ] **Step 2: Write `references/release-note-heuristics.md`**

```markdown
# Release-note heuristics (Hub-only)

OSS PRs always short-circuit to `needs_release_note=no`.

## Where the entry goes

Always `docs/api-gateway/release-notes.mdx`. The `docs/api-management/release-notes.md` file is a re-import shim — never patch it.

## Structure of the target file

```mdx
## <Month YYYY>

### What's New

#### Graduated to GA

- **Feature A** is now generally available. See [...](...).

#### Feature B

:::warning Early Access
This feature is currently in early access.
:::

Body...

For configuration details, see the [...](...) documentation.

#### Compatibility Matrix

| Component | Version |
```

## Shape selection

| Verdict | Shape | Template |
|---|---|---|
| EA feat (default for `feat:`) | `#### <Feature Name>` under "What's New" with `:::warning Early Access` admonition | `release-note-ea.mdx.tmpl` |
| GA feat | Same shape, no admonition | `release-note-ga-subsection.mdx.tmpl` |
| GA graduation (title/body says "graduates to GA") | Bullet appended to existing `#### Graduated to GA` | `release-note-ga-bullet.mdx.tmpl` |
| Breaking change | `#### Breaking Changes` subsection (new if absent — flag for engineer review) | `release-note-breaking.mdx.tmpl` |

## EA vs GA defaulting

Default to EA when "yes". Engineers flip to GA in the edit loop.

## Links

Use relative paths from `docs/api-gateway/` (e.g. `../api-management/api.md#anchor`). Matches the existing file convention even though there's a stale comment at the top saying "ALL LINKS … MUST BE COMPLETE URLS".
```

- [ ] **Step 3: Commit**

```bash
git add references/screenshot-heuristics.md references/release-note-heuristics.md
git commit -m "docs: add screenshot and release-note heuristic catalogs"
```

---

## Phase 9: `SKILL.md` orchestrator

### Task 9.1: Write SKILL.md

**Files:**
- Create: `SKILL.md`

- [ ] **Step 1: Write the file**

```markdown
---
name: hub-doc-pr-generator
description: Use when an engineer or tech writer wants to open a documentation PR in traefik/hub-doc (or amend a traefik/traefik PR with docs) from one or more implementation PRs. Invoke as `/hub-doc-pr-generator <pr-url|pr-number>...` or with no arg when checked out on the impl branch.
---

# hub-doc-pr-generator

Turns implementation PRs into draft documentation PRs.

## Routing

- `traefik/traefik-hub` → draft PR in `traefik/hub-doc` from the engineer's fork
- `traefik/traefik` → new commit appended to the impl PR branch (docs are in-repo for OSS)
- Anything else → refuse with `unsupported impl repo: <owner>/<name>`

For multi-PR aggregation: all PRs must be in the same impl repo. Cross-repo invocations are refused.

## Required environment

- `gh` CLI on PATH, authenticated (`gh auth status` succeeds)
- Local clones of `traefik/hub-doc` and/or `traefik/traefik` (the skill reads neighbor pages from disk; it doesn't fetch them via `gh api`)
- Python 3.11+

The skill expects clone roots at:
- `hub-doc`: `$HUB_DOC_PATH` env var, else `~/Developer/traefik-playground/hub-doc`
- `traefik`: `$TRAEFIK_PATH` env var, else `~/Developer/traefik-playground/traefik`

## Pipeline (the agent follows this checklist)

0. **Preflight.** Run `gh auth status` via Bash. If it fails, stop and tell the engineer to run `gh auth login`. Verify `$HUB_DOC_PATH` (or `$TRAEFIK_PATH` for OSS) points to a clean working tree — if dirty, ask the engineer to stash/commit before continuing.

1. **Parse inputs.** Resolve each argument to `{impl_repo, pr_number}`. Forms:
   - PR URL: `https://github.com/<owner>/<repo>/pull/<N>`
   - PR number: requires being inside the impl repo, or `--repo` flag
   - No-arg: auto-detect from current branch (`gh pr view --json number,headRepository`)
   Validate all PRs share the same `impl_repo`. If not, refuse.

2. **Fetch the PR bundle.**
   ```bash
   python3 -m scripts.fetch_pr --pr <N> [--pr <M> ...] > /tmp/bundle.json
   ```
   Inspect `existing_doc_pr`; if non-null, ask the engineer `[u]pdate / [n]ew / [a]bort` via `AskUserQuestion`.

3. **Fetch grounding.**
   ```bash
   python3 -m scripts.fetch_grounding --touched-files $(jq -r '.merged.files_changed[].path' /tmp/bundle.json) > /tmp/grounding.json
   ```

4. **Compute neighbor paths for classification** by scanning a likely candidate directory in the doc repo. The neighbor list is also reused in step 6.

5. **Classify.**
   ```bash
   python3 -m scripts.classify --bundle /tmp/bundle.json --grounding /tmp/grounding.json $(printf -- '--neighbor %s ' "${neighbors[@]}") > /tmp/classify.json
   ```

6. **Ask the engineer for the doc kind.** Show `doc_kind_candidates[0]` with its rationale via `AskUserQuestion`:
   - `[c]` confirm AI pick
   - `[s]` swap (pick the other candidate)
   - `[d]` you decide (pick higher confidence)
   - `[p]` custom path

7. **Locate targets.**
   ```bash
   python3 -m scripts.locate_targets \
     --impl-repo <repo> --doc-repo-root <path> --doc-kind <kind> \
     --feature-slug <slug> --touched-files ... > /tmp/locate.json
   ```
   Show the top candidate; confirm or accept a custom path.

8. **Generate.** This is the LLM step — no script. Read:
   - `/tmp/bundle.json` (the PR + issues + diff)
   - `/tmp/grounding.json` (concept fields)
   - `/tmp/classify.json` (release-note shape, screenshot verdict)
   - `/tmp/locate.json` (target path + neighbors)
   - Template files from `templates/` (Hub or OSS depending on impl repo)
   - For Hub: last ~150 lines of `docs/api-gateway/release-notes.mdx` (so you know the current month section)
   - Up to 3 neighbor pages in full (read with the Read tool)
   - `references/<convention>.md` files on demand

   Produce a JSON file `/tmp/edits.json` shaped:
   ```json
   [
     {"path": "docs/...", "content": "...", "mode": "create"},
     {"path": "sidebars.js", "content": "<full new file>", "mode": "overwrite"},
     {"path": "docs/api-gateway/release-notes.mdx", "content": "<full new file>", "mode": "overwrite"}
   ]
   ```
   For each release-note shape (see `references/release-note-heuristics.md`), pick the right template and instantiate it. **Skip release notes entirely for OSS impl repos.**

9. **Preview.**
   ```bash
   python3 -m scripts.preview \
     --repo-path <doc-repo> --impl-repo <impl-repo> --branch <branch> \
     --edits /tmp/edits.json > /tmp/preview.json
   ```
   Print the `diff_stat` and `diff` to the engineer. If `lint_ok` is false, surface `lint_errors` and force a re-prompt.

10. **Edit loop.** Use `AskUserQuestion`:
    - `[1] push`
    - `[2] re-prompt with notes` → engineer types feedback; regenerate affected files (step 8 again with the feedback in context); back to step 9
    - `[3] save and exit (no push)`

11. **Push.**
    - **Hub:**
      ```bash
      python3 -m scripts.open_pr hub --doc-repo-root <path> --branch <branch> \
        --title "docs: <feature title>" --body-file /tmp/pr-body.md
      ```
    - **OSS (single):**
      ```bash
      python3 -m scripts.open_pr oss --impl-repo-root <path> \
        --title "<feature title>" --doc-file docs/content/... [--doc-file ...]
      ```
    - **OSS (multi):** same as single, plus `--ref-pr <N>` for each non-primary PR. Ensure the primary PR's branch is checked out first via `gh pr checkout <primary>`.

## Confirmation gates

- Never push without explicit `y` from the engineer
- Never `--force` or `--force-with-lease`
- Never `git commit --amend`
- If `gh auth status` fails: stop with `gh auth login` instructions

## When to use the AskUserQuestion tool

Use it for: kind selection (step 6), candidate-path confirmation (step 7), edit-loop choices (step 10), push confirmation (step 11). Each renders a labelled option list instead of a free-form y/N.
```

- [ ] **Step 2: Commit**

```bash
git add SKILL.md
git commit -m "feat: add SKILL.md orchestrator checklist"
```

---

## Phase 10: Integration smoke test

### Task 10.1: Record a fixture from a real recent PR

**Files:**
- Create: `scripts/tests/fixtures/integration_pr_view.json`
- Create: `scripts/tests/fixtures/integration_pr_diff.patch`
- Create: `references/smoke-test.md`

- [ ] **Step 1: Identify a recent simple feat PR**

Run: `gh pr list --repo traefik/traefik-hub --state merged --limit 20 --json number,title --search "feat:"`
Pick a small PR (< 500 lines added) and note its number.

- [ ] **Step 2: Capture its data**

Run (substituting `<N>`):
```bash
gh pr view <N> --repo traefik/traefik-hub --json number,title,body,labels,author,headRefName,baseRefName,headRefOid,isDraft,mergeable,files,closingIssuesReferences \
  > scripts/tests/fixtures/integration_pr_view.json
gh pr diff <N> --repo traefik/traefik-hub --patch \
  > scripts/tests/fixtures/integration_pr_diff.patch
```

- [ ] **Step 3: Write `references/smoke-test.md`**

```markdown
# Smoke-test recipe

End-to-end check that the skill produces something sensible against a real recent PR.

## Prerequisites

- Local clones at `$HUB_DOC_PATH` (default `~/Developer/traefik-playground/hub-doc`) on a clean `master`.
- `gh` authenticated.

## Steps

1. Pick a recent merged `feat:` PR in `traefik/traefik-hub`: `gh pr list --repo traefik/traefik-hub --state merged --search "feat:" --limit 5`.
2. Run the skill: `/hub-doc-pr-generator https://github.com/traefik/traefik-hub/pull/<N>`.
3. At the kind question, pick the AI suggestion.
4. At the path question, accept the top candidate.
5. Preview prints a diff and lint result; lint should pass.
6. Choose `[3] save and exit (no push)`.
7. Inspect the generated branch in `$HUB_DOC_PATH`: `git -C $HUB_DOC_PATH log -1 --stat docs/<branch>`.
8. Compare against the actual merged doc PR for the same feature (if any).

## Expected results

- Page front matter matches neighbor pages
- `sidebars.js` patch is a small block under the right category
- Release-notes patch is in `docs/api-gateway/release-notes.mdx` only (never the api-management one)
- Lint passes
- For `fix:` or `chore:` PRs: no release-notes patch
```

- [ ] **Step 4: Commit**

```bash
git add scripts/tests/fixtures/integration_pr_view.json scripts/tests/fixtures/integration_pr_diff.patch references/smoke-test.md
git commit -m "test: add fixture from real PR and smoke-test recipe"
```

---

### Task 10.2: End-to-end fixture-driven test

**Files:**
- Create: `scripts/tests/test_integration.py`

- [ ] **Step 1: Write the test**

`scripts/tests/test_integration.py`:

```python
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.fetch_pr import build_bundle, PrRef

FIXTURES = Path(__file__).parent / "fixtures"


class TestEndToEnd(unittest.TestCase):
    """Replay a real PR through fetch_pr without touching the network."""

    def test_real_pr_normalizes_cleanly(self):
        view = json.loads((FIXTURES / "integration_pr_view.json").read_text())
        diff = (FIXTURES / "integration_pr_diff.patch").read_text()

        def fake_json(args):
            joined = " ".join(args)
            if "issue view" in joined or "issues/" in joined and "sub_issues" in joined:
                return []  # no sub-issues / issue-view in this minimal fixture
            if args[:2] == ["pr", "list"]:
                return []
            if args[:2] == ["pr", "view"]:
                return view
            if args[:2] == ["issue", "view"]:
                return {"number": 0, "title": "", "body": "", "comments": []}
            return view

        with patch("scripts.fetch_pr._gh.run_json", side_effect=fake_json), \
             patch("scripts.fetch_pr._gh.run_text", return_value=diff):
            bundle = build_bundle([PrRef("traefik/traefik-hub", view["number"])])

        self.assertEqual(bundle["impl_repo"], "traefik/traefik-hub")
        self.assertEqual(bundle["prs"][0]["number"], view["number"])
        self.assertIsInstance(bundle["prs"][0]["title"], str)
        self.assertTrue(bundle["merged"]["files_changed"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run all tests**

Run: `python3 -m unittest discover -s scripts/tests -v`
Expected: every test passes (40+ tests across all phases).

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/test_integration.py
git commit -m "test: end-to-end fixture-driven replay through fetch_pr"
```

---

## Phase 11: README + finalization

### Task 11.1: Write the README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the file**

````markdown
# ai-ws-hub-doc-pr-generator

A Claude Code skill that drafts documentation PRs from implementation PRs in `traefik/traefik-hub` (→ `traefik/hub-doc`) and `traefik/traefik` (→ in-repo `docs/content/`).

## Install

Clone into the place Claude Code auto-discovers skills:

```bash
mkdir -p ~/.claude/skills
git clone <this-repo-url> ~/.claude/skills/hub-doc-pr-generator
```

Set local-clone paths (the skill reads neighbor pages from disk):

```bash
export HUB_DOC_PATH=~/Developer/traefik-playground/hub-doc
export TRAEFIK_PATH=~/Developer/traefik-playground/traefik
```

Ensure `gh` is authenticated:

```bash
gh auth status   # or gh auth login
```

## Usage

In Claude Code, on the impl PR branch:

```
/hub-doc-pr-generator
```

Or with explicit PRs (multi-PR aggregation):

```
/hub-doc-pr-generator https://github.com/traefik/traefik-hub/pull/1234 1235
```

## Development

```bash
make test    # run unit tests
make lint    # pyflakes
```

See `spec.md` for the design rationale and `docs/superpowers/plans/2026-05-26-hub-doc-pr-generator.md` for the implementation plan.

## Layout

| Path | Purpose |
|---|---|
| `SKILL.md` | Orchestrator the LLM follows |
| `scripts/` | Deterministic Python helpers (Python stdlib only) |
| `templates/` | Markdown scaffolds the LLM fills in |
| `references/` | Convention catalogs loaded on demand |
| `spec.md` | Full design spec |
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with install + usage instructions"
```

---

### Task 11.2: Final test pass + lint

**Files:** none (verification only)

- [ ] **Step 1: Run all tests**

Run: `make test`
Expected: every test passes; exit code 0.

- [ ] **Step 2: Run pyflakes**

Run: `make lint`
Expected: no warnings (or only known/ignored ones).

- [ ] **Step 3: Run the CLI smoke checks**

Run:
```bash
python3 -m scripts.fetch_pr --help
python3 -m scripts.fetch_grounding --help
python3 -m scripts.classify --help
python3 -m scripts.locate_targets --help
python3 -m scripts.preview --help
python3 -m scripts.open_pr --help
```
Expected: each prints usage and exits 0.

- [ ] **Step 4: Verify SKILL.md discoverability**

The Claude Code CLI auto-discovers skills via `~/.claude/skills/<dir>/SKILL.md`. Confirm `SKILL.md` has valid frontmatter (`name:` and `description:`).

Run: `head -5 SKILL.md`
Expected: shows the `---` frontmatter block with `name: hub-doc-pr-generator` and a non-empty description.

- [ ] **Step 5: Tag the v1 milestone**

```bash
git tag -a v1.0.0-rc1 -m "initial scaffold complete; ready for live smoke test"
git log --oneline
```

---

## Self-review notes (for the implementer, not a task)

- Every step shows the actual code (no "implement appropriate X" placeholders).
- Helper scripts share `_gh.py` and `_git.py` to avoid duplicate plumbing.
- Tests use stdlib `unittest` only — no `pytest`, no `requests`, no `pyyaml`.
- Each phase ends with a commit; no phase leaves the tree mid-broken.
- The smoke-test fixture (`integration_pr_view.json`, `integration_pr_diff.patch`) is captured live in Task 10.1 so the fixture-driven test in Task 10.2 reflects real data.
- The OSS flow never patches release notes (enforced by short-circuit in `classify.py` Task 3.2 + verified in Task 10's smoke test).
- Multi-PR is supported in `fetch_pr.py` (Task 1.4), `classify.py` (via `merged.primary_pr` in Task 3.5), `locate_targets.py` (via `touched_paths` union), and `open_pr.py` (Task 7.3 `Refs:` trailer).
