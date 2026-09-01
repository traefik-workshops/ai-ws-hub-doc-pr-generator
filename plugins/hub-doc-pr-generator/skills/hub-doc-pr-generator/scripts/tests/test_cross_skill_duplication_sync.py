"""Guards against silent drift between the two skills' deliberately-copied
implementations.

release-notes-generator can't import hub-doc-pr-generator's modules at
runtime (each skill is invoked with `PYTHONPATH="${CLAUDE_SKILL_DIR}"` set to
its OWN directory -- see SKILL.md -- so there is no shared import path
between sibling skills without changing how skills are packaged/invoked).
Given that constraint, three non-trivial pieces of logic are copy-pasted
between the two skills instead of shared: the Python re-exec guard
(_discover.py), the interpreter-discovery helpers (setup.py), and the
table-truncation diff-scoping helper (preview.py's
_added_or_changed_line_indices). Each copy's own docstring already says so.

A bug fix applied to one copy and forgotten in the other would previously
have nothing to catch it. These tests compare the two copies' function
bodies by AST (ignoring whitespace/formatting, and the one line that's
allowed to differ: the skill-name log prefix string) so an un-mirrored
change fails CI immediately instead of silently shipping a fixed skill next
to a still-broken one.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

# this_file -> tests -> scripts -> hub-doc-pr-generator (skill dir) -> skills
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]

_LOG_PREFIX_RE = re.compile(r"\[(hub-doc-pr-generator|release-notes-generator)\]")


def _function_source(rel_path: str, func_name: str) -> str:
    """AST dump of a function's actual logic -- signature, control flow,
    calls, constants -- with its docstring stripped out. Docstrings are
    expected to differ (each copy's explains itself in its own words, often
    cross-referencing the other); the CODE is what must stay identical."""
    path = _PLUGIN_ROOT / rel_path
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body = body[1:]
            return "\n".join(ast.dump(stmt, annotate_fields=False) for stmt in body)
    raise AssertionError(f"{func_name} not found in {rel_path}")


def _module_source(rel_path: str) -> str:
    return (_PLUGIN_ROOT / rel_path).read_text()


def _normalize_log_prefix(dumped: str) -> str:
    """The only intentional difference between the two copies: which
    skill's name appears in a log message. Everything else must match."""
    return _LOG_PREFIX_RE.sub("[SKILL]", dumped)


class TestReexecSubsystemStaysInSync(unittest.TestCase):
    _HUB = "hub-doc-pr-generator/scripts/_discover.py"
    _RNG = "release-notes-generator/scripts/_discover.py"

    def _assert_functions_match(self, func_name: str) -> None:
        hub_src = _normalize_log_prefix(_function_source(self._HUB, func_name))
        rng_src = _normalize_log_prefix(_function_source(self._RNG, func_name))
        self.assertEqual(
            hub_src, rng_src,
            msg=f"{func_name}() has drifted between {self._HUB} and {self._RNG} -- "
                "a fix applied to one copy wasn't mirrored to the other.",
        )

    def test_reexec_target_matches(self):
        self._assert_functions_match("reexec_target")

    def test_reexec_argv_matches(self):
        self._assert_functions_match("_reexec_argv")

    def test_current_main_module_name_matches(self):
        self._assert_functions_match("_current_main_module_name")

    def test_maybe_reexec_matches(self):
        self._assert_functions_match("maybe_reexec")

    def test_min_python_constant_matches(self):
        hub_src = _module_source(self._HUB)
        rng_src = _module_source(self._RNG)
        hub_const = re.search(r"^MIN_PYTHON\s*=.*$", hub_src, re.MULTILINE).group()
        rng_const = re.search(r"^MIN_PYTHON\s*=.*$", rng_src, re.MULTILINE).group()
        self.assertEqual(hub_const, rng_const)


class TestPythonDiscoveryStaysInSync(unittest.TestCase):
    _HUB = "hub-doc-pr-generator/scripts/setup.py"
    _RNG = "release-notes-generator/scripts/setup.py"

    def _assert_functions_match(self, func_name: str) -> None:
        hub_src = _function_source(self._HUB, func_name)
        rng_src = _function_source(self._RNG, func_name)
        self.assertEqual(
            hub_src, rng_src,
            msg=f"{func_name}() has drifted between {self._HUB} and {self._RNG}.",
        )

    def test_python_version_at_matches(self):
        self._assert_functions_match("python_version_at")

    def test_find_compatible_python_matches(self):
        self._assert_functions_match("find_compatible_python")

    def test_candidate_search_paths_match(self):
        hub_src = _module_source(self._HUB)
        rng_src = _module_source(self._RNG)
        for const in ("_PYTHON_CANDIDATE_NAMES", "_PYTHON_CANDIDATE_ABS_PATHS"):
            hub_block = re.search(rf"^{const}\s*=.*?(?=\n\S|\Z)", hub_src, re.MULTILINE | re.DOTALL).group()
            rng_block = re.search(rf"^{const}\s*=.*?(?=\n\S|\Z)", rng_src, re.MULTILINE | re.DOTALL).group()
            self.assertEqual(hub_block, rng_block, msg=f"{const} has drifted")


class TestTableDiffHelperStaysInSync(unittest.TestCase):
    _HUB = "hub-doc-pr-generator/scripts/preview.py"
    _RNG = "release-notes-generator/scripts/preview.py"

    def test_added_or_changed_line_indices_matches(self):
        hub_src = _function_source(self._HUB, "_added_or_changed_line_indices")
        rng_src = _function_source(self._RNG, "_added_or_changed_line_indices")
        self.assertEqual(
            hub_src, rng_src,
            msg="_added_or_changed_line_indices() has drifted between the two "
                "skills' preview.py -- this is the exact helper behind the "
                "traefik-hub#1435 finding #5 false-positive fix; a fix to one "
                "copy that isn't mirrored to the other can reintroduce that bug "
                "in the unmirrored skill.",
        )


if __name__ == "__main__":
    unittest.main()
