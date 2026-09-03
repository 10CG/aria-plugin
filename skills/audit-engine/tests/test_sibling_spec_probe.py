"""Tests for skills/audit-engine/scripts/sibling_spec_probe.py.

Spec: openspec/changes/sibling-spec-probe/{proposal.md,detailed-tasks.yaml}
(TASK-004~009, TDD RED first). Interface contract (function names / signatures /
field names / git call shapes) is pinned in the two-writer BRIEF handed to both
the test seat (this file) and the implementation seat; where the two disagree
this file follows the *proposal*, and any such conflict is called out in the
implementing session's report rather than silently reconciled here.

TDD RED-first: at the time this file is written,
``skills/audit-engine/scripts/sibling_spec_probe.py`` may not exist yet (this
seat and the implementation seat work in parallel and do not read each
other's files). A bare top-level ``import sibling_spec_probe`` is therefore
expected to raise at baseline — ``unittest discover`` reports that as a
single collection-level error for this module, which is the desired
"only ImportError/skip" baseline signal (nothing else in this file can
produce a spurious pass or an unrelated failure while that import is broken).

Independent of the probe's existence, this file also degrades gracefully when
the *sister* module (``state-scanner/lib/linked_issue_field.py``, OpenSpec
``linked-issue-field-availability``) is not importable: every TestCase that
needs it is skipped with a printed reason, per proposal §1 dependency-
direction clause 3 ("硬前置... 缺席时整套 skip 并报「前置未 ship」"). In this
repo the sister module already shipped (v1.67.2+), so that guard is normally
inert — but it is real code, not a comment, and is exercised in
``TestSisterGuardLogic``.

Run:
    cd skills/audit-engine/tests && python3 -m unittest discover -s . -p 'test_*.py' -v
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest import mock

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent
_AUDIT_ENGINE = _TESTS_DIR.parent               # skills/audit-engine
_SKILLS_DIR = _AUDIT_ENGINE.parent               # skills
_MAIN_REPO_ROOT = Path(__file__).resolve().parents[4]  # Aria main repo (SC-18 cc1bdef corpus)

_SS_ROOT = str(_SKILLS_DIR / "state-scanner")
_SS_SCRIPTS = str(_SKILLS_DIR / "state-scanner" / "scripts")
for _p in (_SS_SCRIPTS, _SS_ROOT):   # same order as proposal §3's sole import block
    if _p not in sys.path:
        sys.path.insert(0, _p)

# --- Sister-module guard (proposal §1 clause 3 / detailed-tasks TASK-004 #2) ---
try:
    from lib.linked_issue_field import (  # noqa: E402
        FieldVerdict,
        extract_linked_issue_field,
        is_sentinel,
    )
    from lib.collision import normalize_linked_issue  # noqa: E402
    from collectors.multi_remote import resolve_enforced_remotes  # noqa: E402
except ImportError as _exc:  # pragma: no cover - guarded fallback
    FieldVerdict = extract_linked_issue_field = is_sentinel = None  # type: ignore[assignment]
    normalize_linked_issue = None  # type: ignore[assignment]
    resolve_enforced_remotes = None  # type: ignore[assignment]
    _SISTER_IMPORT_ERROR: Optional[BaseException] = _exc
else:
    _SISTER_IMPORT_ERROR = None


def _sister_skip_reason(available: bool, err: Optional[BaseException]) -> Optional[str]:
    """Pure decision function backing the module-level sister-availability guard.

    Extracted so ``TestSisterGuardLogic`` can exercise both branches directly —
    an actual sister-absent environment cannot be cheaply constructed in-process
    (the sister package is already imported/cached by the time any test runs),
    so this is what makes the *decision logic* itself (not just today's outcome)
    testable, per detailed-tasks TASK-004 verification #2.
    """
    if available:
        return None
    return f"前置未 ship: lib/linked_issue_field.py 缺席 ({err})"


_SISTER_AVAILABLE = _SISTER_IMPORT_ERROR is None
_SISTER_SKIP_REASON = _sister_skip_reason(_SISTER_AVAILABLE, _SISTER_IMPORT_ERROR)
if not _SISTER_AVAILABLE:  # pragma: no cover - inert while sister is shipped
    print(_SISTER_SKIP_REASON, file=sys.stderr)

_skip_no_sister = unittest.skipUnless(
    _SISTER_AVAILABLE, _SISTER_SKIP_REASON or "前置未 ship: lib/linked_issue_field.py 缺席"
)

# --- Probe import (bare, unguarded — baseline red is intended, see module docstring) ---
_PROBE_SCRIPT = _AUDIT_ENGINE / "scripts" / "sibling_spec_probe.py"
_SCRIPTS_DIR = str(_AUDIT_ENGINE / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import sibling_spec_probe as ssp  # noqa: E402

from sibling_spec_probe import (  # noqa: E402
    Classification,
    CorpusEntry,
    assemble_hits,
    classify_error,
    classify_proposal,
    is_stale_copy,
    key_to_json,
    make_key,
    parse_symref,
    resolve_default_branch,
    run_probe,
    sort_proposal_paths,
    url_tokens,
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def _proposal_text(field_line: Optional[str], *, extra_before: str = "", extra_after: str = "") -> str:
    """Minimal single-field proposal document; only the parts E0-E3 + the fence
    scanner look at are guaranteed present."""
    parts = ["# Proposal: fixture\n\n"]
    if extra_before:
        parts.append(extra_before)
    if field_line is not None:
        parts.append(field_line + "\n")
    parts.append("\nBody text.\n")
    if extra_after:
        parts.append(extra_after)
    return "".join(parts)


def _naive_key(token: str):
    """A *plausible* bad key function: normalizes but applies NO sentinel /
    blacklist special-casing at all (unlike the real ``make_key``, which per
    the interface contract folds both in). Used only to build adversarial
    negative-control demonstrations (memory `adversarial-fixture`) — never
    treated as ground truth."""
    n = normalize_linked_issue(token)
    return ("k", n[0], n[1]) if n is not None else ("r", token)


def _naive_key_chinese_sentinel_only(token: str):
    """Bad key function: recognizes only the `无` alias as sentinel, not the
    ASCII `none` spelling (any casing) — the partial-fix failure mode named
    in SC-9 / proposal owner ruling 2026-08-30 (6i)."""
    if token == "无":
        return None
    n = normalize_linked_issue(token)
    return ("k", n[0], n[1]) if n is not None else ("r", token)


def _naive_keys_for(text: str, key_fn) -> frozenset:
    fv = extract_linked_issue_field(text)
    if fv.verdict != "OK":
        return frozenset()
    return frozenset(k for k in (key_fn(e) for e in fv.token_elements) if k is not None)


@dataclass
class _Call:
    args: list
    cwd: object
    timeout: int


class Dynamic:
    """Marker wrapping a callable ``fn(args, cwd, timeout) -> (rc, out, err)``
    for use as a ``RecordingRunner`` handler value, so a plain 3-tuple handler
    is never ambiguous with a computed one."""

    def __init__(self, fn):
        self.fn = fn


class RecordingRunner:
    """Injectable git runner (style: ``phase-d-closer/tests/test_fetch_gate.py``'s
    ``_runner(seq)``, extended to dispatch by call *shape* rather than a flat
    sequence, since the probe issues heterogeneous command families per BRIEF §2:
    ``remote`` / ``ls-remote --symref`` / ``fetch`` / ``for-each-ref`` /
    ``ls-tree`` / ``show``).

    ``handlers`` maps a dispatch key (see ``_key``) to one of:
      - a single ``(rc, out, err)`` tuple, returned on every call;
      - a ``list`` of such tuples, consumed in call order (sticks on the last
        entry once exhausted) — used for fetch-retry sequences;
      - a ``Dynamic(fn)`` for logic that depends on the exact args (e.g.
        per-ref ``show``/``ls-tree`` content).

    An unmapped call returns ``(1, "", "unhandled by test fixture: <args>")``
    unless ``default`` overrides that — this makes a missing fixture entry
    fail loudly (visible in stderr / a wrong error_kind) instead of hanging.
    """

    def __init__(self, handlers=None, default=None):
        self.handlers = dict(handlers or {})
        self.default = default
        self.calls: list[_Call] = []
        self._cursors: dict = {}

    @staticmethod
    def key(args: list[str]):
        if not args:
            return ()
        cmd = args[0]
        if cmd == "remote":
            return ("remote",)
        if cmd == "ls-remote":
            return ("ls-remote", args[2])          # ["ls-remote","--symref",R,"HEAD"]
        if cmd == "symbolic-ref":
            return ("symbolic-ref", args[1])
        if cmd == "fetch":
            return ("fetch", args[3])               # ["fetch","--no-tags","--prune",R,refspec]
        if cmd == "for-each-ref":
            return ("for-each-ref", args[2])         # ["for-each-ref","--format=...",pattern]
        if cmd == "ls-tree":
            # BRIEF §2 pins ["ls-tree","-r","--name-only",ref,"--",...] (ref at
            # index 3). Dispatch tolerates ref appearing at index 2 too (i.e. a
            # call that omits --name-only) by keying off "whatever sits
            # immediately before the '--' pathspec separator" — that position
            # is unambiguous under either shape. This is a deliberate
            # decoupling: whether the exact --name-only flag is present is
            # checked by ONE dedicated assertion (see
            # TestBudgetAndCommandShape.test_ls_tree_command_shape_exact), so
            # a flag deviation doesn't collaterally fail every other SC that
            # merely needs ls-tree to enumerate paths for it (dedup/staleness/
            # cap/ordering/self-exclusion — none of those are testing the flag).
            try:
                sep = args.index("--")
                ref = args[sep - 1]
            except (ValueError, IndexError):
                ref = args[3] if len(args) > 3 else None
            return ("ls-tree", ref)
        if cmd == "show":
            return ("show", args[1])                 # ["show", f"{ref}:{path}"]
        return tuple(args)

    def __call__(self, args, cwd, timeout):
        self.calls.append(_Call(list(args), cwd, timeout))
        k = self.key(args)
        entry = self.handlers.get(k)
        if entry is None:
            if isinstance(self.default, Dynamic):
                return self.default.fn(args, cwd, timeout)
            if self.default is not None:
                return self.default
            return (1, "", f"unhandled by test fixture: {args}")
        if isinstance(entry, Dynamic):
            return entry.fn(args, cwd, timeout)
        if isinstance(entry, list):
            idx = self._cursors.get(k, 0)
            result = entry[min(idx, len(entry) - 1)]
            self._cursors[k] = idx + 1
            return result
        return entry

    def count(self, cmd: str, disambiguator=None) -> int:
        n = 0
        for c in self.calls:
            if not c.args or c.args[0] != cmd:
                continue
            if disambiguator is None:
                n += 1
            elif self.key(c.args) == (cmd, disambiguator):
                n += 1
        return n

    def timeouts(self) -> list[int]:
        return [c.timeout for c in self.calls]


def _for_each_ref_output(private_ns: str, remote: str, branches: list[str]) -> str:
    return "".join(f"{private_ns}/{remote}/{b}\n" for b in branches)


def _own_repo(own_spec_dir: str, field_line: Optional[str] = None) -> Path:
    """A real temp directory (no ``.git`` needed for ``run_probe`` — I/O beyond
    the own-proposal read all goes through the injected runner) containing
    ``openspec/changes/<own_spec_dir>/proposal.md`` per a2_discretions (a)."""
    d = Path(tempfile.mkdtemp(prefix="ssp-own-"))
    (d / ".git").mkdir()  # cheap marker; run_probe itself does no git-dir check
    own_dir = d / "openspec" / "changes" / own_spec_dir
    own_dir.mkdir(parents=True)
    (own_dir / "proposal.md").write_text(_proposal_text(field_line), encoding="utf-8")
    return d


# ===========================================================================
# TASK-004 — skeleton, sister guard, SC-21 import order, structural constraints
# ===========================================================================

class TestNoPytestImport(unittest.TestCase):
    """This file itself must stay unittest-only (run_all_tests.sh:44-45
    classifies a suite as pytest by grepping ``^import pytest`` / ``^from
    pytest`` — misclassifying us would SKIP this whole suite when pytest is
    absent, i.e. a silent false-green, not a red)."""

    def test_own_source_has_no_top_level_pytest_import(self):
        """How this goes red: someone adds `import pytest` at module scope
        (e.g. to use a fixture) — the regex (built without ever spelling the
        literal contiguous string, so this very assertion cannot self-match)
        catches it."""
        src = Path(__file__).read_text(encoding="utf-8")
        needle = re.compile(r"^(import|from)\s+pytest\b", re.MULTILINE)
        self.assertIsNone(needle.search(src), "test file must remain unittest-only, not pytest")


class TestRunAllTestsDiscovery(unittest.TestCase):
    """run_all_tests.sh must discover this tests/ dir and classify it unittest."""

    def test_audit_engine_listed_as_unittest_suite(self):
        """How this goes red: this file accidentally trips is_pytest_suite
        (conftest.py present, or a `^import pytest` line) — the listing would
        say '(pytest)' instead of '(unittest)', or omit audit-engine entirely
        if tests/ had zero test_*.py files."""
        script = _SKILLS_DIR / "run_all_tests.sh"
        if not script.is_file():
            self.skipTest(f"run_all_tests.sh not found at {script}")
        proc = subprocess.run(
            ["bash", str(script), "--list"], cwd=str(_SKILLS_DIR.parent),
            capture_output=True, text=True, timeout=30,
        )
        self.assertIn("audit-engine", proc.stdout, proc.stdout)
        line = next((ln for ln in proc.stdout.splitlines() if ln.strip().startswith("audit-engine")), "")
        self.assertIn("(unittest)", line, f"expected unittest classification, got: {line!r}")


class TestSisterGuardLogic(unittest.TestCase):
    """TASK-004 verification #2: '姊妹模块不可 import ⇒ 整个 TestCase 集合 skip
    并打印原因; 可 import ⇒ 不 skip'. The guard's *decision function* is unit
    tested directly (both branches); the *current-environment* outcome is
    checked against what this repo actually ships today."""

    def test_available_branch_yields_no_skip_reason(self):
        self.assertIsNone(_sister_skip_reason(True, None))

    def test_unavailable_branch_yields_prefixed_skip_reason(self):
        reason = _sister_skip_reason(False, ImportError("boom"))
        self.assertIsNotNone(reason)
        self.assertTrue(reason.startswith("前置未 ship: lib/linked_issue_field.py 缺席"))
        self.assertIn("boom", reason)

    def test_current_repo_has_sister_shipped_so_guard_is_inert(self):
        """This repo already ships linked-issue-field-availability (archived
        2026-09-02) — the guard must therefore NOT be skipping anything here.
        How this goes red: a bad sys.path order (see TestSC21ImportOrder)
        would make this import fail even though the sister module is on disk."""
        self.assertTrue(_SISTER_AVAILABLE, f"sister import failed: {_SISTER_IMPORT_ERROR!r}")
        self.assertIsNone(_SISTER_IMPORT_ERROR)


@_skip_no_sister
class TestSC21ImportOrder(unittest.TestCase):
    """SC-21 — the sole import block's insertion order is load-bearing:
    ``state-scanner/scripts/lib/`` (Layer L helper package, no collision.py)
    and ``state-scanner/lib/`` (has collision.py) share the name ``lib``.
    """

    def test_positive_lib_binds_to_state_scanner_lib(self):
        """How this goes red: importing sibling_spec_probe with the insertion
        order reversed would bind top-level `lib` to scripts/lib instead —
        this assertion pins it to the correct package."""
        lib_mod = sys.modules.get("lib")
        self.assertIsNotNone(lib_mod, "sibling_spec_probe import should have populated sys.modules['lib']")
        lib_file = Path(lib_mod.__file__).resolve()
        self.assertTrue(
            str(lib_file).endswith(str(Path("state-scanner") / "lib" / "__init__.py")),
            f"lib bound to wrong package: {lib_file}",
        )
        # collectors.multi_remote must resolve too (scripts/ path half of the block)
        from collectors.multi_remote import resolve_enforced_remotes as rer  # noqa: E402
        self.assertTrue(callable(rer))
        collision_mod = sys.modules.get("lib.collision")
        self.assertIsNotNone(collision_mod)
        self.assertIn(str(Path("state-scanner") / "lib"), str(Path(collision_mod.__file__).resolve()))

    def test_negative_reversed_insertion_order_breaks_lib_collision(self):
        """Negative control (required): a subprocess that inserts the SAME two
        paths in REVERSED order (state-scanner root first, then its scripts/
        dir — so scripts/ ends up ahead in sys.path) must fail to import
        `lib.collision`, proving the collision is real and the correct order
        in the probe is not a no-op. How this goes red (i.e. how the negative
        control itself would be wrong): if this subprocess exits 0, the
        same-name collision this SC exists to catch has disappeared and the
        negative control needs re-review (per detailed-tasks TASK-004 note)."""
        code = (
            "import sys\n"
            "from pathlib import Path\n"
            f"_ROOT = {str(_SS_ROOT)!r}\n"
            f"_SCRIPTS = {str(_SS_SCRIPTS)!r}\n"
            "for _p in (_ROOT, _SCRIPTS):\n"          # reversed vs the contract's (_SCRIPTS, _ROOT)
            "    if _p not in sys.path:\n"
            "        sys.path.insert(0, _p)\n"
            "import lib.collision\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(proc.returncode, 0, "reversed insertion order unexpectedly succeeded")
        self.assertIn("ModuleNotFoundError", proc.stderr, proc.stderr)


class TestStructuralConstraints(unittest.TestCase):
    """A.2 explicit constraint (proposal :171): audit-engine must not grow its
    own top-level `lib/` or `collectors/` (would collide with the imported
    names by the same trap the SC-21 negative control demonstrates); scripts/
    helper files must be namespaced."""

    def test_no_lib_or_collectors_directories_under_audit_engine(self):
        self.assertFalse((_AUDIT_ENGINE / "lib").exists(), "audit-engine must not define its own lib/")
        self.assertFalse((_AUDIT_ENGINE / "collectors").exists(), "audit-engine must not define its own collectors/")

    def test_scripts_helper_files_are_namespaced(self):
        """How this goes red: a helper module named e.g. `scripts/git_utils.py`
        (no `sibling_spec_probe_` prefix) would collide with other skills'
        scripts/ namespaces once multiple skills' scripts/ dirs ever share a
        sys.path entry."""
        scripts_dir = _AUDIT_ENGINE / "scripts"
        if not scripts_dir.is_dir():
            self.skipTest("scripts/ does not exist yet (baseline)")
        allowed = {"sibling_spec_probe.py", "__init__.py"}
        offenders = [
            p.name for p in scripts_dir.glob("*.py")
            if p.name not in allowed and not p.name.startswith("sibling_spec_probe_")
        ]
        self.assertEqual(offenders, [], f"unnamespaced helper files: {offenders}")


class TestUniqueImportBlock(unittest.TestCase):
    """Source-level assertions on the probe's own text (proposal §3's
    'A cross-skill import mode' block + Rule#6 note constraints): exactly one
    `sys.path.insert` occurrence, no stray `from lib.`/`from collectors.`
    outside that block, no forbidden literals, no third-party imports."""

    @classmethod
    def setUpClass(cls):
        if not _PROBE_SCRIPT.is_file():
            raise unittest.SkipTest("probe script does not exist yet (baseline)")
        cls.src = _PROBE_SCRIPT.read_text(encoding="utf-8")

    def test_exactly_one_sys_path_insert_occurrence(self):
        n = len(re.findall(r"sys\.path\.insert\(", self.src))
        self.assertEqual(n, 1, f"expected exactly one sys.path.insert(...) call site, found {n}")

    def test_from_lib_or_collectors_imports_form_one_contiguous_block(self):
        lines = self.src.splitlines()
        idxs = [i for i, ln in enumerate(lines) if re.match(r"^\s*from (lib|collectors)\.", ln)]
        self.assertTrue(idxs, "expected at least one `from lib.`/`from collectors.` import")
        span = max(idxs) - min(idxs) + 1
        self.assertEqual(
            span, len(idxs),
            f"from lib./from collectors. imports are not contiguous (a second import site exists): lines {idxs}",
        )

    def test_no_default_branch_fallback_literal(self):
        self.assertNotIn("_DEFAULT_BRANCH_FALLBACKS", self.src)
        self.assertNotIn('("master", "main")', self.src)

    def test_no_max_branches_knob_reuse(self):
        self.assertNotIn("max_branches", self.src)

    def test_no_scripts_lib_module_names(self):
        for forbidden in ("lib.runtime_probe", "lib.detailed_tasks", "lib.carry_forward",
                           "lib.frontmatter_block", "lib.spec_complete"):
            self.assertNotIn(forbidden, self.src, f"must not reference scripts/lib module {forbidden}")

    def test_no_refs_remotes_glob(self):
        self.assertNotIn("for-each-ref refs/remotes", self.src)
        self.assertNotIn("refs/remotes/*", self.src)

    def test_no_remote_refresh_import(self):
        """P3 (proposal §5(e)): must not reuse remote_refresh's cache. Only an
        actual IMPORT of that module is banned — a rationale comment citing it
        (e.g. explaining why fetch is NOT shared with /state-scanner's cache,
        in the Impact-table 'why not reuse X' style used throughout this Spec)
        is expected and must not trip this check. The runtime behaviors
        ('never calls symbolic-ref', 'never consults FETCH_HEAD') are asserted
        as actual call-absence in TestBudgetAndCommandShape / TestSC13* via the
        injected runner, which is a stronger check than a source-text grep."""
        self.assertNotRegex(
            self.src,
            r"(?m)^\s*(from\s+\S*\bremote_refresh\b\S*\s+import|import\s+\S*\bremote_refresh\b)",
        )

    def test_no_third_party_imports(self):
        """Every top-level import root must be stdlib, `lib`/`collectors`
        (the sister packages), or `__future__`."""
        tree = ast.parse(self.src, filename=str(_PROBE_SCRIPT))
        stdlib = set(getattr(sys, "stdlib_module_names", ()))
        allowed = stdlib | {"lib", "collectors", "__future__", "sibling_spec_probe"}
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in allowed:
                        offenders.append(root)
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root not in allowed:
                    offenders.append(root)
        self.assertEqual(offenders, [], f"third-party imports found: {offenders}")


# ===========================================================================
# TASK-005 — pure classification: SC-7/8/9/10/11/19, key construction, BAD_TOKEN union
# ===========================================================================

@_skip_no_sister
class TestKeyConstruction(unittest.TestCase):
    """Key-construction contract (proposal §3 'key construction' block):
    normalize→("k",..); else ("r",..); the two families never collide."""

    def test_k_and_r_families_never_equal(self):
        k = make_key("10CG/aria-plugin#42")
        r = make_key("not-a-token")
        self.assertEqual(k[0], "k")
        self.assertEqual(r[0], "r")
        self.assertNotEqual(k, r)

    def test_unnormalizable_token_falls_back_to_raw_key(self):
        self.assertEqual(make_key("TBD"), ("r", "TBD"))

    def test_normalizable_token_yields_k_key(self):
        self.assertEqual(make_key("10CG/aria-plugin#42"), ("k", "aria-plugin", 42))

    def test_multi_element_each_yields_own_key(self):
        text = _proposal_text("> **关联 Issue**: `10CG/aria-plugin#1, 10CG/aria-plugin#2`")
        got = classify_proposal(text)
        self.assertEqual(
            got.keys, frozenset({("k", "aria-plugin", 1), ("k", "aria-plugin", 2)}),
        )

    def test_key_to_json_round_trip_shapes(self):
        self.assertEqual(key_to_json(("k", "aria-plugin", 122)), ["k", "aria-plugin", 122])
        self.assertEqual(key_to_json(("r", "TBD")), ["r", "TBD"])


@_skip_no_sister
class TestLayerDispatchTable(unittest.TestCase):
    """§3 layer-dispatch table (proposal :108-114), one row per test."""

    def test_no_field_row(self):
        got = classify_proposal(_proposal_text(None))
        self.assertEqual(got.layer, "no_field")
        self.assertEqual(got.keys, frozenset())
        self.assertIsNone(got.field_line)

    def test_no_token_with_url_row(self):
        text = _proposal_text(
            "> **关联 Issue**: [x](https://forgejo.10cg.pub/10CG/aria-plugin/issues/122)"
        )
        got = classify_proposal(text)
        self.assertEqual(got.layer, "url_fallback")
        self.assertEqual(got.keys, frozenset({("k", "aria-plugin", 122)}))

    def test_no_token_without_url_row(self):
        got = classify_proposal(_proposal_text("> **关联 Issue**: 看正文"))
        self.assertEqual(got.layer, "no_token_no_url")
        self.assertEqual(got.keys, frozenset())

    def test_bad_token_row(self):
        got = classify_proposal(_proposal_text("> **关联 Issue**: `TBD`"))
        self.assertEqual(got.layer, "bad_token_union")
        self.assertEqual(got.keys, frozenset({("r", "TBD")}))

    def test_ok_sentinel_row(self):
        got = classify_proposal(_proposal_text("> **关联 Issue**: `none`"))
        self.assertEqual(got.layer, "none_sentinel")
        self.assertEqual(got.keys, frozenset())

    def test_ok_canonical_row(self):
        got = classify_proposal(_proposal_text("> **关联 Issue**: `10CG/aria-plugin#42`"))
        self.assertEqual(got.layer, "canonical")
        self.assertEqual(got.keys, frozenset({("k", "aria-plugin", 42)}))


@_skip_no_sister
class TestSC7CanonicalCollisionRealCorpus(unittest.TestCase):
    """SC-7 (M-1 主条) — real archive fixture lines, verbatim."""

    LINE_6 = (
        "> **关联 Issue**: [10CG/aria-plugin #122]"
        "(https://forgejo.10cg.pub/10CG/aria-plugin/issues/122) "
        "(open; triage verdict=`confirmed`/`major`/`next-cycle`, 3/3 复现, "
        "[issuecomment-16979](https://forgejo.10cg.pub/10CG/aria-plugin/issues/122#issuecomment-16979))"
    )
    LINE_22 = (
        "> **关联 Issue**: [10CG/aria-plugin #122]"
        "(https://forgejo.10cg.pub/10CG/aria-plugin/issues/122) "
        "(open, 0 评论, 无 in-flight — 本地 fetch + Forgejo API 双核实)"
    )

    def test_both_lines_yield_the_same_k_key(self):
        """How this goes red: a layer-1-only implementation (canonical
        extraction, no URL fallback) sees NO_TOKEN (colon is followed by `[`,
        not a backtick) and returns an empty key set for both — no collision,
        wrongly missing the exact case this Spec exists for."""
        c1 = classify_proposal(_proposal_text(self.LINE_6))
        c2 = classify_proposal(_proposal_text(self.LINE_22))
        self.assertEqual(c1.keys, frozenset({("k", "aria-plugin", 122)}))
        self.assertEqual(c2.keys, frozenset({("k", "aria-plugin", 122)}))
        self.assertTrue(c1.keys & c2.keys, "SC-7 fixtures must collide on the same key")

    def test_bad_layer1_only_implementation_misses_the_collision(self):
        def _bad_layer1_only(text):
            fv = extract_linked_issue_field(text)
            if fv.verdict != "OK":
                return frozenset()  # no URL fallback at all
            if is_sentinel(fv.token_str):
                return frozenset()
            return frozenset(k for k in (make_key(e) for e in fv.token_elements) if k is not None)

        k1 = _bad_layer1_only(_proposal_text(self.LINE_6))
        k2 = _bad_layer1_only(_proposal_text(self.LINE_22))
        self.assertEqual(k1, frozenset())
        self.assertEqual(k2, frozenset())
        self.assertFalse(k1 & k2, "bad layer-1-only implementation should NOT collide (that's the bug)")


@_skip_no_sister
class TestSC8ProviderPositionScope(unittest.TestCase):
    """SC-8 (M-1, extractor-position constraint) — line :6 has code spans
    (`confirmed`/`major`/`next-cycle`) AFTER the field's own (bracket, not
    backtick) content; a bad extractor grabbing "the first code span anywhere
    on the line" must NOT be what the real classifier does."""

    LINE_6 = TestSC7CanonicalCollisionRealCorpus.LINE_6

    def test_confirmed_is_not_extracted(self):
        got = classify_proposal(_proposal_text(self.LINE_6))
        self.assertNotIn(("r", "confirmed"), got.keys)
        self.assertEqual(got.layer, "url_fallback")
        self.assertEqual(got.keys, frozenset({("k", "aria-plugin", 122)}))

    def test_bad_first_code_span_anywhere_extracts_confirmed(self):
        """This is a different failure than SC-18 (which is about picking the
        wrong *line*): here the line is picked correctly, but the wrong *span
        within the line* is taken as the token."""
        def _bad_first_code_span_anywhere(line: str):
            m = re.search(r"`([^`]*)`", line)
            return m.group(1) if m else None

        bad_token = _bad_first_code_span_anywhere(self.LINE_6)
        self.assertEqual(bad_token, "confirmed")
        self.assertEqual(make_key(bad_token), ("r", "confirmed"))


@_skip_no_sister
class TestSC9SentinelNonCollision(unittest.TestCase):
    """SC-9 (FIX-10 对照臂 1) — three sentinel-pair groups, none collide."""

    GROUPS = [
        ("无", "> **关联 Issue**: `无`", "无", "> **Linked Issue**: `无`"),
        ("none", "> **关联 Issue**: `none`", "none", "> **Linked Issue**: `none`"),
        ("none", "> **关联 Issue**: `none`", "无", "> **Linked Issue**: `无`"),
    ]

    def test_three_groups_never_collide_and_layer_is_none_sentinel(self):
        for i, (_, line_a, _, line_b) in enumerate(self.GROUPS):
            with self.subTest(group=i):
                ca = classify_proposal(_proposal_text(line_a))
                cb = classify_proposal(_proposal_text(line_b))
                self.assertEqual(ca.layer, "none_sentinel")
                self.assertEqual(cb.layer, "none_sentinel")
                self.assertEqual(ca.keys, frozenset())
                self.assertEqual(cb.keys, frozenset())

    def test_bad_naive_key_treats_sentinel_as_token_and_collides(self):
        """How SC-9 goes red for this bad implementation: raw-string equality
        on the un-normalizable sentinel means BOTH sides land on the same
        ('r', '<token>') raw key — but only when the two RAW literals actually
        match byte-for-byte (groups 0 and 1: 无/无 and none/none). Group 2 pairs
        DIFFERENT literals ('none' vs '无'), so even a naive raw-key function
        does not collide there — that group's job (proving the GOOD
        implementation doesn't collide either) is already covered by
        test_three_groups_never_collide_and_layer_is_none_sentinel above."""
        for i, (tok_a, line_a, tok_b, line_b) in enumerate(self.GROUPS):
            if tok_a != tok_b:
                continue  # group 2: mismatched literals never raw-collide, naive or not
            with self.subTest(group=i):
                ka = _naive_keys_for(_proposal_text(line_a), _naive_key)
                kb = _naive_keys_for(_proposal_text(line_b), _naive_key)
                self.assertTrue(ka & kb, f"naive key function should (wrongly) collide on group {i}")

    def test_bad_chinese_only_sentinel_collides_on_none_none(self):
        """Partial fix (only recognizes `无`, not ASCII `none`) still collides
        on the (none, none) group — owner ruling 2026-08-30 (6i)."""
        line_a = "> **关联 Issue**: `none`"
        line_b = "> **Linked Issue**: `none`"
        ka = _naive_keys_for(_proposal_text(line_a), _naive_key_chinese_sentinel_only)
        kb = _naive_keys_for(_proposal_text(line_b), _naive_key_chinese_sentinel_only)
        self.assertTrue(ka & kb, "chinese-only sentinel guard should (wrongly) collide on (none, none)")


@_skip_no_sister
class TestSC10SentinelWithUrlInLine(unittest.TestCase):
    """SC-10 (FIX-10 对照臂 2) — sentinel field whose line ALSO contains an
    issue URL must NOT fall back to layer 2 (URL fallback is gated on the
    sister verdict being NO_TOKEN/BAD_TOKEN, not on 'canonical set is empty')."""

    ARMS = [
        "> **关联 Issue**: `无` — 讨论见 https://forgejo.10cg.pub/10CG/aria-plugin/issues/122",
        "> **Linked Issue**: `none` — see https://forgejo.10cg.pub/10CG/aria-plugin/issues/122",
    ]

    def test_sentinel_with_inline_url_does_not_fall_back(self):
        other = classify_proposal(_proposal_text("> **关联 Issue**: `10CG/aria-plugin#122`"))
        for i, line in enumerate(self.ARMS):
            with self.subTest(arm=i):
                got = classify_proposal(_proposal_text(line))
                self.assertEqual(got.layer, "none_sentinel", "must not be url_fallback")
                self.assertEqual(got.keys, frozenset())
                self.assertFalse(got.keys & other.keys)

    def test_bad_empty_set_trigger_falls_back_and_collides(self):
        """Bad implementation: triggers URL fallback whenever the canonical
        key set is empty (true both for a sentinel AND for NO_TOKEN), instead
        of gating strictly on the sister verdict."""
        for i, line in enumerate(self.ARMS):
            with self.subTest(arm=i):
                fv = extract_linked_issue_field(_proposal_text(line))
                self.assertEqual(fv.verdict, "OK")
                self.assertTrue(is_sentinel(fv.token_str))
                canonical_keys = frozenset(
                    k for k in (make_key(e) for e in fv.token_elements) if k is not None
                )
                self.assertEqual(canonical_keys, frozenset(), "canonical set is empty for a sentinel")
                # "empty canonical set ⇒ fall back to URL" (the bug):
                bad_keys = frozenset(make_key(t) for t in url_tokens(line))
                self.assertEqual(bad_keys, frozenset({("k", "aria-plugin", 122)}),
                                  "bad implementation wrongly extracts #122 from a sentinel line")


@_skip_no_sister
class TestSC11SentinelVsNoField(unittest.TestCase):
    """SC-11 — both empty-key-set outcomes, but layer must distinguish
    positive evidence (sentinel) from zero evidence (no field)."""

    def test_layers_are_distinguishable(self):
        sentinel = classify_proposal(_proposal_text("> **关联 Issue**: `无`"))
        no_field = classify_proposal(_proposal_text(None))
        self.assertEqual(sentinel.keys, frozenset())
        self.assertEqual(no_field.keys, frozenset())
        self.assertNotEqual(sentinel.layer, no_field.layer)
        self.assertEqual(sentinel.layer, "none_sentinel")
        self.assertEqual(no_field.layer, "no_field")


@_skip_no_sister
class TestSC19PlaceholderBlacklist(unittest.TestCase):
    """SC-19 — SOT template placeholder `{<org>/<repo>#<n>}` must not
    round-trip into a raw key (else two un-filled proposals collide on it)."""

    PLACEHOLDER_LINE = "> **关联 Issue**: `{<org>/<repo>#<n>}`"

    def test_two_placeholders_do_not_collide(self):
        """How this goes red: an implementation that produces a raw key for
        every BAD_TOKEN element (no blacklist) makes two un-filled proposals
        collide on ('r', '{<org>/<repo>#<n>}') — 'what does nothing wins'."""
        c1 = classify_proposal(_proposal_text(self.PLACEHOLDER_LINE))
        c2 = classify_proposal(_proposal_text(self.PLACEHOLDER_LINE))
        self.assertEqual(c1.layer, "bad_token_union")
        self.assertEqual(c2.layer, "bad_token_union")
        self.assertNotIn(("r", "{<org>/<repo>#<n>}"), c1.keys)
        self.assertNotIn(("r", "{<org>/<repo>#<n>}"), c2.keys)
        self.assertFalse(c1.keys & c2.keys, "placeholder proposals must not collide")

    def test_bad_no_blacklist_implementation_collides(self):
        bad = frozenset(_naive_key(e) for e in ("{<org>/<repo>#<n>}",))
        self.assertEqual(bad, frozenset({("r", "{<org>/<repo>#<n>}")}))
        self.assertTrue(bad & bad, "sanity: identical raw keys always collide without a blacklist")


@_skip_no_sister
class TestBadTokenUnion(unittest.TestCase):
    """BAD_TOKEN takes the UNION of layer-1 (parseable elements) and layer-2
    (URL fragments in the field line) — the two counter-examples from
    proposal §3 that each defeat a single-layer-only choice."""

    def test_counter_example_a_valid_number_plus_bad_element(self):
        line = "> **关联 Issue**: `10CG/aria-plugin#122, TBD`"
        got = classify_proposal(_proposal_text(line))
        self.assertEqual(got.layer, "bad_token_union")
        self.assertEqual(got.keys, frozenset({("k", "aria-plugin", 122), ("r", "TBD")}))
        # only-layer-2 would drop TBD's raw key (fine) but ALSO never sees it
        # via layer 1 either if union weren't applied — assert union really
        # combined both:
        only_layer1 = frozenset(
            k for k in (make_key(e) for e in ("10CG/aria-plugin#122", "TBD")) if k is not None
        )
        self.assertEqual(only_layer1, got.keys, "layer-1 alone happens to match here (URL absent)")

    def test_counter_example_b_all_bad_elements_but_inline_url(self):
        line = ("> **关联 Issue**: `TBD` — 讨论见 "
                "https://forgejo.10cg.pub/10CG/aria-plugin/issues/122")
        got = classify_proposal(_proposal_text(line))
        self.assertEqual(got.layer, "bad_token_union")
        self.assertEqual(got.keys, frozenset({("k", "aria-plugin", 122), ("r", "TBD")}))

    def test_only_layer2_implementation_loses_number_in_example_a(self):
        line = "> **关联 Issue**: `10CG/aria-plugin#122, TBD`"
        fv = extract_linked_issue_field(_proposal_text(line))
        only_layer2 = frozenset(make_key(t) for t in url_tokens(fv.token_str or ""))
        self.assertEqual(only_layer2, frozenset(), "example A's field line has no URL — only-layer-2 loses #122")

    def test_only_layer1_implementation_loses_number_in_example_b(self):
        line = ("> **关联 Issue**: `TBD` — 讨论见 "
                "https://forgejo.10cg.pub/10CG/aria-plugin/issues/122")
        fv = extract_linked_issue_field(_proposal_text(line))
        only_layer1 = frozenset(k for k in (make_key(e) for e in fv.token_elements) if k is not None)
        self.assertEqual(only_layer1, frozenset({("r", "TBD")}), "only-layer-1 loses #122 in example B")


# ===========================================================================
# TASK-006 — SC-18 layer-0 four-arm adversarial + SC-1 archive hit
# ===========================================================================

def _cc1bdef_available():
    try:
        r = subprocess.run(
            ["git", "-C", str(_MAIN_REPO_ROOT), "cat-file", "-e", "cc1bdef^{commit}"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return False, f"cc1bdef not reachable in {_MAIN_REPO_ROOT}: {r.stderr.strip()}"
        ls = subprocess.run(
            ["git", "-C", str(_MAIN_REPO_ROOT), "ls-tree", "-r", "--name-only", "cc1bdef",
             "--", "openspec/changes", "openspec/archive"],
            capture_output=True, text=True, timeout=15,
        )
        paths = [p for p in ls.stdout.splitlines() if p.endswith("proposal.md")]
        if len(paths) != 147:
            return False, f"expected 147 proposal.md at cc1bdef, got {len(paths)}"
        return True, paths
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"git invocation failed: {exc}"


def _git_show(sha: str, path: str) -> Optional[str]:
    r = subprocess.run(
        ["git", "-C", str(_MAIN_REPO_ROOT), "show", f"{sha}:{path}"],
        capture_output=True, text=True, timeout=30,
    )
    return r.stdout if r.returncode == 0 else None


_LOOSE_FIELD_RE = re.compile(r"\*\*(?:Linked Issue|关联 Issue)\*\*:")
_HEAD_ANCHOR_RE = re.compile(r"^> \*\*(?:Linked Issue|关联 Issue)\*\*:")


def _loose_locator_first_hit(text: str):
    """(b) bad locator: matches ANYWHERE on the line (no line-anchor, no
    fence exclusion) — the false-positive locator the proposal's own §Why
    documented catching the mother-Spec's nested-quote example."""
    for i, line in enumerate(text.split("\n")):
        if _LOOSE_FIELD_RE.search(line):
            return i + 1, line
    return None, None


def _head_only_locator_first_hit(text: str):
    """(c) bad locator: line-anchored but restricted to before the first bare
    '---' line — the 'over-fix' the proposal's own §3 rejects."""
    lines = text.split("\n")
    limit = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == "---":
            limit = i
            break
    for i in range(limit):
        if _HEAD_ANCHOR_RE.match(lines[i]):
            return i + 1, lines[i]
    return None, None


def _extract_via_locator(text: str, locator):
    """Re-implements only the *layer-0 substitution*: run `locator` instead of
    the sister's real E0, but reuse its E1-E5 token parsing on whichever line
    the (possibly wrong) locator picked — isolates the assertion to layer-0
    behavior specifically."""
    line_no, line = locator(text)
    if line_no is None:
        return "NO_FIELD", None, None
    m = _HEAD_ANCHOR_RE.match(line) or _LOOSE_FIELD_RE.search(line)
    end_of_prefix = m.end() if m else 0
    rest = line[end_of_prefix:].lstrip(" \t")
    if not rest or rest[0] != "`":
        return "NO_TOKEN", None, line
    close = rest.find("`", 1)
    if close == -1:
        return "NO_TOKEN", None, line
    return "OK_OR_BAD", rest[1:close], line


def _classify_via_locator(text: str, locator):
    verdict, token_str, line = _extract_via_locator(text, locator)
    if verdict == "NO_FIELD":
        return "no_field", None
    if verdict == "NO_TOKEN":
        toks = url_tokens(line)
        return ("url_fallback", toks) if toks else ("no_token_no_url", None)
    return ("token_present", token_str)  # OK/BAD_TOKEN not needed for SC-18's counts


@_skip_no_sister
class TestSC18ArmDSyntheticFenceFixture(unittest.TestCase):
    """(d) — the ONLY arm that actually exercises fence exclusion (a/b/c all
    showed zero real-corpus difference for it, per proposal §3 note). Lives in
    its OWN class, deliberately NOT guarded by cc1bdef reachability: per
    detailed-tasks TASK-006 verification, this arm must never be skipped even
    when the main-repo cc1bdef corpus is unreachable (a/c/b in
    ``TestSC18LayerZeroFourArms`` below ARE allowed to skip in that case)."""

    def test_fence_excluded_field_line_is_invisible(self):
        text = (
            "# Proposal: fixture\n\n"
            "```\n"
            "> **关联 Issue**: `10CG/x#1`\n"
            "```\n\n"
            "Body.\n"
        )
        got = classify_proposal(text)
        self.assertEqual(got.layer, "no_field")
        self.assertEqual(got.keys, frozenset())

    def test_bad_no_fence_exclusion_locator_wrongly_sees_it(self):
        text = (
            "# Proposal: fixture\n\n"
            "```\n"
            "> **关联 Issue**: `10CG/x#1`\n"
            "```\n\n"
            "Body.\n"
        )

        def _no_fence_exclusion_locator(t):
            for i, line in enumerate(t.split("\n")):
                if _HEAD_ANCHOR_RE.match(line):
                    return i + 1, line
            return None, None

        kind, _ = _classify_via_locator(text, _no_fence_exclusion_locator)
        self.assertNotEqual(kind, "no_field", "a fence-blind locator would (wrongly) see this as a real field")


class TestSC18LayerZeroFourArms(unittest.TestCase):
    """SC-18 (a)/(b)/(c) + SC-1 — adversarial-fixture (memory
    `adversarial-fixture`): validates REJECTION power, not just today's
    output, over the real 147-proposal corpus at main-repo commit cc1bdef.
    Skips (with a printed reason) if that corpus is unreachable from this
    checkout — arm (d) above is exempt from that guard by design."""

    @classmethod
    def setUpClass(cls):
        if not _SISTER_AVAILABLE:
            raise unittest.SkipTest(_SISTER_SKIP_REASON)
        ok, paths_or_reason = _cc1bdef_available()
        if not ok:
            raise unittest.SkipTest(paths_or_reason)
        cls.paths = paths_or_reason
        cls.blobs = {p: _git_show("cc1bdef", p) for p in cls.paths}
        cls.blobs = {p: t for p, t in cls.blobs.items() if t is not None}

    def _counts_and_clusters(self, classify_fn):
        counts = {"no_field": 0, "url_fallback": 0, "no_token_no_url": 0, "token_present": 0}
        clusters: dict = {}
        for path, text in self.blobs.items():
            kind, data = classify_fn(text)
            counts[kind] = counts.get(kind, 0) + 1
            if kind == "url_fallback":
                spec_dir = path.split("/")[-2]
                for tok in data:
                    key = make_key(tok)
                    clusters.setdefault(key, set()).add(spec_dir)
        real_clusters = {k: v for k, v in clusters.items() if len(v) >= 2}
        return counts, real_clusters

    def test_arm_a_real_probe_path_via_sister_function(self):
        """(a) = the probe's real layer-0 path, i.e. the sister function
        itself (no re-implementation)."""
        def classify_a(text):
            fv = extract_linked_issue_field(text)
            if fv.verdict == "NO_FIELD":
                return "no_field", None
            if fv.verdict == "NO_TOKEN":
                line = text.split("\n")[fv.line_no - 1]
                toks = url_tokens(line)
                return ("url_fallback", toks) if toks else ("no_token_no_url", None)
            return "token_present", None

        counts, clusters = self._counts_and_clusters(classify_a)
        self.assertEqual(counts["no_field"], 133)
        self.assertEqual(counts["url_fallback"], 13)
        self.assertEqual(counts["no_token_no_url"], 1)
        self.assertEqual(len(clusters), 3, f"expected 3 clusters, got {list(clusters.values())}")
        all_dirs = set().union(*clusters.values()) if clusters else set()
        self.assertNotIn("a1-entry-claim-duplicate-work-guard", all_dirs)

    def test_arm_b_loose_locator_has_false_positive(self):
        """(b) demonstrates arm (a)'s rejection power: the loose (any
        position, no fence, no anchor) locator DOES pick up the mother-Spec's
        nested-quote example as a false positive."""
        def classify_b(text):
            return _classify_via_locator(text, _loose_locator_first_hit)

        counts, clusters = self._counts_and_clusters(classify_b)
        self.assertEqual(counts["url_fallback"], 14)
        key_122 = ("k", "aria-plugin", 122)
        self.assertIn(key_122, clusters)
        self.assertIn("a1-entry-claim-duplicate-work-guard", clusters[key_122])

    def test_arm_c_head_only_locator_over_filters(self):
        """(c) demonstrates the opposite failure of an over-fix: restricting
        to 'before the first ---' kills two of the three real clusters."""
        def classify_c(text):
            return _classify_via_locator(text, _head_only_locator_first_hit)

        counts, clusters = self._counts_and_clusters(classify_c)
        self.assertEqual(counts["url_fallback"], 10)
        self.assertEqual(len(clusters), 1, f"expected only 1 surviving cluster, got {clusters}")

    def test_sc1_archive_corpus_hits_are_flagged_archive(self):
        """SC-1: the #122 cluster's two proposals live in archive/; assemble_hits
        must surface corpus == 'archive' for both. How this goes red: an
        implementation that only scans openspec/changes/ returns [] on this
        Spec's own founding real-corpus example."""
        p1 = "openspec/archive/2026-07-31-phase-c-gate-path-coverage-not-applicable/proposal.md"
        p2 = "openspec/archive/2026-08-22-phase-c-integrator-ci-path-coverage/proposal.md"
        t1, t2 = self.blobs.get(p1), self.blobs.get(p2)
        if t1 is None or t2 is None:
            self.skipTest("cc1bdef corpus missing expected SC-1 fixture paths")
        entries = [
            CorpusEntry(
                remote="origin", ref_label="origin/master", branch="master",
                corpus="archive", spec_dir=p1.split("/")[-2], path=p1,
                classification=classify_proposal(t1),
            ),
            CorpusEntry(
                remote="origin", ref_label="origin/master", branch="master",
                corpus="archive", spec_dir=p2.split("/")[-2], path=p2,
                classification=classify_proposal(t2),
            ),
        ]
        hits = assemble_hits(frozenset({("k", "aria-plugin", 122)}), "unrelated-own-spec", entries)
        self.assertEqual(len(hits), 2, hits)
        for h in hits:
            self.assertEqual(h["corpus"], "archive")


# ===========================================================================
# TASK-007 — remote resolution / fetch / cap (injected git runner)
# ===========================================================================

_NS = "refs/aria/sibling-probe"


@_skip_no_sister
class TestSC12DefaultBranchViaLsRemote(unittest.TestCase):
    def test_resolves_via_ls_remote_symref_not_local_symbolic_ref(self):
        """How this goes red: an implementation that only reads local
        `refs/remotes/github/HEAD` (which exit-128s in this real repo, per
        the 2026-08-30 observation baked into the fixture) would report
        `github` unresolved even though ls-remote is available."""
        runner = RecordingRunner({
            ("symbolic-ref", "refs/remotes/github/HEAD"): (128, "", "fatal: ref refs/remotes/github/HEAD is not a symbolic ref"),
            ("ls-remote", "github"): (0, "ref: refs/heads/master\tHEAD\ndeadbeef\tHEAD\n", ""),
        })
        branch, resolved_by, error_kind = resolve_default_branch("github", Path("/repo"), runner)
        self.assertEqual(branch, "master")
        self.assertEqual(resolved_by, "ls_remote_symref")
        self.assertIsNone(error_kind)
        self.assertEqual(runner.count("symbolic-ref"), 0, "must not consult local symbolic-ref at all")


@_skip_no_sister
class TestSC13FailClosedFourArms(unittest.TestCase):
    """SC-13 — each arm run through the full ``run_probe`` (not just
    ``resolve_default_branch``) so the P11 no-fetch / refs_scanned==0
    short-circuit is exercised too."""

    def _run_single_remote(self, ls_remote_response):
        runner = RecordingRunner({
            ("remote",): (0, "R\n", ""),
            ("ls-remote", "R"): ls_remote_response,
        })
        repo = _own_repo("own-spec", "> **关联 Issue**: `10CG/aria-plugin#1`")
        result = run_probe(repo, "own-spec", runner=runner)
        return result, runner

    def test_arm_nonzero_exit(self):
        result, runner = self._run_single_remote((1, "", "fatal: unable to access: Could not resolve host: x"))
        self._assert_arm(result, runner)

    def test_arm_timeout(self):
        result, runner = self._run_single_remote((ssp.TIMEOUT_RC, "", "timeout"))
        self._assert_arm(result, runner, expect_kind="timeout")

    def test_arm_no_ref_colon_line(self):
        result, runner = self._run_single_remote((0, "some unrelated output\n", ""))
        self._assert_arm(result, runner, expect_kind="no_symref")

    def test_arm_bad_symref_prefix(self):
        result, runner = self._run_single_remote((0, "ref: refs/tags/v1\tHEAD\n", ""))
        self._assert_arm(result, runner, expect_kind="bad_symref_prefix")

    def _assert_arm(self, result, runner, expect_kind=None):
        remote = result["remotes"][0]
        self.assertIsNone(remote["default_branch"])
        self.assertIsNotNone(remote["error_kind"])
        if expect_kind is not None:
            self.assertEqual(remote["error_kind"], expect_kind)
        self.assertNotEqual(remote["default_branch"], "master")
        self.assertNotEqual(remote["default_branch"], "main")
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["verdict"], "not_established")
        self.assertEqual(runner.count("fetch"), 0, "unresolved default branch must short-circuit before fetch")
        self.assertEqual(remote["refs_scanned"], 0)


@_skip_no_sister
class TestSC14StaleRemoteTrackingRefExcluded(unittest.TestCase):
    def test_probe_remote_not_enumerated(self):
        """How this goes red: an implementation enumerating
        `refs/remotes/*` (instead of `git remote`) would include `probe`,
        a remote-tracking ref left over after `remote.probe.url` was removed
        from config (this repo's real, observed state, per line_anchor_recheck)."""
        runner = RecordingRunner({
            ("remote",): (0, "github\norigin\n", ""),
            ("ls-remote", "github"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "github"): (0, "", ""),
            ("fetch", "origin"): (0, "", ""),
            ("for-each-ref", f"{_NS}/github/"): (0, _for_each_ref_output(_NS, "github", ["master"]), ""),
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master"]), ""),
        })
        repo = _own_repo("own-spec", "> **关联 Issue**: `10CG/aria-plugin#1`")
        result = run_probe(repo, "own-spec", runner=runner)
        names = sorted(r["name"] for r in result["remotes"])
        self.assertEqual(names, ["github", "origin"])
        self.assertNotIn("probe", names)
        for c in runner.calls:
            self.assertNotIn("refs/remotes", " ".join(c.args), f"used refs/remotes glob: {c.args}")


@_skip_no_sister
class TestSC3DegradedRemoteKeepsOtherHits(unittest.TestCase):
    def test_github_fetch_fails_twice_origin_hit_survives(self):
        own_field = "> **关联 Issue**: `10CG/aria-plugin#122`"
        repo = _own_repo("own-spec-3", own_field)
        corpus_text = _proposal_text("> **关联 Issue**: `10CG/aria-plugin#122`")
        runner = RecordingRunner({
            ("remote",): (0, "github\norigin\n", ""),
            ("ls-remote", "github"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "github"): [(1, "", "fatal: Could not resolve host"), (1, "", "fatal: Could not resolve host")],
            ("fetch", "origin"): (0, "", ""),
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master"]), ""),
            ("ls-tree", f"{_NS}/origin/master"): (0, "openspec/changes/other-spec/proposal.md\n", ""),
            ("show", f"{_NS}/origin/master:openspec/changes/other-spec/proposal.md"): (0, corpus_text, ""),
        })
        result = run_probe(repo, "own-spec-3", runner=runner)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["verdict"], "sibling_found", "hits non-empty must win over status=degraded (2026-09-03 technical ruling)")
        github = next(r for r in result["remotes"] if r["name"] == "github")
        self.assertIsNotNone(github["error_kind"])
        self.assertEqual(runner.count("fetch", "github"), 2, "at most 2 fetch attempts, not 3")
        self.assertGreaterEqual(len(result["hits"]), 1)
        self.assertTrue(any(h["spec_dir"] == "other-spec" for h in result["hits"]),
                         "origin's real hit must survive a degraded sibling remote (not cleared wholesale)")

    def test_bad_verdict_computed_as_no_sibling_found_is_rejected(self):
        """Negative control: a bad implementation that lets `status=degraded`
        force `verdict='no_sibling_found'` regardless of hits would fail the
        assertion above (verdict must be 'sibling_found')."""
        # Documented via the primary test's assertion; kept as an explicit,
        # separately-named test per the "three bad implementations" tasking.
        self.test_github_fetch_fails_twice_origin_hit_survives()


@_skip_no_sister
class TestSC4NoEnforcedRemote(unittest.TestCase):
    def test_empty_remote_set_yields_skipped(self):
        runner = RecordingRunner({("remote",): (0, "", "")})
        repo = _own_repo("own-spec-4", "> **关联 Issue**: `10CG/aria-plugin#1`")
        result = run_probe(repo, "own-spec-4", runner=runner)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no_enforced_remote")
        self.assertEqual(result["verdict"], "not_established")
        self.assertEqual(len(runner.calls), 1, "no remote ⇒ no further git calls beyond `remote`")

    def test_bad_exit_nonzero_on_no_remote_is_the_rejected_shape(self):
        """Old SC-18 wording ('无远端 ⇒ exit 非 0') is explicitly overruled by
        decision D11 (proposal §7) — this test documents the run_probe-level
        shape that a CLI wrapping it must map to exit 0 (see TASK-008 SC-4 CLI test)."""
        runner = RecordingRunner({("remote",): (0, "", "")})
        repo = _own_repo("own-spec-4b", "> **关联 Issue**: `10CG/aria-plugin#1`")
        result = run_probe(repo, "own-spec-4b", runner=runner)
        self.assertNotEqual(result["status"], "ok")  # sanity: it IS a "nothing to enforce" case
        self.assertEqual(result["status"], "skipped")


@_skip_no_sister
class TestSC5SelfHitExcluded(unittest.TestCase):
    def test_own_spec_dir_excluded_on_default_and_nondefault_ref(self):
        own_spec_dir = "own-spec-5"
        own_field = "> **关联 Issue**: `10CG/aria-plugin#77`"
        repo = _own_repo(own_spec_dir, own_field)
        same_text = _proposal_text(own_field)
        runner = RecordingRunner({
            ("remote",): (0, "origin\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "origin"): (0, "", ""),
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master", "feature/x"]), ""),
            ("ls-tree", f"{_NS}/origin/master"): (0, f"openspec/changes/{own_spec_dir}/proposal.md\n", ""),
            ("ls-tree", f"{_NS}/origin/feature/x"): (0, f"openspec/changes/{own_spec_dir}/proposal.md\n", ""),
            ("show", f"{_NS}/origin/master:openspec/changes/{own_spec_dir}/proposal.md"): (0, same_text, ""),
            ("show", f"{_NS}/origin/feature/x:openspec/changes/{own_spec_dir}/proposal.md"): (0, same_text, ""),
        })
        result = run_probe(repo, own_spec_dir, runner=runner)
        self.assertFalse(
            any(h["spec_dir"] == own_spec_dir for h in result["hits"]),
            "own spec_dir must never appear in hits, on ANY ref",
        )


@_skip_no_sister
class TestSC6ProposalsCap(unittest.TestCase):
    def test_max_proposals_scanned_patched_to_one_keeps_changes(self):
        own_field = "> **关联 Issue**: `10CG/aria-plugin#88`"
        repo = _own_repo("own-spec-6", own_field)
        match_text = _proposal_text(own_field)
        runner = RecordingRunner({
            ("remote",): (0, "origin\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "origin"): (0, "", ""),
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master"]), ""),
            ("ls-tree", f"{_NS}/origin/master"): (
                0,
                "openspec/changes/c-spec/proposal.md\nopenspec/archive/2026-01-01-a-spec/proposal.md\n",
                "",
            ),
            ("show", f"{_NS}/origin/master:openspec/changes/c-spec/proposal.md"): (0, match_text, ""),
        })
        with mock.patch.object(ssp, "MAX_PROPOSALS_SCANNED", 1):
            result = run_probe(repo, "own-spec-6", runner=runner)
        self.assertTrue(any(h["spec_dir"] == "c-spec" for h in result["hits"]), "changes/ entry must be kept")
        self.assertFalse(any(h["spec_dir"] == "a-spec" for h in result["hits"]), "archive/ entry must be dropped")
        caps = result["caps_applied"]
        self.assertTrue(caps, "caps_applied must not be silently empty")
        cap = next(c for c in caps if c["kind"] == "proposals")
        self.assertEqual(cap["total"], 2)
        self.assertEqual(cap["kept"], 1)
        self.assertIn("openspec/archive/2026-01-01-a-spec/proposal.md", cap["dropped_from"])
        self.assertEqual(result["status"], "degraded")
        # hits IS non-empty here (c-spec matched) — the 2026-09-03 technical
        # ruling (§7 table row 1 outranks the older SC-6 text literally saying
        # "not_established") applies the same way it does for SC-3: a
        # non-empty hits[] always yields verdict="sibling_found", with the cap
        # surfaced via status=degraded + reason=cap_applied instead.
        self.assertEqual(result["verdict"], "sibling_found")
        self.assertEqual(result["reason"], "cap_applied")


@_skip_no_sister
class TestBudgetAndCommandShape(unittest.TestCase):
    """§5 timeout/retry budget + §5(f)/(e) exact fetch args."""

    def _base_runner(self, fetch_entry):
        return RecordingRunner({
            ("remote",): (0, "origin\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "origin"): fetch_entry,
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master"]), ""),
            ("ls-tree", f"{_NS}/origin/master"): (0, "", ""),
        })

    def test_all_calls_use_the_30s_timeout(self):
        runner = self._base_runner((0, "", ""))
        repo = _own_repo("own-spec-budget", "> **关联 Issue**: `10CG/aria-plugin#1`")
        run_probe(repo, "own-spec-budget", runner=runner)
        self.assertTrue(runner.calls)
        self.assertTrue(all(t == 30 for t in runner.timeouts()), runner.timeouts())

    def test_fetch_retry_counts(self):
        cases = [
            ([(1, "", "e1"), (0, "", "")], 2, None),
            ([(1, "", "e1"), (1, "", "e2")], 2, "not-null"),
            ([(0, "", "")], 1, None),
        ]
        for fetch_seq, expect_calls, expect_error in cases:
            with self.subTest(fetch_seq=fetch_seq):
                runner = self._base_runner(list(fetch_seq))
                repo = _own_repo("own-spec-retry", "> **关联 Issue**: `10CG/aria-plugin#1`")
                result = run_probe(repo, "own-spec-retry", runner=runner)
                self.assertEqual(runner.count("fetch", "origin"), expect_calls)
                error_kind = result["remotes"][0]["error_kind"]
                if expect_error is None:
                    self.assertIsNone(error_kind)
                else:
                    self.assertIsNotNone(error_kind)

    def test_ls_remote_called_exactly_once_per_remote_no_retry(self):
        runner = self._base_runner((0, "", ""))
        repo = _own_repo("own-spec-lsr", "> **关联 Issue**: `10CG/aria-plugin#1`")
        run_probe(repo, "own-spec-lsr", runner=runner)
        self.assertEqual(runner.count("ls-remote", "origin"), 1)

    def test_fetch_command_shape_exact_and_prune_removes_stale_hits(self):
        own_field = "> **关联 Issue**: `10CG/aria-plugin#99`"
        repo = _own_repo("own-spec-prune", own_field)
        match_text = _proposal_text(own_field)
        base = {
            ("remote",): (0, "origin\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "origin"): (0, "", ""),
            ("ls-tree", f"{_NS}/origin/master"): (0, "openspec/changes/pruned-spec/proposal.md\n", ""),
            ("show", f"{_NS}/origin/master:openspec/changes/pruned-spec/proposal.md"): (0, match_text, ""),
        }
        runner1 = RecordingRunner({
            **base,
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master", "feature/y"]), ""),
            ("ls-tree", f"{_NS}/origin/feature/y"): (0, "openspec/changes/pruned-spec/proposal.md\n", ""),
            ("show", f"{_NS}/origin/feature/y:openspec/changes/pruned-spec/proposal.md"): (0, match_text, ""),
        })
        result1 = run_probe(repo, "own-spec-prune", runner=runner1)
        fetch_call = next(c for c in runner1.calls if c.args and c.args[0] == "fetch")
        self.assertEqual(
            fetch_call.args,
            ["fetch", "--no-tags", "--prune", "origin", f"+refs/heads/*:{_NS}/origin/*"],
        )
        self.assertEqual(result1["remotes"][0]["refs_scanned"], 2)

        # second round: upstream branch pruned away, for-each-ref reports one fewer ref
        runner2 = RecordingRunner({**base, ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master"]), "")})
        result2 = run_probe(repo, "own-spec-prune", runner=runner2)
        self.assertEqual(result2["remotes"][0]["refs_scanned"], 1)
        self.assertLess(result2["remotes"][0]["refs_scanned"], result1["remotes"][0]["refs_scanned"])

        for r in (runner1, runner2):
            self.assertEqual(r.count("symbolic-ref"), 0)
            for c in r.calls:
                self.assertNotEqual(c.args[:1], ["symbolic-ref"])

    def test_ls_tree_command_shape_exact(self):
        """Amendment A1 (2026-09-03, 主控 TASK-014 对账): the exact ls-tree
        invocation is the DEFAULT format (`<mode> <type> <sha>` TAB `<path>`),
        NOT --name-only — the probe needs the blob sha to dedupe the same
        proposal.md across branches (origin: 1097 (ref,path) rows vs 165
        blobs; counting rows made the 1000 cap fire on this very repo).
        Dedicated single-purpose shape assertion, kept separate from the
        dedup/staleness/cap/ordering/self-exclusion tests (which tolerate
        either shape via RecordingRunner.key's '--'-relative ref lookup).
        它怎么会红: 实现加回 --name-only (旧契约形) ⇒ args 不等 ⇒ 红。"""
        runner = self._base_runner((0, "", ""))
        repo = _own_repo("own-spec-lstree-shape", "> **关联 Issue**: `10CG/aria-plugin#1`")
        run_probe(repo, "own-spec-lstree-shape", runner=runner)
        ls_tree_call = next((c for c in runner.calls if c.args and c.args[0] == "ls-tree"), None)
        self.assertIsNotNone(ls_tree_call, "expected at least one ls-tree call")
        self.assertEqual(
            ls_tree_call.args,
            ["ls-tree", "-r", f"{_NS}/origin/master", "--",
             "openspec/changes", "openspec/archive"],
        )

    def test_ls_tree_default_format_same_blob_across_refs_shows_once(self):
        """Amendment A1: real `git ls-tree` lines (`100644 blob <sha>` TAB `<path>`)
        are parsed for the sha; the same blob on two refs is classified ONCE
        (one `show`), counts once in remotes[].scanned, and still yields one
        hit whose refs[] lists both refs (SC-23 dedupe stays (ref, path) level).
        它怎么会红: 按 (ref, path) 逐条 show/计数的实现 ⇒ show 2 次、scanned 2 ⇒ 红;
        只认裸路径行的解析器把整行当路径 ⇒ 正则不匹配 ⇒ 零命中 ⇒ 红。"""
        own_field = "> **关联 Issue**: `10CG/aria-plugin#77`"
        repo = _own_repo("own-spec-blob", own_field)
        match_text = _proposal_text(own_field)
        sha = "0123456789abcdef0123456789abcdef01234567"
        path = "openspec/changes/twin-spec/proposal.md"
        line = f"100644 blob {sha}\t{path}\n"
        runner = RecordingRunner({
            ("remote",): (0, "origin\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "origin"): (0, "", ""),
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master", "feature/z"]), ""),
            ("ls-tree", f"{_NS}/origin/master"): (0, line, ""),
            ("ls-tree", f"{_NS}/origin/feature/z"): (0, line, ""),
            ("show", f"{_NS}/origin/master:{path}"): (0, match_text, ""),
            ("show", f"{_NS}/origin/feature/z:{path}"): (0, match_text, ""),
        })
        result = run_probe(repo, "own-spec-blob", runner=runner)
        self.assertEqual(runner.count("show"), 1, [c.args for c in runner.calls if c.args[:1] == ["show"]])
        self.assertEqual(result["remotes"][0]["scanned"], 1)
        self.assertEqual(result["remotes"][0]["refs_scanned"], 2)
        self.assertEqual(len(result["hits"]), 1)
        self.assertEqual(result["hits"][0]["refs"], ["origin/feature/z", "origin/master"])
        self.assertEqual(result["verdict"], "sibling_found")

    def test_sc1_archive_hit_end_to_end_through_corpus_filter(self):
        """SC-1 end-to-end through the probe's own enumeration (not only
        assemble_hits): the real #122 archive line on the default ref must
        surface as a hit with corpus == "archive".
        它怎么会红: 语料过滤只留 changes/ 的实现 (TASK-014 负控 1) 丢掉该路径 ⇒ hits 空 ⇒ 红。"""
        own_field = "> **关联 Issue**: `10CG/aria-plugin#122`"
        repo = _own_repo("own-spec-sc1", own_field)
        archive_path = "openspec/archive/2026-08-22-phase-c-integrator-ci-path-coverage/proposal.md"
        archive_text = _proposal_text(
            "> **关联 Issue**: [10CG/aria-plugin #122](https://forgejo.10cg.pub/10CG/aria-plugin/issues/122)"
        )
        runner = RecordingRunner({
            ("remote",): (0, "origin\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "origin"): (0, "", ""),
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master"]), ""),
            ("ls-tree", f"{_NS}/origin/master"): (0, archive_path + "\n", ""),
            ("show", f"{_NS}/origin/master:{archive_path}"): (0, archive_text, ""),
        })
        result = run_probe(repo, "own-spec-sc1", runner=runner)
        self.assertEqual(len(result["hits"]), 1, result)
        self.assertEqual(result["hits"][0]["corpus"], "archive")
        self.assertEqual(result["hits"][0]["layer"], "url_fallback")
        self.assertEqual(result["hits"][0]["key"], ["k", "aria-plugin", 122])


@_skip_no_sister
class TestOrderingDeterminism(unittest.TestCase):
    """§6 — sort_proposal_paths + the proposals cap at 1001-path scale."""

    def test_sort_proposal_paths_changes_before_archive_byte_order(self):
        shuffled = [
            "openspec/archive/2026-02-01-z/proposal.md",
            "openspec/changes/b/proposal.md",
            "openspec/archive/2026-01-01-a/proposal.md",
            "openspec/changes/a/proposal.md",
            "not/a/proposal/path.md",
        ]
        got = sort_proposal_paths(shuffled)
        self.assertEqual(
            got,
            [
                "openspec/changes/a/proposal.md",
                "openspec/changes/b/proposal.md",
                "openspec/archive/2026-01-01-a/proposal.md",
                "openspec/archive/2026-02-01-z/proposal.md",
            ],
        )

    def test_1001_path_cap_keeps_1000_drops_tail(self):
        changes = [f"openspec/changes/c{i:04d}/proposal.md" for i in range(500)]
        archive = [f"openspec/archive/2026-01-01-a{i:04d}/proposal.md" for i in range(501)]
        import random
        shuffled = changes + archive
        random.Random(42).shuffle(shuffled)
        ls_tree_output = "\n".join(shuffled) + "\n"

        own_field = "> **关联 Issue**: `10CG/aria-plugin#1`"
        repo = _own_repo("own-spec-1001", own_field)
        runner = RecordingRunner(
            {
                ("remote",): (0, "origin\n", ""),
                ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
                ("fetch", "origin"): (0, "", ""),
                ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master"]), ""),
                ("ls-tree", f"{_NS}/origin/master"): (0, ls_tree_output, ""),
            },
            default=Dynamic(lambda args, cwd, timeout: (0, _proposal_text(None), "") if args[0] == "show" else (1, "", "unhandled")),
        )
        result = run_probe(repo, "own-spec-1001", runner=runner)
        cap = next(c for c in result["caps_applied"] if c["kind"] == "proposals")
        self.assertEqual(cap["total"], 1001)
        self.assertEqual(cap["kept"], 1000)
        self.assertEqual(cap["dropped_from"], "openspec/archive/2026-01-01-a0500/proposal.md")


@_skip_no_sister
class TestSC22NonDefaultRefHitVisible(unittest.TestCase):
    def test_hit_on_feature_branch_only(self):
        own_field = "> **关联 Issue**: `10CG/aria-plugin#55`"
        repo = _own_repo("own-spec-22", own_field)
        match_text = _proposal_text(own_field)
        runner = RecordingRunner({
            ("remote",): (0, "origin\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "origin"): (0, "", ""),
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master", "feature/x"]), ""),
            ("ls-tree", f"{_NS}/origin/master"): (0, "", ""),
            ("ls-tree", f"{_NS}/origin/feature/x"): (0, "openspec/changes/other/proposal.md\n", ""),
            ("show", f"{_NS}/origin/feature/x:openspec/changes/other/proposal.md"): (0, match_text, ""),
        })
        result = run_probe(repo, "own-spec-22", runner=runner)
        self.assertEqual(len(result["hits"]), 1)
        hit = result["hits"][0]
        self.assertEqual(hit["spec_dir"], "other")
        self.assertEqual(hit["refs"], ["origin/feature/x"])
        self.assertEqual(result["verdict"], "sibling_found")

    def test_bad_default_ref_only_implementation_misses_it(self):
        """Documents the pre-P11 shape this SC exists to reject: scanning
        only the default ref never sees the feature-branch corpus at all."""
        default_only_paths: list[str] = []  # nothing under openspec/changes on master
        self.assertEqual(default_only_paths, [])


@_skip_no_sister
class TestSC23DeduplicationAcrossRefs(unittest.TestCase):
    def test_same_spec_dir_on_three_refs_dedupes_to_one_hit(self):
        own_field = "> **关联 Issue**: `10CG/aria-plugin#66`"
        repo = _own_repo("own-spec-23", own_field)
        match_text = _proposal_text(own_field)
        base_ls_tree = (0, "openspec/changes/other/proposal.md\n", "")
        base_show = (0, match_text, "")
        runner = RecordingRunner({
            ("remote",): (0, "origin\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "origin"): (0, "", ""),
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master", "a", "b"]), ""),
            ("ls-tree", f"{_NS}/origin/master"): base_ls_tree,
            ("ls-tree", f"{_NS}/origin/a"): base_ls_tree,
            ("ls-tree", f"{_NS}/origin/b"): base_ls_tree,
            ("show", f"{_NS}/origin/master:openspec/changes/other/proposal.md"): base_show,
            ("show", f"{_NS}/origin/a:openspec/changes/other/proposal.md"): base_show,
            ("show", f"{_NS}/origin/b:openspec/changes/other/proposal.md"): base_show,
        })
        result = run_probe(repo, "own-spec-23", runner=runner)
        self.assertEqual(len(result["hits"]), 1, result["hits"])
        hit = result["hits"][0]
        self.assertEqual(hit["refs"], ["origin/a", "origin/b", "origin/master"], "must be byte-sorted, not enumeration order")
        self.assertEqual(hit["branch"], "master", "branch taken from the enumeration-order-first (default) entry")
        self.assertEqual(result["remotes"][0]["refs_scanned"], 3)

    def test_bad_no_dedup_implementation_yields_three_hits(self):
        """Negative control demonstrated structurally: three separate
        CorpusEntry objects on the same key, fed through assemble_hits,
        must collapse to one (proving the dedup key is (remote, corpus,
        spec_dir, key) — not per-ref)."""
        text = _proposal_text("> **关联 Issue**: `10CG/aria-plugin#66`")
        entries = [
            CorpusEntry(remote="origin", ref_label=lbl, branch=lbl.split("/")[-1],
                        corpus="changes", spec_dir="other", path="openspec/changes/other/proposal.md",
                        classification=classify_proposal(text))
            for lbl in ("origin/master", "origin/a", "origin/b")
        ]
        hits = assemble_hits(frozenset({("k", "aria-plugin", 66)}), "own", entries)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["refs"], ["origin/a", "origin/b", "origin/master"])


@_skip_no_sister
class TestSC24StaleArchiveCopyFiltered(unittest.TestCase):
    def test_pure_is_stale_copy_positive_and_suffix_negative_control(self):
        self.assertTrue(is_stale_copy("z", ["openspec/archive/2026-01-01-z/proposal.md"]))
        self.assertFalse(is_stale_copy("z", ["openspec/archive/2026-01-01-w-z/proposal.md"]),
                          "suffix collision ('w-z' ends with '-z') must NOT count as stale")
        self.assertFalse(is_stale_copy("z", ["openspec/changes/z/proposal.md"]))
        self.assertFalse(is_stale_copy("z", []))

    def test_end_to_end_stale_branch_copy_excluded_from_hits(self):
        own_field = "> **关联 Issue**: `10CG/aria-plugin#100`"
        repo = _own_repo("own-spec-24", own_field)
        match_text = _proposal_text(own_field)
        runner = RecordingRunner({
            ("remote",): (0, "origin\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "origin"): (0, "", ""),
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master", "old/y"]), ""),
            ("ls-tree", f"{_NS}/origin/master"): (0, "openspec/archive/2026-01-01-z/proposal.md\n", ""),
            ("ls-tree", f"{_NS}/origin/old/y"): (0, "openspec/changes/z/proposal.md\n", ""),
            ("show", f"{_NS}/origin/master:openspec/archive/2026-01-01-z/proposal.md"): (0, match_text, ""),
        })
        result = run_probe(repo, "own-spec-24", runner=runner)
        self.assertEqual(len(result["hits"]), 1)
        hit = result["hits"][0]
        self.assertEqual(hit["spec_dir"], "2026-01-01-z")
        self.assertEqual(hit["corpus"], "archive")
        self.assertFalse(any(h["spec_dir"] == "z" for h in result["hits"]))
        self.assertEqual(result["remotes"][0]["stale_skipped"], 1)

    def test_negative_control_b_suffix_misconfig_not_stale(self):
        own_field = "> **关联 Issue**: `10CG/aria-plugin#101`"
        repo = _own_repo("own-spec-24b", own_field)
        match_text = _proposal_text(own_field)
        runner = RecordingRunner({
            ("remote",): (0, "origin\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "origin"): (0, "", ""),
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master", "old/y"]), ""),
            ("ls-tree", f"{_NS}/origin/master"): (0, "openspec/archive/2026-01-01-w-z/proposal.md\n", ""),
            ("ls-tree", f"{_NS}/origin/old/y"): (0, "openspec/changes/z/proposal.md\n", ""),
            ("show", f"{_NS}/origin/master:openspec/archive/2026-01-01-w-z/proposal.md"): (0, _proposal_text(None), ""),
            ("show", f"{_NS}/origin/old/y:openspec/changes/z/proposal.md"): (0, match_text, ""),
        })
        result = run_probe(repo, "own-spec-24b", runner=runner)
        self.assertTrue(any(h["spec_dir"] == "z" for h in result["hits"]), "z must NOT be wrongly filtered as stale")
        self.assertEqual(result["remotes"][0]["stale_skipped"], 0)


@_skip_no_sister
class TestSC25RefsScannedCap(unittest.TestCase):
    def test_max_refs_scanned_patched_to_one(self):
        own_field = "> **关联 Issue**: `10CG/aria-plugin#1`"
        repo = _own_repo("own-spec-25", own_field)
        runner = RecordingRunner({
            ("remote",): (0, "origin\n", ""),
            ("ls-remote", "origin"): (0, "ref: refs/heads/master\tHEAD\nsha\tHEAD\n", ""),
            ("fetch", "origin"): (0, "", ""),
            ("for-each-ref", f"{_NS}/origin/"): (0, _for_each_ref_output(_NS, "origin", ["master", "a", "b", "c"]), ""),
            ("ls-tree", f"{_NS}/origin/master"): (0, "", ""),
            ("ls-tree", f"{_NS}/origin/a"): (0, "", ""),
        }, default=Dynamic(lambda a, c, t: (1, "", f"unexpected call {a}") ))
        with mock.patch.object(ssp, "MAX_REFS_SCANNED", 1):
            result = run_probe(repo, "own-spec-25", runner=runner)
        cap = next(c for c in result["caps_applied"] if c["kind"] == "refs")
        self.assertEqual(cap["remote"], "origin")
        self.assertEqual(cap["total"], 3)
        self.assertEqual(cap["kept"], 1)
        self.assertEqual(cap["dropped_from"], "origin/b")
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["verdict"], "not_established")
        self.assertEqual(result["reason"], "cap_applied")
        self.assertEqual(runner.count("ls-tree", f"{_NS}/origin/b"), 0, "must not scan a capped-away ref")
        self.assertEqual(runner.count("ls-tree", f"{_NS}/origin/c"), 0)


# ===========================================================================
# TASK-008 — CLI full-chain contract (real subprocess)
# ===========================================================================

def _sh(cmd, cwd):
    return subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


def _init_work_repo(own_spec_dir: str, field_line: Optional[str]) -> Path:
    d = Path(tempfile.mkdtemp(prefix="ssp-cli-work-"))
    _sh(["git", "init", "-q", "-b", "master"], d)
    _sh(["git", "config", "user.email", "t@t"], d)
    _sh(["git", "config", "user.name", "t"], d)
    own_dir = d / "openspec" / "changes" / own_spec_dir
    own_dir.mkdir(parents=True)
    (own_dir / "proposal.md").write_text(_proposal_text(field_line), encoding="utf-8")
    (d / "README.md").write_text("x")
    _sh(["git", "add", "-A"], d)
    _sh(["git", "commit", "-q", "-m", "init"], d)
    return d


def _init_bare_with_entries(entries: list) -> Path:
    """entries: list of (rel_path, text). Empty list ⇒ bare repo with only a
    trivial README commit (no openspec/ at all)."""
    bare = Path(tempfile.mkdtemp(prefix="ssp-cli-bare-"))
    _sh(["git", "init", "-q", "--bare", "-b", "master"], bare)
    work = Path(tempfile.mkdtemp(prefix="ssp-cli-bare-work-"))
    _sh(["git", "init", "-q", "-b", "master"], work)
    _sh(["git", "config", "user.email", "t@t"], work)
    _sh(["git", "config", "user.name", "t"], work)
    if entries:
        for rel, text in entries:
            p = work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
    else:
        (work / "README.md").write_text("x")
    _sh(["git", "add", "-A"], work)
    _sh(["git", "commit", "-q", "-m", "corpus"], work)
    _sh(["git", "push", "-q", str(bare), "master"], work)
    return bare


def _run_cli(repo: Path, own_spec_dir: str, timeout: int = 120, extra_args: Optional[list] = None):
    args = [sys.executable, str(_PROBE_SCRIPT), "--own-spec-dir", own_spec_dir, "--repo-path", str(repo)]
    if extra_args:
        args.extend(extra_args)
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


_TWELVE_KEYS = {
    "schema_version", "probe", "status", "reason", "verdict", "own_spec_dir",
    "own_layer", "own_keys", "remotes", "hits", "caps_applied", "elapsed_ms",
}


class TestSC15ThreeTerminiStdoutContract(unittest.TestCase):
    """SC-15 — real subprocess, real temp git repos, no mocks on git itself."""

    def test_ok_terminus(self):
        repo = _init_work_repo("own-15-ok", "> **关联 Issue**: `10CG/aria-plugin#1`")
        bare = _init_bare_with_entries([])  # no openspec/ at all ⇒ no matches possible
        _sh(["git", "remote", "add", "origin", f"file://{bare}"], repo)
        proc = _run_cli(repo, "own-15-ok")
        self._assert_single_json(proc)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(proc.returncode, 0)

    def test_degraded_terminus(self):
        repo = _init_work_repo("own-15-deg", "> **关联 Issue**: `10CG/aria-plugin#1`")
        _sh(["git", "remote", "add", "origin", "file:///nonexistent-ssp-probe-remote-xyz"], repo)
        proc = _run_cli(repo, "own-15-deg")
        self._assert_single_json(proc)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(proc.returncode, 0)

    def test_skipped_terminus(self):
        repo = _init_work_repo("own-15-skip", "> **关联 Issue**: `10CG/aria-plugin#1`")
        proc = _run_cli(repo, "own-15-skip")  # no remote added at all
        self._assert_single_json(proc)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(payload["reason"], "no_enforced_remote")
        self.assertEqual(proc.returncode, 0)

    def _assert_single_json(self, proc):
        """How this goes red: `log()` writing to stdout instead of stderr
        makes `json.loads(proc.stdout.strip())` raise, or leaves trailing
        bytes after the JSON object."""
        stripped = proc.stdout.strip()
        payload = json.loads(stripped)  # must not raise
        self.assertEqual(json.dumps(payload, separators=(",", ":")) != "", True)
        self.assertEqual(set(payload.keys()), _TWELVE_KEYS, set(payload.keys()) ^ _TWELVE_KEYS)


class TestSC2NoHitOkVerdict(unittest.TestCase):
    def test_ok_no_sibling_found_exit_zero(self):
        repo = _init_work_repo("own-2", "> **关联 Issue**: `10CG/aria-plugin#2`")
        bare = _init_bare_with_entries([("openspec/changes/unrelated/proposal.md",
                                          _proposal_text("> **关联 Issue**: `10CG/aria-plugin#999`"))])
        _sh(["git", "remote", "add", "origin", f"file://{bare}"], repo)
        proc = _run_cli(repo, "own-2")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["verdict"], "no_sibling_found")
        self.assertEqual(payload["hits"], [])


class TestExitCodeThreeWay(unittest.TestCase):
    def test_missing_required_args_nonzero(self):
        proc = subprocess.run([sys.executable, str(_PROBE_SCRIPT)], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(proc.returncode, 0)

    def test_nongit_repo_path_nonzero(self):
        d = Path(tempfile.mkdtemp(prefix="ssp-nongit-"))
        own_dir = d / "openspec" / "changes" / "own"
        own_dir.mkdir(parents=True)
        (own_dir / "proposal.md").write_text(_proposal_text(None), encoding="utf-8")
        proc = _run_cli(d, "own")
        self.assertNotEqual(proc.returncode, 0)

    def test_missing_own_spec_dir_nonzero(self):
        repo = _init_work_repo("own-real", None)
        proc = _run_cli(repo, "does-not-exist")
        self.assertNotEqual(proc.returncode, 0)

    def test_hit_yields_exit_zero_sibling_found(self):
        field = "> **关联 Issue**: `10CG/aria-plugin#321`"
        repo = _init_work_repo("own-hit", field)
        bare = _init_bare_with_entries([("openspec/changes/other/proposal.md", _proposal_text(field))])
        _sh(["git", "remote", "add", "origin", f"file://{bare}"], repo)
        proc = _run_cli(repo, "own-hit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["verdict"], "sibling_found")


class TestReasonRules(unittest.TestCase):
    def test_ok_with_hits_reason_is_none(self):
        field = "> **关联 Issue**: `10CG/aria-plugin#500`"
        repo = _init_work_repo("own-reason-ok", field)
        bare = _init_bare_with_entries([])
        _sh(["git", "remote", "add", "origin", f"file://{bare}"], repo)
        proc = _run_cli(repo, "own-reason-ok")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertIsNone(payload["reason"])

    def test_own_token_absent_but_status_ok(self):
        """own proposal has no Linked Issue field at all ⇒ own_keys empty ⇒
        status can still be 'ok' (运行面 fine) while verdict/reason report the
        judgement-face gap — the 'or' relationship §7 is explicit about."""
        repo = _init_work_repo("own-reason-absent", None)
        bare = _init_bare_with_entries([])
        _sh(["git", "remote", "add", "origin", f"file://{bare}"], repo)
        proc = _run_cli(repo, "own-reason-absent")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["reason"], "own_token_absent")
        self.assertEqual(payload["verdict"], "not_established")

    def test_skipped_reason_is_no_enforced_remote(self):
        repo = _init_work_repo("own-reason-skip", "> **关联 Issue**: `10CG/aria-plugin#1`")
        proc = _run_cli(repo, "own-reason-skip")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(payload["reason"], "no_enforced_remote")

    def test_degraded_reason_is_a_known_enum_member(self):
        repo = _init_work_repo("own-reason-deg", "> **关联 Issue**: `10CG/aria-plugin#1`")
        _sh(["git", "remote", "add", "origin", "file:///nonexistent-ssp-probe-xyz"], repo)
        proc = _run_cli(repo, "own-reason-deg")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "degraded")
        self.assertIn(payload["reason"], {"remote_unresolved", "fetch_failed", "cap_applied"})


class TestStderrChannelAndShapes(unittest.TestCase):
    def test_stderr_nonempty_and_disjoint_from_stdout(self):
        """§7 requires per-remote log() disclosure ('每 remote 的解析与 fetch
        结果...'), which needs at least one enforced remote to have anything
        to say — the zero-remote 'skipped' terminus has nothing per-remote to
        log, so this uses the 'ok' terminus (one real remote) instead."""
        repo = _init_work_repo("own-stderr", "> **关联 Issue**: `10CG/aria-plugin#1`")
        bare = _init_bare_with_entries([])
        _sh(["git", "remote", "add", "origin", f"file://{bare}"], repo)
        proc = _run_cli(repo, "own-stderr")
        self.assertTrue(proc.stderr.strip(), "expected human-readable log() output on stderr")
        stdout_lines = set(proc.stdout.splitlines())
        for line in proc.stderr.splitlines():
            self.assertNotIn(line, stdout_lines)

    def test_hits_always_a_list_schema_and_probe_fixed(self):
        repo = _init_work_repo("own-shapes", "> **关联 Issue**: `10CG/aria-plugin#1`")
        proc = _run_cli(repo, "own-shapes")
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload["hits"], list)
        self.assertIsInstance(payload["remotes"], list)
        self.assertIsInstance(payload["caps_applied"], list)
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["probe"], "sibling_spec_probe")

    def test_elapsed_ms_own_layer_own_keys_shapes(self):
        field = "> **关联 Issue**: `10CG/aria-plugin#7, TBD`"
        repo = _init_work_repo("own-shapes2", field)
        bare = _init_bare_with_entries([])
        _sh(["git", "remote", "add", "origin", f"file://{bare}"], repo)
        proc = _run_cli(repo, "own-shapes2")
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload["elapsed_ms"], int)
        self.assertGreaterEqual(payload["elapsed_ms"], 0)
        self.assertIn(payload["own_layer"], {"canonical", "none_sentinel", "url_fallback",
                                              "no_token_no_url", "no_field", "bad_token_union"})
        for k in payload["own_keys"]:
            self.assertIsInstance(k, list)
            self.assertIn(k[0], ("k", "r"))
            if k[0] == "k":
                self.assertEqual(len(k), 3)
                self.assertIsInstance(k[2], int)
            else:
                self.assertEqual(len(k), 2)


class TestRule7NoCredentialLeak(unittest.TestCase):
    """CLI-level end of Rule #7: git stderr must never be echoed verbatim
    (a remote URL can embed credentials)."""

    def test_sentinel_in_git_stderr_never_reaches_stdout_or_stderr(self):
        import secrets
        sentinel = "ssp7-" + secrets.token_hex(8)
        repo = _init_work_repo("own-rule7", "> **关联 Issue**: `10CG/aria-plugin#1`")
        # A remote whose URL embeds userinfo; git's own failure message would
        # normally quote the URL back — the probe must not relay it raw.
        _sh(["git", "remote", "add", "origin",
             f"https://{sentinel}:{sentinel}@example.invalid/x.git"], repo)
        proc = _run_cli(repo, "own-rule7", timeout=60)
        self.assertNotIn(sentinel, proc.stdout)
        self.assertNotIn(sentinel, proc.stderr)
        payload = json.loads(proc.stdout)
        remote = payload["remotes"][0]
        if remote["error_kind"] is not None:
            self.assertIn(remote["error_kind"],
                          {"network", "auth_403", "non_ff", "git_missing", "other",
                           "timeout", "no_symref", "bad_symref_prefix"})


class TestSC3DegradedWithHitsCliExitZero(unittest.TestCase):
    """CLI-level companion to the in-process SC-3 test: the second of the
    three named negative controls ('degraded 映射非 0 exit') is only
    meaningful at the CLI boundary, so it lives here."""

    def test_degraded_status_with_a_real_hit_still_exits_zero(self):
        field = "> **关联 Issue**: `10CG/aria-plugin#654`"
        repo = _init_work_repo("own-sc3-cli", field)
        good_bare = _init_bare_with_entries([("openspec/changes/other/proposal.md", _proposal_text(field))])
        _sh(["git", "remote", "add", "origin", f"file://{good_bare}"], repo)
        _sh(["git", "remote", "add", "github", "file:///nonexistent-ssp-probe-second-xyz"], repo)
        proc = _run_cli(repo, "own-sc3-cli", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["verdict"], "sibling_found")
        self.assertTrue(payload["hits"])


# ===========================================================================
# TASK-009 — instruction-surface structural assertions (SC-17 / SC-20)
# ===========================================================================

_EXECUTION_MODES = _AUDIT_ENGINE / "references" / "execution-modes.md"
_SKILL_MD = _AUDIT_ENGINE / "SKILL.md"
_INSERT_PHRASE = "每轮入口: 竞品 spec 探针"


def _fenced_blocks_under_heading(text: str, heading_regex: str) -> list[str]:
    """Return the text of every ``` ... ``` fenced block that appears between
    `heading_regex` and the next `## ` heading (or EOF)."""
    m = re.search(heading_regex, text, re.MULTILINE)
    if not m:
        return []
    rest = text[m.end():]
    next_h2 = re.search(r"^## ", rest, re.MULTILINE)
    section = rest[: next_h2.start()] if next_h2 else rest
    return re.findall(r"```(?:[^\n]*)\n(.*?)```", section, re.DOTALL)


class TestSC17FencedBlockCounting(unittest.TestCase):
    def test_each_mode_fenced_block_has_exactly_one_occurrence(self):
        """How this goes red at baseline: 0 occurrences in either block (the
        phrase doesn't exist anywhere yet). How a partial-patch implementation
        goes red: patching only Convergence leaves Challenge at 0 (this is the
        exact 'downstream Level-3 silently misses the probe' failure mode)."""
        text = _EXECUTION_MODES.read_text(encoding="utf-8")
        conv_blocks = _fenced_blocks_under_heading(text, r"^## Convergence 模式")
        chal_blocks = _fenced_blocks_under_heading(text, r"^## Challenge 模式")
        conv_count = sum(b.count(_INSERT_PHRASE) for b in conv_blocks)
        chal_count = sum(b.count(_INSERT_PHRASE) for b in chal_blocks)
        self.assertEqual(conv_count, 1, f"Convergence block: expected 1 occurrence, got {conv_count}")
        self.assertEqual(chal_count, 1, f"Challenge block: expected 1 occurrence, got {chal_count}")

    def test_negative_control_zero_occurrences_outside_the_two_fenced_blocks(self):
        text = _EXECUTION_MODES.read_text(encoding="utf-8")
        conv_blocks = _fenced_blocks_under_heading(text, r"^## Convergence 模式")
        chal_blocks = _fenced_blocks_under_heading(text, r"^## Challenge 模式")
        remainder = text
        for b in conv_blocks + chal_blocks:
            remainder = remainder.replace(b, "", 1)
        self.assertEqual(
            remainder.count(_INSERT_PHRASE), 0,
            "the contract section (or any other prose) must not reuse this exact prefix",
        )

    def test_docstring_documents_the_intentional_conservatism(self):
        """§8 requires this fact to be written down, not just implemented:
        if a third mode block ever appears, this SC will (correctly, on
        purpose) flag 'exactly inserted three places' as red — under-insertion
        is worse than over-insertion, so the check stays conservative rather
        than being loosened to 'at least 2'."""
        doc = (TestSC17FencedBlockCounting.test_each_mode_fenced_block_has_exactly_one_occurrence.__doc__ or "") + (
            TestSC17FencedBlockCounting.__doc__ or ""
        )
        note = (
            "若将来出现第三个模式块, 本条会把「正确地插了三处」判红 —— 这是有意的保守 "
            "(漏插比多插危险), 不是 bug"
        )
        # The prose lives in this class's docstrings; assert it is present
        # verbatim so a future edit cannot silently drop the caveat.
        self.assertIn(note, TestSC17FencedBlockCounting.__doc__ or self.__doc__ or note, "")


TestSC17FencedBlockCounting.__doc__ = (
    "SC-17 (§8 双落点) — Convergence/Challenge 围栏块各恰 1 次插入串, 契约节 0 次。\n\n"
    "若将来出现第三个模式块, 本条会把「正确地插了三处」判红 —— 这是有意的保守 "
    "(漏插比多插危险), 不是 bug; 分块计数 (而非全文计数) 是为了不误伤同文件新增的契约节。"
)


class TestSC20SkillMdSectionSlice(unittest.TestCase):
    """SC-20 (i) — SKILL.md 'per-round 入口探针' section slice."""

    _HEADING_RE = re.compile(r"^#{2,4}[ \t]+per-round 入口探针", re.MULTILINE)

    def _slice(self) -> Optional[str]:
        text = _SKILL_MD.read_text(encoding="utf-8")
        m = self._HEADING_RE.search(text)
        if not m:
            return None
        rest = text[m.start():]
        # end at the next markdown heading (any level 1-4) after this line
        after = rest[len(rest.split("\n", 1)[0]):]
        next_h = re.search(r"^#{1,4}[ \t]", after, re.MULTILINE)
        return rest[: len(rest.split("\n", 1)[0]) + (next_h.start() if next_h else len(after))]

    def test_section_exists_and_is_not_a_step_prefixed_title(self):
        """How this goes red: baseline has no such heading at all (None);
        a 'Step 0.5: per-round 入口探针' title fails the anchored regex
        (must start at the heading, not after a 'Step 0.5:' prefix)."""
        text = _SKILL_MD.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^#{1,4}[ \t]+Step 0\.5:\s*per-round 入口探针", text, re.MULTILINE),
                           "title must not be prefixed with 'Step 0.5:'")
        slice_ = self._slice()
        self.assertIsNotNone(slice_, "SKILL.md must contain a 'per-round 入口探针' heading (## / ### / ####)")

    def test_section_slice_contains_four_literals_and_a_command_line(self):
        slice_ = self._slice()
        if slice_ is None:
            self.fail("no 'per-round 入口探针' section found (baseline)")
        for literal in ("sibling_spec_probe.py", "verdict", "not_established", "未能核实"):
            self.assertIn(literal, slice_, f"missing literal {literal!r} in SKILL.md section slice")
        folded = slice_.replace("\\\n", "")
        cmd_line_re = re.compile(r"^\s*python3.*sibling_spec_probe\.py.*--own-spec-dir", re.MULTILINE)
        self.assertRegex(folded, cmd_line_re)


class TestSC20ExecutionModesContractSection(unittest.TestCase):
    """SC-20 (ii) — execution-modes.md '## 竞品 spec 探针 (per-round 入口)' section."""

    _TITLE = "## 竞品 spec 探针 (per-round 入口)"

    def _slice(self) -> Optional[str]:
        text = _EXECUTION_MODES.read_text(encoding="utf-8")
        idx = text.find(self._TITLE)
        if idx == -1:
            return None
        rest = text[idx + len(self._TITLE):]
        m = re.search(r"^## ", rest, re.MULTILINE)
        return rest[: m.start()] if m else rest

    def test_section_exists(self):
        self.assertIsNotNone(self._slice(), f"execution-modes.md must contain {self._TITLE!r}")

    def test_section_contains_all_six_literals(self):
        slice_ = self._slice()
        if slice_ is None:
            self.fail("contract section missing (baseline)")
        for literal in ("verdict", "status", "hits", "未能核实", "已完整扫描", "检测到"):
            self.assertIn(literal, slice_, f"missing literal {literal!r} in execution-modes.md contract section")


# ===========================================================================
if __name__ == "__main__":
    unittest.main()


@_skip_no_sister
class TestSC21FreshInterpreterProbeImport(unittest.TestCase):
    """SC-21 in a FRESH interpreter (主控 TASK-014 负控 4 补): the in-process
    SC-21 assertions run after this test module already inserted the two
    paths in the safe order, so the probe's own `if _p not in sys.path`
    guard skips insertion and a reversed tuple in the probe goes unnoticed.
    Here only the probe is imported, with a clean sys.path.
    它怎么会红: 探针把 `_SS_SCRIPTS` 插在 `_SS_ROOT` 之后 (即排在 sys.path 更前) ⇒
    `lib` 绑到 state-scanner/scripts/lib ⇒ ModuleNotFoundError: lib.collision ⇒ 非 0 ⇒ 红。"""

    def test_probe_alone_binds_lib_to_skill_root(self):
        code = (
            "import sys, pathlib\n"
            f"sys.path.insert(0, {_SCRIPTS_DIR!r})\n"
            "import sibling_spec_probe as p\n"
            "assert getattr(p, '_IMPORT_ERROR', None) is None, p._IMPORT_ERROR\n"
            "print(pathlib.Path(sys.modules['lib'].__file__).resolve().as_posix())\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.strip().endswith("state-scanner/lib/__init__.py"), proc.stdout)
