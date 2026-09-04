"""assign_target_version.py — rewrite one fragment's target_version in place.

Used by `cut` mode step 2 (see SKILL.md) after the writer confirms which
`unassigned` fragments belong to the release being cut. Pulled out of inline
SKILL.md prose (a `python3 -c` one-liner previously did a literal
`.replace('target_version: unassigned', ...)`) because that literal-string
match silently no-ops on any front-matter form it doesn't expect byte-for-byte
-- verified live: a fragment written as `target_version: "unassigned"` (quoted,
which collect_fragments.parse_fragment already tolerates when reading a
fragment back) left the string completely unchanged, no error, permanently
stranding that fragment as unassigned with zero visible failure. A real,
tested function can raise loudly instead of silently doing nothing.

Usage:
  python -m scripts.assign_target_version --fragment <path> --version <version>
Exits non-zero (with a clear message) if the fragment has no unassigned
target_version line to replace -- never silently no-ops.
"""
from __future__ import annotations
import argparse
import os
import re
import sys
from pathlib import Path

from scripts import _discover, _git
from scripts._frontmatter import (
    UNASSIGNED_TARGET_VERSION_RE,
    detect_newline,
    join_front_matter,
    split_front_matter,
)


def assign(content: str, version: str) -> str:
    """Replace the fragment's `target_version: unassigned` line (bare or
    quoted) with `target_version: <version>` (always written unquoted, matching
    templates/release-note-fragment.mdx.tmpl's convention). Raises ValueError
    if no such line is found -- never returns `content` unchanged.

    Also raises if MORE than one such line is found, rather than quietly fixing
    just the first: a well-formed fragment has exactly one `target_version:`
    key, so two is itself malformed front matter (a bad hand-edit or merge),
    not something to guess a "right one" for. Confirmed live that silently
    replacing only the first left the fragment still parsing back as
    `unassigned` (parse_fragment's dict-assignment walk takes the LAST
    occurrence), while this function had already reported success.

    The search is scoped to the front-matter block only, not the whole file --
    confirmed live that scanning the whole content let a coincidental match in
    the fragment's own BODY prose (e.g. documentation text that happens to
    contain the literal string "target_version: unassigned") count as a second
    "duplicate key", permanently blocking assignment with a false "malformed
    front matter" error even though the front matter itself was perfectly
    well-formed.

    Preserves the fragment's original line-ending style throughout (PR #32
    review finding 1). split_front_matter already keeps whatever `\\r\\n` or
    `\\n` the original fm/body used, but that guarantee is only as good as
    what this function does with it: the delimiter lines rebuilt by
    join_front_matter must use the SAME line ending as the rest of the file
    (detect_newline reads it off the file's own first line, not a hardcoded
    `\\n`), and the one line actually being rewritten must keep its own
    trailing `\\r` too -- confirmed live that a naive fix of only the
    delimiters still left a CRLF fragment's rewritten line as bare `\\n`
    (UNASSIGNED_TARGET_VERSION_RE's `\\s*$` swallows the `\\r` into the match,
    so it never survives into the replacement unless put back explicitly),
    producing the exact mixed-line-ending write-back diff this CRLF-tolerance
    work exists to avoid. The newline detection and delimiter reconstruction
    themselves live in the shared _frontmatter module (join_front_matter/
    detect_newline), not as a private expression here, so a future
    front-matter rewriter doesn't have to reinvent this trick."""
    try:
        fm_text, body = split_front_matter(content)
    except ValueError:
        raise ValueError("fragment has no '---' front matter block")

    matches = list(UNASSIGNED_TARGET_VERSION_RE.finditer(fm_text))
    if not matches:
        raise ValueError(
            "no 'target_version: unassigned' line found in this fragment's front matter "
            "-- it may already be assigned, or its front matter doesn't match the expected shape"
        )
    if len(matches) > 1:
        raise ValueError(
            f"found {len(matches)} 'target_version: unassigned' lines in this fragment's front "
            "matter -- that's a duplicate key and needs a human to fix it by hand before it can "
            "be assigned a version"
        )

    def _replacement(m: re.Match[str]) -> str:
        # A callable replacement, not an f-string passed straight to `sub`'s
        # `repl` argument -- re.sub treats a STRING repl's backslash-digit
        # sequences (\1, \g<name>, ...) as backreferences, so a version
        # containing one (a plausible typo, e.g. an accidentally-pasted regex
        # fragment) would raise a raw `re.error: invalid group reference`
        # instead of this module's documented clean non-zero exit. A
        # callable's return value is inserted literally -- no backreference
        # processing. `\s*$` in the pattern swallows a trailing `\r` (CRLF)
        # into the match, so it has to be put back here or the rewritten
        # line loses its `\r` while every other line in the file keeps it.
        trailing_cr = "\r" if m.group(0).endswith("\r") else ""
        return f"target_version: {version}{trailing_cr}"

    new_fm = UNASSIGNED_TARGET_VERSION_RE.sub(_replacement, fm_text, count=1)
    return join_front_matter(new_fm, body, detect_newline(content))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fragment", required=True, help="path to the fragment file to rewrite")
    parser.add_argument("--version", required=True, help="the confirmed target_version to assign")
    parser.add_argument(
        "--doc-repo-root",
        help="path to the hub-doc clone this fragment lives in -- if given, `git add`s the "
             "rewritten fragment there so the reassignment rides along with whatever this cut "
             "eventually commits, instead of staying an uncommitted, easy-to-lose local edit "
             "(cutmode audit finding F: a re-cut of the same still-open version from a "
             "different or fresh clone previously saw this fragment as still `unassigned`, "
             "since nothing in the pipeline ever committed the reassignment). Omit for a "
             "fragment that isn't inside a git repo (e.g. in tests).",
    )
    parser.add_argument(
        "--branch",
        help="the release branch this cut is building (same value passed to preview.py's "
             "--branch). If given alongside --doc-repo-root, checks out this branch in the doc "
             "repo -- creating it fresh from origin/main if it doesn't exist locally yet, via "
             "the same checkout_branch() preview.py itself uses -- BEFORE staging the "
             "reassignment there (PR #32 review round 4, finding 6). Without this, the "
             "reassignment stages on whatever branch --doc-repo-root already happened to be on; "
             "if that isn't the release branch (main, or a stale branch left by other work) and "
             "preview.py's own later checkout of the release branch then fails (e.g. a diverged "
             "branch refusing to be overwritten), the reassignment is left staged somewhere that "
             "was never going to be committed anywhere real. Omit only when there's no release "
             "branch yet to check out (e.g. reassigning a fragment outside the cut pipeline).",
    )
    args = parser.parse_args(argv)
    path = Path(args.fragment)

    # Validate --doc-repo-root and compute rel_path BEFORE writing anything --
    # PR #32 review finding 8: the original fix wrote the fragment's new
    # target_version to disk first and only attempted staging afterward, so a
    # bad --doc-repo-root (not a git repo, or a fragment that isn't actually
    # inside it) left the fragment rewritten-but-unstaged: a broken,
    # re-run-unsafe state, since the unassigned sentinel is already gone and
    # a re-run of this command will just fail with "no unassigned line
    # found". Catching the likely failure classes here, before the write,
    # means those two mistakes leave the fragment completely untouched.
    # --doc-repo-root and --branch are optional (a fragment outside any repo,
    # e.g. in a test, has neither), but SKILL.md's cut-mode step 2 says to
    # "always pass both" -- that instruction was prose-only, the exact
    # pattern this PR's own docstrings criticize elsewhere (PR #32 review
    # round 5, finding 1): omitting either flag left the reassignment
    # written-but-uncommitted (or committed to the wrong branch) with NO
    # visible difference in this command's output from the safe case. Warn
    # loudly on stderr whenever either is skipped, so a copy-pasted older
    # command or a forgotten flag doesn't silently reopen finding F.
    if not args.doc_repo_root:
        print(
            f"{args.fragment}: WARNING: no --doc-repo-root given -- the rewritten "
            "target_version will NOT be committed anywhere; it stays a local, uncommitted "
            "edit that a later re-cut of this version (from this clone or a fresh one) will "
            "not see, silently reopening cutmode audit finding F for this fragment. Pass "
            "--doc-repo-root (and --branch) unless this fragment genuinely isn't inside a "
            "git repo (e.g. a test fixture).",
            file=sys.stderr,
        )
    elif not args.branch:
        print(
            f"{args.fragment}: WARNING: --doc-repo-root given without --branch -- staging on "
            "whatever branch the doc repo currently has checked out, which may not be the "
            "release branch this cut is building. Pass --branch to check out the exact "
            "release branch before staging.",
            file=sys.stderr,
        )

    rel_path: str | None = None
    if args.doc_repo_root:
        repo_root = Path(args.doc_repo_root)
        if not (repo_root / ".git").exists():
            print(f"{args.fragment}: --doc-repo-root {args.doc_repo_root!r} has no .git -- "
                  "not a git repo. Refusing to touch the fragment until this is fixed.",
                  file=sys.stderr)
            return 1
        rel_path = os.path.relpath(path.resolve(), repo_root.resolve())
        if rel_path.startswith(".."):
            print(f"{args.fragment}: is not inside --doc-repo-root {args.doc_repo_root!r} "
                  f"(computed relative path {rel_path!r}). Refusing to touch the fragment "
                  "until this is fixed.", file=sys.stderr)
            return 1
        if args.branch:
            # Same "validate/act before writing" ordering as the checks
            # above -- a failed checkout must leave the fragment untouched,
            # not rewritten-but-on-the-wrong-branch.
            from scripts.preview import checkout_branch
            try:
                checkout_branch(args.doc_repo_root, args.branch)
            except _git.GitError as e:
                print(f"{args.fragment}: failed to check out branch {args.branch!r} in "
                      f"{args.doc_repo_root!r}: {e}. Refusing to touch the fragment until this "
                      "is fixed.", file=sys.stderr)
                return 1

    try:
        # newline="" on BOTH read and write, not Path.read_text()/write_text()'s
        # defaults (PR #32 review round 4, finding 2): Path.read_text() with
        # the default newline=None applies Python's universal-newline
        # translation, silently converting every \r\n to \n BEFORE assign()
        # ever sees the content -- confirmed live, this defeated the whole
        # CRLF-preservation fix above in the one code path that matters (the
        # CLI is what actually rewrites fragments on disk; the regression
        # test for that fix calls assign() directly with an in-memory string,
        # which never exercised this). newline="" on write likewise stops
        # write_text() from re-translating the \n's assign() already paired
        # with \r back into the platform default.
        with open(path, encoding="utf-8", newline="") as f:
            content = f.read()
        new_content = assign(content, args.version)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_content)
    except ValueError as e:
        print(f"{args.fragment}: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        # Distinct from the ValueError branch above (PR #32 review round 5,
        # finding 2): if --branch just checked out an EXISTING local branch
        # that doesn't happen to contain this fragment yet (a stale branch
        # left over from other work on a shared clone -- checkout_branch()
        # only fetches/branches from origin/main when the branch doesn't
        # exist locally, an already-existing branch is left exactly as-is),
        # the checkout can silently remove the fragment from the working
        # tree before this open() ever runs. That used to surface as a raw,
        # uncaught FileNotFoundError traceback instead of this module's
        # documented clean non-zero exit with a "Refusing to touch..."
        # message every other validated failure here produces.
        hint = (
            f" --branch {args.branch!r} was checked out just before this -- if that's an "
            "existing local branch that predates this fragment's merge, checking it out "
            "would have removed the file from the working tree. Check out a branch that "
            "actually contains this fragment, or omit --branch to stay on the current one."
            if args.doc_repo_root and args.branch else ""
        )
        print(f"{args.fragment}: could not read/write the fragment file: {e}.{hint}", file=sys.stderr)
        return 1

    if rel_path is not None:
        try:
            _git.run(args.doc_repo_root, ["add", "--", rel_path])
        except _git.GitError as e:
            # The write already happened and can't be undone here without
            # its own risk of clobbering a concurrent change -- give the
            # operator the exact recovery command instead of a bare "failed
            # to stage" message that leaves the next step a mystery. Do NOT
            # re-run this command: the unassigned sentinel is already gone,
            # so a re-run would just fail with "no unassigned line found".
            print(
                f"{args.fragment}: rewrote target_version -> {args.version} on disk, but failed "
                f"to stage it in {args.doc_repo_root!r}: {e}\n"
                f"Fix the git issue, then run `git -C {args.doc_repo_root} add -- {rel_path}` "
                "manually -- don't re-run this command.",
                file=sys.stderr,
            )
            return 1
    # The confirmation line states whether staging actually happened (PR #32
    # review round 5, finding 1) instead of the same text either way -- an
    # operator skimming output for confirmation shouldn't have to infer
    # staging status from the presence or absence of a WARNING line above.
    status = f"staged in {args.doc_repo_root!r}" if rel_path is not None else "NOT staged (no --doc-repo-root given)"
    print(f"{args.fragment}: target_version -> {args.version} ({status})")
    return 0


if __name__ == "__main__":
    _discover.maybe_reexec()
    sys.exit(main(sys.argv[1:]))
