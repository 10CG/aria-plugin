"""受控审计 build 宿主（stdlib）。

TASK-004：严格固定来源、首次 genesis、冻结闭包、短锁与 pending 窄恢复。
TASK-008：从固定账本和冻结原字节重放已提交前缀，复用分类/聚合/政策内核。
TASK-010：共享来源投影的 final/check、逐文件原子发布与冻结原生问答处置。
"""
from __future__ import annotations

import argparse
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, NoReturn


Json = dict[str, Any]
SOURCE_NAMES = ("config", "defaults", "executor", "contract", "convergence_algorithm", "report_storage")
IDENTITY_KEYS = ("audit_cycle_id", "client_round_id", "checkpoint", "change_id", "round", "candidate_sha")
BUDGETS = {"single_agent_ms": 120000, "round_ms": 300000, "max_parallel": 2}
EVIDENCE_KEYS = {"schema_version", "cycle_origin", "previous_round", "dispatch_preflight", "policy_inputs",
                 "post_audit_index_path", "post_drift_index_path", "post_disposition_index_path"}
MANIFEST_KEYS = set(IDENTITY_KEYS) | {"attempt_index", "roles", "require_same_admitted_roles", "evidence"} | set(BUDGETS)
OVERRIDES = {"model", "agents_config", "team", "teams", "mode", "backend", "model_override", "additional_agents"}
CHECKPOINTS = {"post_brainstorm", "post_spec", "post_planning", "mid_implementation", "mid_post_spec",
               "post_implementation", "pre_merge", "post_closure"}


class ExecutorError(Exception):
    def __init__(self, error_code: str, reason: str = "", input_ref: str = ""):
        super().__init__(error_code)
        self.error_code = error_code
        self.reason = reason
        self.input_ref = input_ref


def _fail(code: str, reason: str, path: Any = "") -> NoReturn:
    raise ExecutorError(code, reason, str(path))


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse(data: bytes, path: Path, code: str = "E_INPUT_SCHEMA") -> Any:
    def pairs(items: list[tuple[str, Any]]) -> Json:
        result: Json = {}
        for key, value in items:
            if key in result:
                _fail(code, "duplicate_json_key", path)
            result[key] = value
        return result

    def number(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            _fail(code, "nonfinite_json_number", path)
        return parsed

    def invalid_constant(_: str) -> Any:
        return _fail(code, "nonfinite_json_number", path)

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                          parse_float=number, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        return _fail(code, "invalid_json", path)


def _keys(value: Any, expected: set[str], code: str, reason: str, path: Any = "") -> None:
    if not isinstance(value, dict) or set(value) != expected:
        _fail(code, reason, path)


def _integer(value: Any, minimum: int = 0, code: str = "E_INPUT_SCHEMA") -> None:
    if type(value) is not int or value < minimum:
        _fail(code, "integer_required")


def _id(value: Any, code: str = "E_INPUT_SCHEMA") -> None:
    if not isinstance(value, str) or not value.strip():
        _fail(code, "nonempty_string_required")


def _version(value: Any, code: str = "E_POLICY_SOURCE") -> None:
    if type(value) is not int or value != 1:
        _fail(code, "schema_version")


def _ref_shape(value: Any, code: str = "E_POLICY_SOURCE") -> None:
    _keys(value, {"path", "sha256"}, code, "file_ref")
    _id(value["path"], code)
    if not isinstance(value["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None:
        _fail(code, "file_ref_hash")


def _path(value: str, carrier: Path) -> Path:
    path = Path(value)
    return Path(os.path.abspath(path if path.is_absolute() else carrier.parent / path))


class _Inputs:
    """同次输入按 origin 保存原字节；连续两次读取，不把 hash 当真实性签名。"""
    def __init__(self) -> None:
        self.raw: dict[str, bytes] = {}

    def read(self, path: Path, code: str = "E_POLICY_SOURCE") -> bytes:
        try:
            first = path.read_bytes()
            second = path.read_bytes()
        except OSError:
            return _fail(code, "source_unreadable", path)
        if first != second:
            _fail(code, "source_unstable", path)
        origin = str(path)
        if origin in self.raw and self.raw[origin] != first:
            _fail(code, "source_changed_during_capture", path)
        self.raw[origin] = first
        return first

    def reference(self, path: Path, code: str = "E_POLICY_SOURCE") -> Json:
        return {"path": str(path), "sha256": _hash(self.read(path, code))}

    def dereference(self, value: Any, carrier: Path, code: str = "E_POLICY_SOURCE") -> tuple[Path, bytes]:
        _ref_shape(value, code)
        path = _path(value["path"], carrier)
        raw = self.read(path, code)
        if _hash(raw) != value["sha256"]:
            _fail(code, "source_hash_mismatch", path)
        return path, raw


def _fixed_paths(repo: Path) -> dict[str, Path]:
    engine = Path(__file__).resolve().parents[1]
    return {"config": repo / ".aria" / "config.json",
            "defaults": engine.parent / "config-loader" / "DEFAULTS.json",
            "executor": Path(__file__).resolve(),
            "contract": engine / "references" / "executor-contract.md",
            "convergence_algorithm": engine / "references" / "convergence-algorithm.md",
            "report_storage": engine / "references" / "report-storage.md"}


def _merge(defaults: Json, project: Json) -> Json:
    merged = dict(defaults)
    for key, value in project.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_fixed_policy(repo_path: Path, inputs: _Inputs | None = None) -> Json:
    inputs = inputs if inputs is not None else _Inputs()
    repo = Path(repo_path).resolve()
    paths = _fixed_paths(repo)
    raw: Json = {}
    source_refs: Json = {}
    for name in ("defaults", "config"):
        path = paths[name]
        if name == "config" and not isinstance(inputs, _FrozenInputs):
            try:
                path.stat()
            except FileNotFoundError:
                raw[name] = {}
                continue
            except OSError:
                _fail("E_CONFIG_SOURCE", "source_unreadable", path)
        data = inputs.read(path, "E_CONFIG_SOURCE")
        value = _parse(data, path)
        if not isinstance(value, dict) or ("audit" in value and not isinstance(value["audit"], dict)):
            _fail("E_INPUT_SCHEMA", "config_object_required", path)
        audit = value.get("audit", {})
        if "require_same_admitted_roles" in audit and type(audit["require_same_admitted_roles"]) is not bool:
            _fail("E_CONFIG_TYPE", "raw_guard_not_boolean", path)
        if name == "defaults" and audit.get("require_same_admitted_roles") is not False:
            _fail("E_CONFIG_SOURCE", "defaults_guard_registration", path)
        raw[name] = value
        source_refs[name] = {"path": str(path), "sha256": _hash(data)}
    merged = _merge(raw["defaults"], raw["config"])
    return {"require_same_admitted_roles": merged["audit"]["require_same_admitted_roles"],
            "audit": merged["audit"], "raw": raw, "sources": source_refs, "paths": paths}


def _source_field(policy: Json, parts: list[str], value: Any) -> Json:
    name = "defaults"
    node: Any = policy["raw"]["config"]
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            break
        node = node[part]
    else:
        name = "config"
    pointer = "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)
    return {"value": value, "source": policy["sources"][name], "pointer": pointer}


def _validate_manifest(manifest: Any) -> None:
    if isinstance(manifest, dict) and OVERRIDES.intersection(manifest):
        _fail("E_UNSUPPORTED", "caller_override")
    _keys(manifest, MANIFEST_KEYS, "E_INPUT_SCHEMA", "manifest_keys")
    for key in IDENTITY_KEYS:
        if key == "round":
            _integer(manifest[key], 1)
        else:
            _id(manifest[key])
    _integer(manifest["attempt_index"], 1)
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", manifest["candidate_sha"]) is None:
        _fail("E_INPUT_SCHEMA", "full_git_object_id_required")
    if manifest["checkpoint"] not in CHECKPOINTS:
        _fail("E_INPUT_SCHEMA", "unknown_checkpoint")
    if Path(manifest["change_id"]).name != manifest["change_id"] or manifest["change_id"] in (".", ".."):
        _fail("E_INPUT_SCHEMA", "change_id_path")
    if type(manifest["require_same_admitted_roles"]) is not bool:
        _fail("E_INPUT_SCHEMA", "manifest_guard_boolean")
    for key, expected in BUDGETS.items():
        _integer(manifest[key], 1)
        if manifest[key] != expected:
            _fail("E_MANIFEST_MISMATCH", "budget_mismatch")
    roles = manifest["roles"]
    if not isinstance(roles, list) or not roles:
        _fail("E_INPUT_SCHEMA", "roles_required")
    for role in roles:
        if isinstance(role, dict) and OVERRIDES.intersection(role):
            _fail("E_UNSUPPORTED", "caller_override")
        _keys(role, {"role_id", "agentType", "model_alias", "prompt"}, "E_INPUT_SCHEMA", "role_keys")
        for key in ("role_id", "agentType", "model_alias"):
            _id(role[key])
        if not isinstance(role["prompt"], str):
            _fail("E_INPUT_SCHEMA", "prompt_string_required")
    evidence = manifest["evidence"]
    _keys(evidence, EVIDENCE_KEYS, "E_INPUT_SCHEMA", "evidence_keys")
    _version(evidence["schema_version"], "E_INPUT_SCHEMA")
    for key in ("cycle_origin", "previous_round", "dispatch_preflight", "policy_inputs"):
        if evidence[key] is not None or key == "policy_inputs":
            _ref_shape(evidence[key], "E_INPUT_SCHEMA")
    for key in EVIDENCE_KEYS:
        if key.endswith("_path"):
            _id(evidence[key])


def _proposal_path(repo: Path, change: str) -> Path:
    current = repo / "openspec" / "changes" / change / "proposal.md"
    archived: list[Path] = []
    archive = repo / "openspec" / "archive"
    if archive.exists():
        archived = sorted(p / "proposal.md" for p in archive.iterdir()
                          if p.is_dir() and (p.name == change or p.name.endswith("-" + change))
                          and (p / "proposal.md").exists())
    if current.exists():
        if archived:
            _fail("E_POLICY_SOURCE", "ambiguous_proposal", current)
        return current
    if len(archived) > 1:
        _fail("E_POLICY_SOURCE", "ambiguous_proposal", archive)
    return archived[0] if archived else current


def _effective_policy(policy: Json, manifest: Json, repo: Path, inputs: _Inputs,
                      proposal_source: Path | None = None) -> Json:
    audit = policy["audit"]
    cp = manifest["checkpoint"]
    if manifest["require_same_admitted_roles"] != policy["require_same_admitted_roles"]:
        _fail("E_MANIFEST_MISMATCH", "guard_mismatch")
    if not policy["require_same_admitted_roles"]:
        _fail("E_UNSUPPORTED", "guard_disabled_use_legacy")
    teams = policy["raw"]["config"].get("audit", {}).get("teams")
    if not isinstance(teams, dict):
        _fail("E_UNSUPPORTED", "explicit_team_required", policy["paths"]["config"])
    explicit = teams.get(cp)
    if (not isinstance(explicit, list) or not explicit or
            any(not isinstance(role, str) or not role.strip() for role in explicit) or
            len(set(explicit)) != len(explicit)):
        _fail("E_UNSUPPORTED", "explicit_team_required")
    if ([role["role_id"] for role in manifest["roles"]] != explicit or
            [role["agentType"] for role in manifest["roles"]] != explicit):
        _fail("E_MANIFEST_MISMATCH", "team_mismatch")
    checkpoints = audit.get("checkpoints")
    if not isinstance(checkpoints, dict):
        _fail("E_POLICY_SOURCE", "checkpoint_config")
    mode = checkpoints.get(cp)
    mode_parts = ["audit", "checkpoints", cp]
    if mode == "on":
        mode = audit.get("mode")
        mode_parts = ["audit", "mode"]
    mode_evidence: list[Json] = [_source_field(policy, mode_parts, mode)]
    if mode == "adaptive":
        proposal = proposal_source if proposal_source is not None else _proposal_path(repo, manifest["change_id"])
        try:
            text = inputs.read(proposal).decode("utf-8")
        except UnicodeError:
            _fail("E_POLICY_SOURCE", "invalid_proposal_utf8", proposal)
        levels: set[int] = set()
        for line in text.splitlines():
            if re.search(r"(?i)level|规格等级|spec.level", line):
                for match in re.finditer(r"(?i)level\s*[:：]?\s*([123])|\b(full|standard|skip)\b", line):
                    levels.add(int(match[1]) if match[1] else {"full": 3, "standard": 2, "skip": 1}[match[2].lower()])
        if len(levels) != 1:
            _fail("E_POLICY_SOURCE", "spec_level_unverifiable", proposal)
        level = next(iter(levels))
        rules = audit.get("adaptive_rules")
        if not isinstance(rules, dict):
            _fail("E_POLICY_SOURCE", "adaptive_rules")
        mode = rules.get(f"level_{level}")
        mode_evidence.extend([{"source": inputs.reference(proposal), "level": level},
                              _source_field(policy, ["audit", "adaptive_rules", f"level_{level}"], mode)])
    if audit.get("enabled") is not True or mode != "convergence":
        _fail("E_UNSUPPORTED", "convergence_required")
    _integer(audit.get("max_rounds"), 1, "E_POLICY_SOURCE")
    drift = audit.get("drift_guard")
    if not isinstance(drift, dict):
        _fail("E_POLICY_SOURCE", "drift_config")
    for key in ("warn_threshold", "refocus_threshold"):
        value = drift.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            _fail("E_POLICY_SOURCE", "drift_threshold")
    if drift["warn_threshold"] > drift["refocus_threshold"] or type(drift.get("convergence_mode")) is not bool:
        _fail("E_POLICY_SOURCE", "drift_config")
    criteria = audit.get("convergence_criteria")
    if not isinstance(criteria, dict) or any(type(criteria.get(k)) is not bool for k in ("conclusion_match", "unanimous_pass")):
        _fail("E_POLICY_SOURCE", "convergence_criteria")
    result = {key: _source_field(policy, ["audit", key], audit.get(key)) for key in
              ("enabled", "require_same_admitted_roles", "mode", "max_rounds")}
    # 每个叶子单独标源，避免将部分 project override 的整个合并对象误标成单一源。
    result["checkpoint"] = _source_field(policy, ["audit", "checkpoints", cp], checkpoints[cp])
    result["teams"] = _source_field(policy, ["audit", "teams", cp], explicit)
    for key in ("drift_guard", "convergence_criteria", "adaptive_rules"):
        value = audit.get(key)
        if not isinstance(value, dict):
            _fail("E_POLICY_SOURCE", "policy_object_required")
        result[key] = {field: _source_field(policy, ["audit", key, field], item) for field, item in value.items()}
    result["resolved_mode"] = {"value": mode, "evidence": mode_evidence}
    return result


def _safe_write_path(path: Path, allowed: Path) -> Path:
    path = Path(os.path.abspath(path))
    allowed = Path(os.path.abspath(allowed))
    if not path.is_relative_to(allowed):
        _fail("E_OUTPUT_CONFLICT", "path_escape", path)
    for part in [path, *path.parents]:
        if part.is_symlink():
            _fail("E_OUTPUT_CONFLICT", "symlink_write_path", part)
    if path.resolve() != path:
        _fail("E_OUTPUT_CONFLICT", "noncanonical_write_path", path)
    return path


def _publish(path: Path, raw: bytes, allowed: Path, resume: bool = False) -> Json:
    path = _safe_write_path(path, allowed)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if resume and path.is_file() and path.read_bytes() == raw:
            return {"path": str(path), "sha256": _hash(raw)}
        _fail("E_OUTPUT_CONFLICT", "existing_output", path)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".publish-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # link 为排他发布；不存在 replace/覆盖窗口。
        os.link(temporary, path)
    except FileExistsError:
        _fail("E_OUTPUT_CONFLICT", "concurrent_output", path)
    except OSError:
        _fail("E_OUTPUT_CONFLICT", "publish_failed", path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"path": str(path), "sha256": _hash(raw)}


@contextmanager
def _writer_lock(scope: Path) -> Generator[None, None, None]:
    try:
        import fcntl
    except ImportError:
        _fail("E_UNSUPPORTED", "posix_flock_required", scope)
    _safe_write_path(scope, scope.parent)
    scope.mkdir(parents=True, exist_ok=True)
    lock_path = _safe_write_path(scope / "writer.lock", scope)
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except (OSError, AttributeError):
        _fail("E_UNSUPPORTED", "posix_lock_open", lock_path)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _fail("E_SCOPE_BUSY", "writer_lock_busy", lock_path)
        except OSError:
            _fail("E_UNSUPPORTED", "posix_flock_required", lock_path)
        yield
    finally:
        os.close(fd)


def _freeze_blob(raw: bytes, scope: Path) -> Json:
    return _publish(scope / "blobs" / (_hash(raw) + ".blob"), raw, scope, resume=True)


def _freeze_closure(inputs: _Inputs, scope: Path, output: Path, *, resume: bool = False) -> Json:
    entries = [{"origin": origin, "sha256": _hash(raw), "blob": _freeze_blob(raw, scope)}
               for origin, raw in sorted(inputs.raw.items())]
    value = {"schema_version": 1, "algorithm_version": "canonical_v1", "sources": entries}
    return _publish(output, _canonical(value), output.parent, resume=resume)


def _span(value: Any, carrier: Path, inputs: _Inputs) -> tuple[str, Path]:
    _keys(value, {"source", "start", "end"}, "E_POLICY_SOURCE", "span_keys")
    _integer(value["start"], 0, "E_POLICY_SOURCE")
    _integer(value["end"], value["start"], "E_POLICY_SOURCE")
    path, raw = inputs.dereference(value["source"], carrier)
    if value["end"] > len(raw):
        _fail("E_POLICY_SOURCE", "span_bounds", path)
    try:
        # 解码前缀/后缀也验证边界；不允许截在多字节 UTF-8 中间。
        raw[:value["start"]].decode("utf-8")
        text = raw[value["start"]:value["end"]].decode("utf-8")
        raw[value["end"]:].decode("utf-8")
    except UnicodeError:
        return _fail("E_POLICY_SOURCE", "span_utf8_boundary", path)
    return text, path


def _has_goal(raw: bytes, kind: str, path: Path) -> bool:
    if kind in ("issue_title", "pr_title"):
        value = _parse(raw, path, "E_POLICY_SOURCE")
        if not isinstance(value, dict) or "title" not in value or (value["title"] is not None and not isinstance(value["title"], str)):
            _fail("E_POLICY_SOURCE", "title_response_required", path)
        return isinstance(value["title"], str) and bool(value["title"].strip())
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        return _fail("E_POLICY_SOURCE", "fallback_utf8", path)
    match = re.search(r"(?im)^#{1,6}\s+(?:Why|Goal|目标|已确认决策)\s*\n([^#]+)", text)
    return match is not None and bool(match[1].strip())


def _freeze_policy_inputs(repo: Path, manifest: Json, manifest_path: Path,
                          inputs: _Inputs, scope: Path) -> tuple[Json, Json]:
    policy_path, data = inputs.dereference(manifest["evidence"]["policy_inputs"], manifest_path)
    policy = _parse(data, policy_path, "E_POLICY_SOURCE")
    _keys(policy, {"schema_version", "context", "spec_source", "anchor_selection", "fallback_sources"},
          "E_POLICY_SOURCE", "policy_input_keys", policy_path)
    _version(policy["schema_version"])
    context, _ = inputs.dereference(policy["context"], policy_path)
    proposal = _proposal_path(repo, manifest["change_id"])
    if policy["spec_source"] is not None:
        spec, _ = inputs.dereference(policy["spec_source"], policy_path)
        if spec != proposal:
            _fail("E_POLICY_SOURCE", "spec_source_not_fixed", spec)
    elif proposal.exists():
        _fail("E_POLICY_SOURCE", "spec_source_required", proposal)
    selection = policy["anchor_selection"]
    _keys(selection, {"primary_goal", "in_scope", "out_of_scope_hints"}, "E_POLICY_SOURCE", "anchor_selection_keys")
    primary = ""
    selected_path: Path | None = None
    if selection["primary_goal"] is not None:
        primary, selected_path = _span(selection["primary_goal"], policy_path, inputs)
        if not primary.strip():
            _fail("E_POLICY_SOURCE", "empty_primary_goal")
    scopes: Json = {}
    for key in ("in_scope", "out_of_scope_hints"):
        if not isinstance(selection[key], list):
            _fail("E_POLICY_SOURCE", "scope_spans_required")
        scopes[key] = [_span(span, policy_path, inputs)[0] for span in selection[key]]
    fallback = policy["fallback_sources"]
    if not isinstance(fallback, list) or not fallback:
        _fail("E_POLICY_SOURCE", "fallback_sources_required")
    first_kind = "decisions" if manifest["checkpoint"] == "post_brainstorm" else "proposal"
    first_locator = context if first_kind == "decisions" else proposal
    observations: list[Json] = []
    expected_order = [first_kind, "issue_title", "pr_title"]
    selected = False
    for index, entry in enumerate(fallback):
        _keys(entry, {"kind", "locator", "source"}, "E_POLICY_SOURCE", "fallback_keys")
        if index >= len(expected_order) or entry["kind"] != expected_order[index]:
            _fail("E_POLICY_SOURCE", "fallback_order")
        _id(entry["locator"], "E_POLICY_SOURCE")
        locator = _path(entry["locator"], policy_path)
        if index == 0 and locator != first_locator:
            _fail("E_POLICY_SOURCE", "fallback_fixed_locator", locator)
        try:
            raw = locator.read_bytes()
            second = locator.read_bytes()
        except FileNotFoundError:
            if index > 0 or entry["source"] is not None:
                _fail("E_POLICY_SOURCE", "title_capture_or_source_required", locator)
            observations.append({"kind": entry["kind"], "locator": str(locator), "outcome": "missing", "source": None})
            continue
        except OSError:
            _fail("E_POLICY_SOURCE", "fallback_unreadable", locator)
        if raw != second or entry["source"] is None:
            _fail("E_POLICY_SOURCE", "fake_missing_or_unstable_fallback", locator)
        source_path, source_raw = inputs.dereference(entry["source"], policy_path)
        if source_path != locator or raw != source_raw:
            _fail("E_POLICY_SOURCE", "fallback_source_mismatch", locator)
        has_goal = _has_goal(raw, entry["kind"], locator)
        chosen = selected_path == locator and bool(primary)
        if chosen:
            selected = True
        if has_goal and not chosen:
            _fail("E_POLICY_SOURCE", "anchor_selection_required", locator)
        observations.append({"kind": entry["kind"], "locator": str(locator),
                             "outcome": "read" if chosen else "no_anchor", "source": inputs.reference(locator)})
        if chosen:
            if index != len(fallback) - 1:
                _fail("E_POLICY_SOURCE", "fallback_after_selection")
            break
    if not selected and (len(fallback) != len(expected_order) or primary or any(scopes.values())):
        _fail("E_POLICY_SOURCE", "all_applicable_fallbacks_required")
    observation_ref = _freeze_blob(_canonical({"schema_version": 1, "observations": observations}), scope)
    inputs.read(Path(observation_ref["path"]))
    anchor_value: Json | None = None
    if selected:
        result = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
                                capture_output=True, check=False)
        sha = result.stdout.decode("ascii", errors="replace").strip()
        if result.returncode or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha) is None:
            _fail("E_POLICY_SOURCE", "anchor_git_object_unavailable", repo)
        anchor_value = {"checkpoint": manifest["checkpoint"], "primary_goal": primary, **scopes, "source_sha": sha}
    anchor = {"schema_version": 1, "status": "present" if selected else "missing",
              "value": anchor_value, "observations": observation_ref}
    anchor_ref = _freeze_blob(_canonical(anchor), scope)
    inputs.read(Path(anchor_ref["path"]))
    return _freeze_blob(data, scope), anchor_ref


def _origin_observation(repo: Path, scope: Path, manifest: Json, inputs: _Inputs,
                        manifest_path: Path) -> Json:
    reports = repo / ".aria" / "audit-reports"
    cp, change = manifest["checkpoint"], manifest["change_id"]
    # 只绑定显式本次输入的 origin/hash；其它同形或同字节文件仍须归属检查。
    current_manifest = inputs.reference(manifest_path)
    known: set[str] = {change}

    def scan_error(error: OSError) -> NoReturn:
        _fail("E_POLICY_SOURCE", "historical_scan_unreadable", error.filename or reports)

    for directory in (repo / "openspec" / "changes", repo / "openspec" / "archive"):
        try:
            known.update(re.sub(r"^\d{4}-\d{2}-\d{2}-", "", p.name)
                         if directory.name == "archive" else p.name
                         for p in directory.iterdir() if p.is_dir())
        except FileNotFoundError:
            continue
        except OSError as error:
            scan_error(error)
    files: list[Json] = []
    if reports.exists():
        for directory, children, names in os.walk(reports, followlinks=False, onerror=scan_error):
            for child in children:
                path = Path(directory) / child
                if path.is_symlink():
                    _fail("E_POLICY_SOURCE", "historical_symlink_unattributed", path)
            children[:] = sorted(name for name in children if name not in ("fixtures", "fixture")
                                 and Path(directory) / name != scope)
            for name in sorted(names):
                path = Path(directory) / name
                if path.is_symlink():
                    _fail("E_POLICY_SOURCE", "historical_symlink_unattributed", path)
                raw = inputs.read(path)
                if str(path) == current_manifest["path"] and _hash(raw) == current_manifest["sha256"]:
                    continue
                belongs = False
                attribution = "UNKNOWN"
                if name.endswith(".json"):
                    value = _parse(raw, path, "E_POLICY_SOURCE")
                    if isinstance(value, dict):
                        identity = value.get("identity", value)
                        if isinstance(identity, dict) and "checkpoint" in identity and "change_id" in identity:
                            belongs = identity["checkpoint"] == cp and identity["change_id"] == change
                            attribution = "SAME_SCOPE" if belongs else "OTHER_SCOPE"
                elif name.endswith(".md"):
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeError:
                        _fail("E_POLICY_SOURCE", "historical_utf8", path)
                    stem = name[:-3]
                    hit = f"-{change}-" in f"-{stem}-"
                    excluded = any(other != change and f"-{change}-" in f"-{other}-" and
                                   f"-{other}-" in f"-{stem}-" for other in known)
                    cp_match = re.search(r"(?m)^checkpoint:\s*([^\s]+)\s*$", text)
                    context_match = re.search(r"(?m)^context:\s*(.+?)\s*$", text)
                    context_id = context_match[1].strip("\"'") if context_match else None
                    context_hit = context_id in (change, f"openspec/changes/{change}/proposal.md",
                                                  str(repo / "openspec" / "changes" / change / "proposal.md"))
                    prefix_cp = next((c for c in CHECKPOINTS if name.startswith(c + "-")), None)
                    if cp_match and prefix_cp and cp_match[1] != prefix_cp:
                        _fail("E_POLICY_SOURCE", "historical_checkpoint_conflict", path)
                    actual_cp = cp_match[1] if cp_match else prefix_cp
                    if hit and not excluded and actual_cp == cp and context_id is not None and not context_hit:
                        _fail("E_POLICY_SOURCE", "historical_change_conflict", path)
                    belongs = actual_cp == cp and ((hit and not excluded) or context_hit)
                    if actual_cp is not None and (hit or context_hit):
                        attribution = "SAME_SCOPE" if belongs else "OTHER_SCOPE"
                if belongs:
                    _fail("E_PREVIOUS_IDENTITY", "existing_scope_history_no_migration", path)
                files.append({"file": {"path": str(path), "sha256": _hash(raw)}, "attribution": attribution})
    return {"schema_version": 1, "checkpoint": cp, "change_id": change, "files": files,
            "warnings": [{"code": "UNKNOWN", "file": item["file"]} for item in files if item["attribution"] == "UNKNOWN"]}


def _load_scope(scope: Path, manifest: Json, inputs: _Inputs) -> Json:
    genesis_path = scope / "genesis.json"
    event_dir = scope / "events"
    if not genesis_path.exists():
        if manifest["evidence"]["cycle_origin"] is not None or (event_dir.exists() and any(event_dir.iterdir())):
            _fail("E_PREVIOUS_IDENTITY", "missing_genesis_with_history", scope)
        if (scope / "blobs").exists() and any((scope / "blobs").iterdir()):
            _fail("E_POLICY_SOURCE", "incomplete_bootstrap_requires_review", scope)
        return {"genesis": None, "genesis_ref": None, "events": [], "head": None, "pending": None, "reserve_count": 0}
    raw = inputs.read(genesis_path)
    genesis = _parse(raw, genesis_path, "E_POLICY_SOURCE")
    _keys(genesis, {"schema_version", "algorithm_version", "audit_cycle_id", "checkpoint", "change_id",
                    "policy_inputs", "anchor", "origin_observation", "initial_sources", "initial_max_rounds"},
          "E_POLICY_SOURCE", "genesis_keys", genesis_path)
    _version(genesis["schema_version"])
    _integer(genesis["initial_max_rounds"], 1, "E_POLICY_SOURCE")
    if genesis["algorithm_version"] != "canonical_v1":
        _fail("E_POLICY_SOURCE", "algorithm_version", genesis_path)
    if any(genesis[key] != manifest[key] for key in ("audit_cycle_id", "checkpoint", "change_id")):
        _fail("E_PREVIOUS_IDENTITY", "genesis_identity", genesis_path)
    genesis_ref = {"path": str(genesis_path), "sha256": _hash(raw)}
    for key in ("policy_inputs", "anchor", "origin_observation"):
        inputs.dereference(genesis[key], genesis_path)
    _keys(genesis["initial_sources"], set(SOURCE_NAMES), "E_POLICY_SOURCE", "genesis_sources")
    for source in genesis["initial_sources"].values():
        inputs.dereference(source, genesis_path)
    events: list[Json] = []
    head: Json | None = None
    pending: Json | None = None
    if event_dir.exists():
        for seq, path in enumerate(sorted(event_dir.iterdir()), 1):
            if path.name != f"{seq:010d}.json":
                _fail("E_PREVIOUS_IDENTITY", "event_sequence", path)
            event_raw = inputs.read(path)
            event = _parse(event_raw, path, "E_POLICY_SOURCE")
            _keys(event, {"schema_version", "seq", "genesis", "previous_event", "kind", "payload"},
                  "E_POLICY_SOURCE", "event_keys", path)
            _version(event["schema_version"])
            if type(event["seq"]) is not int or event["seq"] != seq or event["genesis"] != genesis_ref or event["previous_event"] != head:
                _fail("E_PREVIOUS_IDENTITY", "event_chain", path)
            if event["kind"] not in ("reserve", "commit", "observe", "disposition") or not isinstance(event["payload"], dict):
                _fail("E_PREVIOUS_IDENTITY", "event_kind", path)
            event_ref = {"path": str(path), "sha256": _hash(event_raw)}
            if event["kind"] == "reserve":
                _keys(event["payload"], {"identity", "attempt_index", "manifest", "workflow_script", "previous_round", "previous_attempt"},
                      "E_POLICY_SOURCE", "reservation_keys", path)
                if pending is not None:
                    _fail("E_PREVIOUS_IDENTITY", "multiple_pending", path)
                pending = {"event": event, "ref": event_ref}
            elif event["kind"] == "commit":
                # 完整语义由后续共享重算宿主实现；绝不直接使用 result.policy。
                pending = None
            elif event["kind"] == "observe":
                _keys(event["payload"], {"preflight"}, "E_NATIVE_EVIDENCE", "observe_payload", path)
                _read_preflight(event["payload"]["preflight"], path, _StoredObserveInputs(scope))
            events.append({"event": event, "ref": event_ref})
            head = event_ref
    return {"genesis": genesis, "genesis_ref": genesis_ref, "events": events, "head": head, "pending": pending,
            "reserve_count": sum(entry["event"]["kind"] == "reserve" for entry in events)}


RESULT_INPUTS = {'manifest', 'build_record', 'config', 'defaults', 'workflow_script', 'native_record',
                 'genesis', 'reservation', 'input_closure', 'audit_index', 'policy_request',
                 'prepare_record', 'publication_record', 'prefix_head', 'previous_round',
                 'previous_attempt', 'drift_index'}
RESULT_KEYS = {'schema_version', 'identity', 'budgets', 'inputs', 'attempt_index', 'workflow_run_id',
               'workflow_script_sha256', 'clock', 'require_same_admitted_roles', 'configured_roles',
               'dispatched_roles', 'admitted_roles', 'roles', 'conclusions', 'comparison_keys',
               'conclusion_keys_equal', 'population_comparable', 'population_reason', 'incomplete',
               'all_failed_void', 'unanimous_pass', 'conclusions_stable', 'converged', 'policy',
               'verdict', 'next_round_dispatch_allowed', 'generated_at'}


ROUND_METADATA_KEYS = {
    'prepare': {'schema_version', 'identity', 'attempt_index', 'audit_index', 'input_closure',
                'policy_request', 'policy_script', 'generated_at', 'host_prepare_duration_ms'},
    'publication': {'schema_version', 'identity', 'attempt_index', 'generated_at', 'host_collect_duration_ms'},
}


def _validate_round_metadata(value: Any, kind: str, carrier: Path, *,
                             identity: Json | None = None, attempt_index: int | None = None) -> Json:
    """Use one closed metadata contract in publication, projection and history."""
    code = 'E_POLICY_SOURCE'
    if kind not in ROUND_METADATA_KEYS:
        _fail(code, 'round_metadata_kind', carrier)
    _keys(value, ROUND_METADATA_KEYS[kind], code, 'round_metadata_keys', carrier)
    _version(value['schema_version'], code)
    _integer(value['attempt_index'], 1, code)
    duration = 'host_prepare_duration_ms' if kind == 'prepare' else 'host_collect_duration_ms'
    _integer(value[duration], 0, code)
    _id(value['generated_at'], code)
    _keys(value['identity'], set(IDENTITY_KEYS), code, 'round_metadata_identity_keys', carrier)
    _integer(value['identity']['round'], 1, code)
    for key in IDENTITY_KEYS:
        if key != 'round':
            _id(value['identity'][key], code)
    if ((identity is not None and _canonical(value['identity']) != _canonical(identity)) or
            (attempt_index is not None and value['attempt_index'] != attempt_index)):
        _fail('E_PREVIOUS_IDENTITY', 'round_metadata_identity', carrier)
    return value


def _history_closure(reference: Json, carrier: Path, scope: Path, *, raw: bytes | None = None) -> _FrozenInputs:
    """Read an immutable capture package; never fall back to a mutable source origin."""
    path = _path(reference['path'], carrier)
    if raw is None:
        _, raw = _StoredObserveInputs(scope).dereference(reference, carrier, 'E_POLICY_SOURCE')
    if _hash(raw) != reference['sha256']:
        _fail('E_POLICY_SOURCE', 'history_closure_hash', path)
    value = _parse(raw, path, 'E_POLICY_SOURCE')
    _keys(value, {'schema_version', 'algorithm_version', 'sources'}, 'E_POLICY_SOURCE', 'history_closure')
    _version(value['schema_version'])
    if value['algorithm_version'] != 'canonical_v1' or not isinstance(value['sources'], list):
        _fail('E_POLICY_SOURCE', 'history_closure_schema', path)
    captured: dict[str, bytes] = {}
    for entry in value['sources']:
        _keys(entry, {'origin', 'sha256', 'blob'}, 'E_POLICY_SOURCE', 'history_closure_entry')
        _ref_shape({'path': entry['origin'], 'sha256': entry['sha256']})
        if (not Path(entry['origin']).is_absolute() or
                str(_path(entry['origin'], path)) != entry['origin'] or entry['origin'] in captured):
            _fail('E_POLICY_SOURCE', 'history_closure_origin', path)
        blob = scope / 'blobs' / (entry['sha256'] + '.blob')
        if entry['blob'] != {'path': str(blob), 'sha256': entry['sha256']}:
            _fail('E_POLICY_SOURCE', 'history_blob_mapping', path)
        data = _Inputs().read(blob)
        if _hash(data) != entry['sha256']:
            _fail('E_POLICY_SOURCE', 'history_blob_hash', blob)
        captured[entry['origin']] = data
    if value['sources'] != sorted(value['sources'], key=lambda x: (x['origin'], x['sha256'])):
        _fail('E_POLICY_SOURCE', 'history_closure_order', path)
    return _FrozenInputs(captured)


def _bound_result_ref(reference: Json | None, carrier: Path, committed: Json | None,
                      scope: Path, *, inputs: _Inputs | None = None) -> Json | None:
    """Map only an exact committed origin or its content-addressed carrier.

    A display hash is not an identity. Resolve it against the immutable original,
    retaining the original carrier for relative refs. No content-copy aliases.
    """
    resolved = _resolved_ref(reference, carrier)
    if resolved is None or committed is None or resolved == committed:
        return resolved
    canonical = scope / 'blobs' / (committed['sha256'] + '.blob')
    if resolved == {'path': str(canonical), 'sha256': committed['sha256']}:
        raw = _Inputs().read(canonical)
        if _hash(raw) != committed['sha256']:
            _fail('E_POLICY_SOURCE', 'result_blob_hash', canonical)
        return committed
    if resolved['path'] != committed['path']:
        return resolved
    candidate = scope / 'blobs' / (resolved['sha256'] + '.blob')
    origin = Path(resolved['path'])
    raw = _Inputs().read(candidate if candidate.exists() else origin)
    if _hash(raw) != resolved['sha256']:
        return resolved
    original = _HistoryGraph(scope).leaf(committed, carrier, published=True)
    value, expected = _parse(raw, origin), _parse(original, origin)
    if (not isinstance(value, dict) or not isinstance(expected, dict) or
            _canonical({**value, 'generated_at': expected['generated_at']}) != _canonical(expected)):
        return resolved
    if inputs is not None:
        inputs.raw.setdefault(str(origin), raw)
    return committed


class _HistoryGraph:
    """Only schema-declared structure edges recurse. Native/raw/JSONL are opaque.

    Check origin re-entry BEFORE even validating a back-edge hash. The cache is
    populated only after the entire node has passed. Code bytes are never run.
    """
    def __init__(self, scope: Path) -> None:
        self.scope = scope
        self.visiting: set[str] = set()
        self.result_refs: list[Json] = []
        self.raw: dict[str, bytes] = {}
        self.origins: dict[str, str] = {}
        self.visited: dict[tuple[str, str], tuple[str, Json]] = {}

    def leaf(self, reference: Json, carrier: Path, *, published: bool = False) -> bytes:
        _ref_shape(reference)
        origin = _path(reference['path'], carrier)
        blob = self.scope / 'blobs' / (reference['sha256'] + '.blob')
        path = blob if blob.exists() or not published else origin
        raw = _Inputs().read(path)
        if _hash(raw) != reference['sha256']:
            _fail('E_POLICY_SOURCE', 'history_source_hash', origin)
        return raw

    def walk(self, reference: Json, carrier: Path, kind: str) -> Json:
        if not isinstance(reference, dict) or not isinstance(reference.get('path'), str):
            _fail('E_POLICY_SOURCE', 'history_reference', carrier)
        if kind == 'result':
            for committed in self.result_refs:
                bound = _bound_result_ref(reference, carrier, committed, self.scope)
                if bound == committed:
                    reference = committed
                    break
        origin = _path(reference['path'], carrier)
        name = str(origin)
        if name in self.visiting:
            _fail('E_HISTORY_CYCLE', 'structural_origin_reentry', origin)
        _ref_shape(reference)
        digest = reference['sha256']
        if name in self.origins and self.origins[name] != digest:
            _fail('E_POLICY_SOURCE', 'structural_origin_rewritten', origin)
        key = (name, digest)
        if key in self.visited:
            previous_kind, value = self.visited[key]
            if previous_kind != kind:
                _fail('E_POLICY_SOURCE', 'structural_schema_alias', origin)
            return value
        raw = self.leaf(reference, carrier, published=kind in ('event', 'result', 'closure', 'genesis', 'sidecar'))
        value = _parse(raw, origin, 'E_POLICY_SOURCE')
        if not isinstance(value, dict):
            _fail('E_POLICY_SOURCE', 'history_object', origin)
        schemas = {
            'event': {'schema_version', 'seq', 'genesis', 'previous_event', 'kind', 'payload'},
            'result': RESULT_KEYS,
            'closure': {'schema_version', 'algorithm_version', 'sources'},
            'genesis': {'schema_version', 'algorithm_version', 'audit_cycle_id', 'checkpoint', 'change_id',
                        'policy_inputs', 'anchor', 'origin_observation', 'initial_sources', 'initial_max_rounds'},
            'manifest': MANIFEST_KEYS,
            'build': {'schema_version', 'manifest', 'identity', 'sources', 'effective_config', 'budgets', 'roles',
                      'workflow_script', 'attempt_index', 'genesis', 'prefix_head', 'reservation', 'input_closure',
                      'generated_at', 'host_build_duration_ms'},
            'request': {'schema_version', 'algorithm_version', 'identity', 'attempt_index', 'genesis', 'anchor',
                        'audit_index', 'input_closure', 'conclusions', 'required', 'reason', 'checker'},
            'prepare': ROUND_METADATA_KEYS['prepare'],
            'publication': ROUND_METADATA_KEYS['publication'],
            'audit': {'schema_version', 'identity', 'attempt_index', 'workflow_run_id', 'native_record', 'termination_refs'},
            'drift': {'schema_version', 'identity', 'attempt_index', 'request', 'kind', 'workflow_run_id',
                      'native_record', 'termination_refs', 'tool_failure'},
            'policy': {'schema_version', 'context', 'spec_source', 'anchor_selection', 'fallback_sources'},
            'anchor': {'schema_version', 'status', 'value', 'observations'},
            'anchor_observations': {'schema_version', 'observations'},
            'origin': {'schema_version', 'checkpoint', 'change_id', 'files', 'warnings'},
            'preflight': {'schema_version', 'observations'},
            'disposition_index': {'schema_version', 'target_result', 'question', 'response', 'options'},
            'sidecar': DISPOSITION_KEYS}
        if kind not in schemas:
            _fail('E_POLICY_SOURCE', 'history_unknown_schema', origin)
        _keys(value, schemas[kind], 'E_POLICY_SOURCE', 'history_' + kind, origin)
        if kind in ROUND_METADATA_KEYS:
            _validate_round_metadata(value, kind, origin)
        elif kind != 'manifest':
            _version(value['schema_version'])
        self.origins[name] = digest
        self.visiting.add(name)

        def edge(ref: Any, target: str) -> None:
            if ref is not None:
                self.walk(ref, origin, target)

        def leaf(ref: Any) -> None:
            if ref is not None:
                self.leaf(ref, origin)

        try:
            if kind == 'event':
                edge(value['genesis'], 'genesis'); edge(value['previous_event'], 'event')
                payload = value['payload']
                if value['kind'] == 'reserve':
                    _keys(payload, {'identity', 'attempt_index', 'manifest', 'workflow_script', 'previous_round',
                                    'previous_attempt'}, 'E_POLICY_SOURCE', 'reservation_keys')
                    edge(payload['manifest'], 'manifest'); leaf(payload['workflow_script'])
                    edge(payload['previous_round'], 'result'); edge(payload['previous_attempt'], 'event')
                elif value['kind'] == 'commit':
                    _keys(payload, {'reservation', 'result', 'markdown', 'input_closure'},
                          'E_POLICY_SOURCE', 'commit_keys')
                    committed = _required_ref(payload['result'], origin)
                    if committed not in self.result_refs:
                        self.result_refs.append(committed)
                    edge(payload['reservation'], 'event'); edge(payload['result'], 'result')
                    edge(payload['input_closure'], 'closure')
                    self.leaf(payload['markdown'], origin, published=True)
                elif value['kind'] == 'observe':
                    _keys(payload, {'preflight'}, 'E_POLICY_SOURCE', 'observe_keys')
                    edge(payload['preflight'], 'preflight')
                elif value['kind'] == 'disposition':
                    _keys(payload, {'target_result', 'evidence', 'sidecar'}, 'E_POLICY_SOURCE', 'disposition_payload')
                    edge(payload['target_result'], 'result')
                    edge(payload['evidence'], 'disposition_index')
                    # Unlike opaque growing session sources, the published sidecar is immutable.
                    _Inputs().dereference(payload['sidecar'], origin)
                    edge(payload['sidecar'], 'sidecar')
                else:
                    _fail('E_POLICY_SOURCE', 'unknown_history_event', origin)
            elif kind == 'result':
                _keys(value['inputs'], RESULT_INPUTS, 'E_POLICY_SOURCE', 'result_inputs')
                targets = {'manifest': 'manifest', 'build_record': 'build', 'genesis': 'genesis',
                    'reservation': 'event', 'input_closure': 'closure', 'audit_index': 'audit',
                    'policy_request': 'request', 'prepare_record': 'prepare', 'publication_record': 'publication',
                    'prefix_head': 'event', 'previous_round': 'result', 'previous_attempt': 'event', 'drift_index': 'drift'}
                for field, target in targets.items():
                    edge(value['inputs'][field], target)
                for field in ('config', 'defaults', 'workflow_script', 'native_record'):
                    leaf(value['inputs'][field])
            elif kind == 'closure':
                _history_closure(reference, carrier, self.scope, raw=raw)
            elif kind == 'genesis':
                edge(value['policy_inputs'], 'policy'); edge(value['anchor'], 'anchor')
                edge(value['origin_observation'], 'origin')
                _keys(value['initial_sources'], set(SOURCE_NAMES), 'E_POLICY_SOURCE', 'initial_sources')
                for ref in value['initial_sources'].values():
                    leaf(ref)
            elif kind == 'manifest':
                _validate_manifest(value)
                ev = value['evidence']
                edge(ev['cycle_origin'], 'genesis'); edge(ev['previous_round'], 'result')
                edge(ev['dispatch_preflight'], 'preflight'); edge(ev['policy_inputs'], 'policy')
            elif kind == 'build':
                for field, target in [('manifest', 'manifest'), ('genesis', 'genesis'), ('reservation', 'event'),
                                      ('prefix_head', 'event'), ('input_closure', 'closure')]:
                    edge(value[field], target)
                _keys(value['sources'], set(SOURCE_NAMES), 'E_POLICY_SOURCE', 'build_sources')
                for ref in value['sources'].values():
                    leaf(ref)
                leaf(value['workflow_script'])
            elif kind in ('request', 'prepare'):
                targets = ({'genesis': 'genesis', 'anchor': 'anchor', 'audit_index': 'audit', 'input_closure': 'closure'}
                           if kind == 'request' else {'audit_index': 'audit', 'input_closure': 'closure', 'policy_request': 'request'})
                for field, target in targets.items():
                    edge(value[field], target)
                if kind == 'prepare':
                    leaf(value['policy_script'])
            elif kind in ('audit', 'drift'):
                leaf(value['native_record'])
                if not isinstance(value['termination_refs'], list):
                    _fail('E_POLICY_SOURCE', 'termination_refs_array', origin)
                for link in value['termination_refs']:
                    _keys(link, {'native_pointer', 'agent_id', 'event'}, 'E_POLICY_SOURCE', 'termination_link')
                    leaf(link['event']['file'])
                if kind == 'drift':
                    edge(value['request'], 'request')
                    if value['tool_failure'] is not None:
                        _keys(value['tool_failure'], {'call', 'response'}, 'E_POLICY_SOURCE', 'tool_failure')
                        for item in value['tool_failure'].values():
                            leaf(item['file'])
            elif kind == 'policy':
                leaf(value['context']); leaf(value['spec_source'])
                selection = value['anchor_selection']
                _keys(selection, {'primary_goal', 'in_scope', 'out_of_scope_hints'}, 'E_POLICY_SOURCE', 'anchor_selection')
                spans = [selection['primary_goal'], *selection['in_scope'], *selection['out_of_scope_hints']]
                for span in spans:
                    if span is not None:
                        leaf(span['source'])
                for item in value['fallback_sources']:
                    leaf(item['source'])
            elif kind == 'anchor':
                edge(value['observations'], 'anchor_observations')
            elif kind == 'anchor_observations':
                for item in value['observations']:
                    leaf(item['source'])
            elif kind == 'origin':
                for item in value['files']:
                    leaf(item['file'])
            elif kind == 'sidecar':
                edge(value['target_result'], 'result'); edge(value['evidence'], 'disposition_index')
                edge(value['input_closure'], 'closure')
            elif kind == 'disposition_index':
                edge(value['target_result'], 'result')
                leaf(value['question']['file']); leaf(value['response']['file'])
            elif kind == 'preflight':
                for item in value['observations']:
                    leaf(item['native_record'])
                    for link in item['termination_refs']:
                        leaf(link['event']['file'])
        except (KeyError, TypeError, ValueError, IndexError):
            _fail('E_POLICY_SOURCE', 'history_nested_schema', origin)
        finally:
            self.visiting.remove(name)
        self.raw[name] = raw
        self.visited[key] = (kind, value)
        return value


def _resolved_ref(reference: Json | None, carrier: Path) -> Json | None:
    if reference is None:
        return None
    _ref_shape(reference)
    return {'path': str(_path(reference['path'], carrier)), 'sha256': reference['sha256']}


def _round_from_sources(repo: Path, result: Json, frozen: _FrozenInputs, genesis: Json,
                     attempts: list[Json], *, carrier: Path, observes: list[Json] | None = None,
                     scope: Path | None = None, preparing: bool = False) -> tuple[Json, Json, Json | None]:
    """Shared read-only round kernel for history and future prepare/final/check.

    Does not publish, parse human consent, or consume caller policy booleans.
    Full source/hash/structure verification precedes this semantic projection.
    """
    # Normalize for lookup/binding only; preserve original reference spelling in output.
    refs: Json = {key: _resolved_ref(value, carrier) for key, value in result['inputs'].items()}
    def document(field: str) -> Json:
        path = Path(refs[field]['path'])
        _, raw = frozen.dereference(refs[field], path)
        return _parse(raw, path, 'E_POLICY_SOURCE')

    build_record = document('build_record')
    manifest_path = Path(refs['manifest']['path'])
    index = document('audit_index')
    audit = _classify_native(repo, manifest_path, Path(refs['build_record']['path']),
        index['workflow_run_id'], _path(index['native_record']['path'], Path(refs['audit_index']['path'])),
        Path(refs['audit_index']['path']), inputs=frozen)
    manifest = document('manifest')
    ident = _identity(manifest)
    if refs['genesis'] != build_record['genesis']:
        _fail('E_PREVIOUS_IDENTITY', 'round_genesis_binding')
    reserve = document('reservation')
    for field, expected in {'manifest': build_record['manifest'], 'reservation': build_record['reservation'],
            'workflow_script': build_record['workflow_script'], 'prefix_head': build_record['prefix_head'],
            'previous_round': reserve['payload']['previous_round'], 'previous_attempt': reserve['payload']['previous_attempt'],
            'native_record': audit['native_record'], 'config': build_record['sources']['config'],
            'defaults': build_record['sources']['defaults']}.items():
        if refs[field] != expected:
            _fail('E_PREVIOUS_IDENTITY', 'round_input_binding_' + field)
    for name, source in build_record['sources'].items():
        if source['sha256'] != genesis['initial_sources'][name]['sha256']:
            _fail('E_SOURCE_DRIFT', 'history_fixed_source_changed', source['path'])
    anchor_path, anchor_raw = frozen.dereference(genesis['anchor'], Path(refs['genesis']['path']))
    anchor = {'record': _parse(anchor_raw, anchor_path, 'E_POLICY_SOURCE'), 'source': genesis['anchor']}
    effective = build_record['effective_config']
    aggregate = _aggregate_admitted(audit['roles'])
    reason = _policy_reason(aggregate, ident, effective['drift_guard'], anchor)
    if preparing:
        # The very same origin-bound native/history kernel precedes request output.
        _apply_policy(genesis, attempts, effective, anchor)
        request = _make_policy_request(manifest, build_record, audit, anchor,
                                      refs['audit_index'], refs['input_closure'])
        _resource_view([a['audit'] for a in attempts] +
            [a['drift'] for a in attempts if a['drift'] is not None] + [audit],
            inputs=_RoundResourceInputs(frozen, scope) if scope is not None else frozen,
            observes=observes, scope=scope, for_checker=request['required'])
        return {'identity': ident, 'attempt_index': manifest['attempt_index'], 'audit': audit, 'drift': None}, request, None
    prepare, publication = document('prepare_record'), document('publication_record')
    _validate_round_metadata(prepare, 'prepare', Path(refs['prepare_record']['path']),
                             identity=ident, attempt_index=manifest['attempt_index'])
    _validate_round_metadata(publication, 'publication', Path(refs['publication_record']['path']),
                             identity=ident, attempt_index=manifest['attempt_index'])
    # Each typed FileRef belongs to its original document, not the result,
    # the referenced target, the blob directory, or the current working directory.
    prepare_path = Path(refs['prepare_record']['path'])
    prepare_refs: Json = {field: _resolved_ref(prepare[field], prepare_path)
                         for field in ('audit_index', 'policy_request', 'input_closure', 'policy_script')}
    if prepare_refs['audit_index'] != refs['audit_index'] or prepare_refs['policy_request'] != refs['policy_request']:
        _fail('E_POLICY_SOURCE', 'prepare_binding')
    if genesis['initial_max_rounds'] != effective['max_rounds']['value']:
        _fail('E_POLICY_SOURCE', 'initial_limit_not_from_fixed_sources')
    if scope is None:
        _fail('E_POLICY_SOURCE', 'round_capture_scope_required')
    # Prepare is an earlier capture, not merely a decorative hash in the final package.
    _, audit_capture_raw = frozen.dereference(prepare_refs['input_closure'], prepare_path)
    audit_capture = _history_closure(prepare['input_closure'], prepare_path, scope, raw=audit_capture_raw)
    try:
        prepared_audit = _classify_native(repo, manifest_path, Path(refs['build_record']['path']),
            index['workflow_run_id'], _path(index['native_record']['path'], Path(refs['audit_index']['path'])),
            Path(refs['audit_index']['path']), inputs=audit_capture)
    except ExecutorError as error:
        if error.reason == 'incomplete_pending_closure':
            _fail('E_POLICY_SOURCE', 'incomplete_prepare_capture', error.input_ref)
        raise
    if _canonical(prepared_audit) != _canonical(audit):
        _fail('E_POLICY_SOURCE', 'prepare_final_audit_changed')
    request = document('policy_request')
    request_path = Path(refs['policy_request']['path'])
    resolved_request = {**request, **{field: _resolved_ref(request[field], request_path)
                        for field in ('genesis', 'anchor', 'audit_index', 'input_closure')}}
    expected_request = _make_policy_request(manifest, build_record, audit, anchor,
                                              refs['audit_index'], prepare_refs['input_closure'])
    expected_request['genesis'] = refs['genesis']
    expected_request['anchor'] = _resolved_ref(genesis['anchor'], Path(refs['genesis']['path']))
    if _canonical(resolved_request) != _canonical(expected_request):
        _fail('E_POLICY_SOURCE', 'request_not_recomputed')
    drift = None
    if reason == 'required':
        if refs['drift_index'] is None or prepare_refs['policy_script'] is None:
            _fail('E_POLICY_SOURCE', 'required_checker_evidence_missing')
        if scope is None:
            _fail('E_POLICY_SOURCE', 'checker_resource_scope_required')
        _resource_view([a['audit'] for a in attempts] + [a['drift'] for a in attempts if a['drift'] is not None] +
                       [audit], inputs=_RoundResourceInputs(frozen, scope), observes=observes, scope=scope, for_checker=True)
        drift = _verify_drift(Path(refs['drift_index']['path']), refs['policy_request'],
                              Path(prepare_refs['policy_script']['path']), inputs=frozen)
    elif refs['drift_index'] is not None or prepare_refs['policy_script'] is not None:
        _fail('E_POLICY_SOURCE', 'unexpected_checker_evidence')
    attempt = {'identity': ident, 'attempt_index': manifest['attempt_index'], 'audit': audit, 'drift': drift}
    folded = _apply_policy(genesis, [*attempts, attempt], effective, anchor)
    row = folded['attempts'][-1]
    resources = _resource_view([a['audit'] for a in [*attempts, attempt]] +
        [a['drift'] for a in [*attempts, attempt] if a['drift'] is not None],
        inputs=_RoundResourceInputs(frozen, scope) if scope is not None else frozen, observes=observes, scope=scope)
    expected = {k: v for k, v in row.items() if k not in ('policy', 'policy_sources')}
    expected.update(schema_version=1, identity=ident, budgets=dict(BUDGETS), inputs=result['inputs'],
        attempt_index=manifest['attempt_index'], workflow_run_id=audit['workflow_run_id'],
        workflow_script_sha256=build_record['workflow_script']['sha256'], roles=audit['roles'],
        require_same_admitted_roles=effective['require_same_admitted_roles']['value'],
        dispatched_roles=[r['role_id'] for r in audit['roles'] if r['attempted']],
        clock={**{k: v for k, v in audit.items() if k not in ('roles', 'workflow_run_id', 'native_record')},
               'host_prepare_duration_ms': prepare['host_prepare_duration_ms'],
               'host_collect_duration_ms': publication['host_collect_duration_ms']},
        policy={**row['policy'], 'sources': row['policy_sources']},
        next_round_dispatch_allowed=resources['next_round_dispatch_allowed'], generated_at=publication['generated_at'])
    return attempt, row, expected


def _recompute_round(repo: Path, result: Json, frozen: _FrozenInputs, genesis: Json,
                     attempts: list[Json], *, carrier: Path, observes: list[Json] | None = None,
                     scope: Path | None = None, preparing: bool = False) -> tuple[Json, Json]:
    attempt, row, expected = _round_from_sources(repo, result, frozen, genesis, attempts,
        carrier=carrier, observes=observes, scope=scope, preparing=preparing)
    if expected is not None and _canonical({**result, 'generated_at': expected['generated_at']}) != _canonical(expected):
        _fail('E_RESULT_MISMATCH', 'historical_round_projection')
    return attempt, row


def _replay_history(state: Json) -> Json:
    """Rebuild every committed attempt from fixed ledger and frozen original bytes.

    Human disposition events are parsed from their own frozen source package.
    A pending reservation is never interpreted as a void or a completed attempt.
    """
    if not state.get('events'):
        limit = state['genesis']['initial_max_rounds']
        return {'charged_rounds': 0, 'effective_limit': limit, 'remaining_rounds': limit,
                'terminal_state': None, 'overridden_by_user': False, 'degraded': False,
                'latest_round': None, 'latest_attempt': None, 'attempts': [], 'rounds': [],
                'resource_attempts': [], 'resource_view': _resource_summary([]), 'frozen_raw': {}}
    if not state.get('genesis_ref'):
        _fail('E_POLICY_SOURCE', 'missing_history_genesis')
    if state.get('pending') is not None:
        _fail('E_POLICY_SOURCE', 'pending_requires_exact_resume')
    scope = Path(state['genesis_ref']['path']).parent
    repo = scope.parents[3]
    graph = _HistoryGraph(scope)
    genesis = graph.walk(state['genesis_ref'], scope / 'genesis.json', 'genesis')
    if _canonical(genesis) != _canonical(state['genesis']):
        _fail('E_PREVIOUS_IDENTITY', 'history_genesis_changed')
    for entry in state['events']:
        actual = graph.walk(entry['ref'], Path(entry['ref']['path']), 'event')
        if _canonical(actual) != _canonical(entry['event']):
            _fail('E_PREVIOUS_IDENTITY', 'history_event_changed')
    attempts: list[Json] = []
    rows: list[Json] = []
    resource_attempts: list[Json] = []
    latest_round: Json | None = None
    latest_attempt: Json | None = None
    pending: Json | None = None
    head: Json | None = None
    clients: set[str] = set()
    reserves = 0
    frozen_raw: dict[str, bytes] = {}
    policy: Json = {'charged_rounds': 0, 'effective_limit': genesis['initial_max_rounds'],
                   'remaining_rounds': genesis['initial_max_rounds'], 'terminal_state': None,
                   'overridden_by_user': False, 'degraded': False}
    observes: list[Json] = []
    dispositions: list[Json] = []
    consumed: set[tuple[str, ...]] = set()
    for seq, entry in enumerate(state['events'], 1):
        event, reference = entry['event'], entry['ref']
        if (type(event['seq']) is not int or event['seq'] != seq or event['previous_event'] != head or
                event['genesis'] != state['genesis_ref']):
            _fail('E_PREVIOUS_IDENTITY', 'history_event_sequence')
        payload = event['payload']
        if event['kind'] == 'reserve':
            if pending is not None:
                _fail('E_PREVIOUS_IDENTITY', 'history_multiple_reserves')
            reserves += 1
            identity = payload['identity']
            _round_identity(identity)
            if (type(payload['attempt_index']) is not int or payload['attempt_index'] != reserves or
                    identity['round'] != policy['charged_rounds'] + 1 or
                    any(identity[k] != genesis[k] for k in ('audit_cycle_id', 'checkpoint', 'change_id')) or
                    identity['client_round_id'] in clients or payload['previous_round'] != latest_round or
                    payload['previous_attempt'] != latest_attempt):
                _fail('E_PREVIOUS_IDENTITY', 'history_reservation_sequence')
            clients.add(identity['client_round_id'])
            resources = _resource_view(resource_attempts, inputs=_FrozenInputs(frozen_raw), observes=observes, scope=scope)
            if not resources['next_round_dispatch_allowed']:
                _fail('E_RESOURCE_PENDING', 'historical_dispatch_with_unknown_calls')
            _require_dispatch_policy(policy)
            pending = entry
        elif event['kind'] == 'commit':
            if pending is None or payload['reservation'] != pending['ref']:
                _fail('E_PREVIOUS_IDENTITY', 'commit_without_matching_reservation')
            result = graph.walk(payload['result'], Path(reference['path']), 'result')
            result_carrier = _path(payload['result']['path'], Path(reference['path']))
            round_refs = {key: _resolved_ref(value, result_carrier) for key, value in result['inputs'].items()}
            if round_refs['input_closure'] != _resolved_ref(payload['input_closure'], Path(reference['path'])):
                _fail('E_PREVIOUS_IDENTITY', 'commit_closure_binding')
            # Final closures are published after their capture, so explicitly freeze
            # their verified bytes for the package loader; no arbitrary live leaf fallback.
            closure_raw = graph.leaf(payload['input_closure'], Path(reference['path']), published=True)
            frozen = _history_closure(payload['input_closure'], Path(reference['path']), scope, raw=closure_raw)
            captured = frozen.raw
            if (round_refs['reservation'] != pending['ref'] or
                    round_refs['genesis'] != state['genesis_ref'] or
                    result['identity'] != pending['event']['payload']['identity'] or
                    result['attempt_index'] != reserves):
                _fail('E_PREVIOUS_IDENTITY', 'committed_attempt_identity')
            attempt, row = _recompute_round(repo, result, frozen, genesis, attempts, carrier=result_carrier,
                                            observes=observes, scope=scope)
            attempts.append(attempt); rows.append(row)
            resource_attempts.append(attempt['audit'])
            if attempt['drift'] is not None:
                resource_attempts.append(attempt['drift'])
            frozen_raw.update(captured)
            policy = row['policy']
            latest_attempt = reference
            if not row['all_failed_void']:
                latest_round = payload['result']
            pending = None
        elif event['kind'] == 'observe':
            observes.append(entry)
            if pending is None:
                _resource_view(resource_attempts, inputs=_FrozenInputs(frozen_raw), observes=observes, scope=scope)
        elif event['kind'] == 'disposition':
            _keys(payload, {'target_result', 'evidence', 'sidecar'}, 'E_POLICY_SOURCE', 'disposition_payload')
            carrier = Path(reference['path'])
            target = _required_ref(payload['target_result'], carrier)
            if (pending is not None or latest_round is None or target != latest_round or
                    not rows or rows[-1]['all_failed_void'] or
                    any(d['target_result'] == target for d in dispositions)):
                _fail('E_POLICY_SOURCE', 'disposition_not_latest_effective_head')
            side_ref = _required_ref(payload['sidecar'], carrier)
            side_path = Path(side_ref['path'])
            if side_path != Path(target['path']).with_suffix('.disposition.json'):
                _fail('E_POLICY_SOURCE', 'sidecar_target_path')
            side = graph.walk(side_ref, carrier, 'sidecar')
            closure = _required_ref(side['input_closure'], side_path)
            if Path(closure['path']) != Path(target['path']).with_suffix('.disposition-closure.json'):
                _fail('E_POLICY_SOURCE', 'disposition_closure_path')
            frozen = _history_closure(closure, side_path, scope,
                raw=graph.leaf(closure, side_path, published=True))
            evidence = _required_ref(payload['evidence'], carrier)
            target_value = graph.walk(target, carrier, 'result')
            manifest_ref = _required_ref(target_value['inputs']['manifest'], Path(target['path']))
            manifest_path, manifest_raw = frozen.dereference(manifest_ref, side_path)
            manifest = _parse(manifest_raw, manifest_path, 'E_POLICY_SOURCE')
            if evidence['path'] != str(_path(manifest['evidence']['post_disposition_index_path'], manifest_path)):
                _fail('E_POLICY_SOURCE', 'disposition_locator_binding')
            frozen.dereference(evidence, carrier)
            decision = _parse_human_disposition(Path(evidence['path']), target,
                target_value['identity'], policy, inputs=frozen, scope=scope)
            token = tuple(decision['token'])
            if token in consumed:
                _fail('E_POLICY_SOURCE', 'disposition_token_replay')
            next_policy = _disposition_view(policy, decision['action'])
            expected = _disposition_record(target, evidence, closure, target_value['identity'], decision, next_policy)
            if _canonical(side) != _canonical(expected):
                _fail('E_POLICY_SOURCE', 'sidecar_not_recomputed')
            consumed.add(token)
            parsed = {**decision, 'target_result': target, 'evidence': evidence, 'sidecar': side_ref}
            attempts[-1]['disposition'] = parsed
            dispositions.append({**parsed, 'view': {**next_policy, 'converged': False}})
            policy = next_policy
            frozen_raw.update(frozen.raw)
        else:
            _fail('E_POLICY_SOURCE', 'unknown_history_event')
        head = reference
    if (pending is not None or state['head'] != head or state['reserve_count'] != reserves):
        _fail('E_PREVIOUS_IDENTITY', 'history_incomplete_or_stale_prefix')
    resources = _resource_view(resource_attempts, inputs=_FrozenInputs(frozen_raw), observes=observes, scope=scope)
    frozen_raw.update(graph.raw)
    return {**policy, 'latest_round': latest_round, 'latest_attempt': latest_attempt,
            'attempts': attempts, 'rounds': rows, 'resource_attempts': resource_attempts,
            'resource_view': resources, 'frozen_raw': frozen_raw, 'dispositions': dispositions}


def _require_dispatch_policy(view: Json) -> None:
    if (view["remaining_rounds"] <= 0 or view["terminal_state"] in
            ("CONVERGED", "DRIFT_TERMINATED", "OSCILLATION", "MAX_ROUNDS_EXHAUSTED") or
            view["overridden_by_user"] or view["degraded"]):
        _fail("E_POLICY_BLOCKED", "prefix_policy_forbids_dispatch")


def _identity(manifest: Json) -> Json:
    return {key: manifest[key] for key in IDENTITY_KEYS}


def _roles(manifest: Json) -> list[Json]:
    return [{"index": index, "role_id": role["role_id"], "agentType": role["agentType"],
             "model_alias": role["model_alias"], "prompt_sha256": _hash(role["prompt"].encode("utf-8")),
             "label": f"audit:{manifest['client_round_id']}:{index}"}
            for index, role in enumerate(manifest["roles"])]


def _workflow(manifest: Json, manifest_hash: str) -> bytes:
    # 调度属性的受控 VM/JS 验证属于 TASK-005；本接口只生成冻结字面量程序。
    identity = _identity(manifest)
    args = {"identity": identity, "manifest_sha256": manifest_hash}
    literal = lambda value: _canonical(value).decode("ascii")
    script = 'export const meta = {"name":"audit-executor","description":"Frozen audit round","phases":[{"title":"Audit"}]}\n'
    script += "const MANIFEST = " + literal(manifest) + ";\n"
    script += "const EXPECTED_ARGS = " + literal(args) + ";\n"
    script += "const IDENTITY = " + literal(identity) + ";\n"
    script += "const MANIFEST_SHA256 = " + literal(manifest_hash) + ";\n"
    script += """if (!args || Object.keys(args).length !== 2 || args.manifest_sha256 !== MANIFEST_SHA256 ||
    !args.identity || Object.keys(args.identity).length !== Object.keys(IDENTITY).length ||
    Object.keys(IDENTITY).some(key => args.identity[key] !== IDENTITY[key])) throw new Error('E_RUN_IDENTITY');
phase('Audit');
const results = MANIFEST.roles.map((role,index) => ({index,role_id:role.role_id,agentType:role.agentType,
  label:'audit:'+MANIFEST.client_round_id+':'+String(index),attempted:false,settled:false,raw:null,error:null}));
let next = 0, stop = false, finish;
const deadline = new Promise(resolve => { finish = resolve; });
const timer = setTimeout(() => { stop = true; finish('control_timeout'); }, 300000);
async function worker() {
  while (!stop && next < results.length) {
    const index = next++, item = results[index], role = MANIFEST.roles[index];
    item.attempted = true;
    const seatTimer = setTimeout(() => { log(item.label+': soft timeout; slot retained'); }, 120000);
    try {
      const raw = await agent(role.prompt, {agentType:role.agentType,label:item.label,phase:'Audit'});
      if (!stop) { item.raw = raw === undefined ? null : raw; item.settled = true; }
    } catch (error) {
      if (!stop) { item.error = String(error); item.settled = true; }
    } finally { clearTimeout(seatTimer); }
  }
}
const workers = Promise.all([worker(),worker()]).then(() => 'all_settled');
const reason = await Promise.race([workers, deadline]);
clearTimeout(timer);
const snapshot = JSON.parse(JSON.stringify({schema_version:1,identity:IDENTITY,manifest_sha256:MANIFEST_SHA256,
  control:{round_timer_ms:300000,stop_observed:stop,return_reason:reason},results}));
stop = true;
return snapshot;
"""
    return script.encode("utf-8")


def _render_policy_workflow(request_ref: Json, *, inputs: _Inputs | None = None) -> bytes:
    """读取先封存的 request FileRef，返回 JS 最终字节；不写文件/重算政策。

    TASK-010 在真实 prepare 中先写 request、取原字节 hash，再调用本函数，
    最后发布脚本并取脚本 hash。required/reason 的政策推导及原生验证仍在
    prepare/final/check；这里仅验证冻结协议和生成单一独立调用。
    """
    code = "E_POLICY_SOURCE"
    _ref_shape(request_ref, code)
    if not Path(request_ref["path"]).is_absolute():
        _fail(code, "absolute_request_reference_required", request_ref["path"])
    inputs = inputs if inputs is not None else _Inputs()
    request_path, request_raw = inputs.dereference(request_ref, Path(request_ref["path"]), code)
    request = _parse(request_raw, request_path, code)
    _keys(request, {"schema_version", "algorithm_version", "identity", "attempt_index", "genesis",
                    "anchor", "audit_index", "input_closure", "conclusions", "required", "reason", "checker"},
          code, "policy_request_keys", request_path)
    _version(request["schema_version"])
    if request["algorithm_version"] != "canonical_v1":
        _fail(code, "policy_request_algorithm", request_path)
    identity = request["identity"]
    _keys(identity, set(IDENTITY_KEYS), code, "policy_identity_keys", request_path)
    for key in IDENTITY_KEYS:
        if key != "round":
            _id(identity[key], code)
    _integer(identity["round"], 2, code)
    _integer(request["attempt_index"], 1, code)
    if (identity["checkpoint"] not in CHECKPOINTS or
            re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", identity["candidate_sha"]) is None):
        _fail(code, "policy_identity", request_path)
    if request["required"] is not True or request["reason"] != "required":
        _fail(code, "checker_not_required", request_path)
    checker = request["checker"]
    _keys(checker, {"agentType", "label", "timeout_ms"}, code, "checker_keys", request_path)
    _integer(checker["timeout_ms"], 1, code)
    if checker["timeout_ms"] != 60000 or checker["label"] != "drift:" + identity["client_round_id"]:
        _fail(code, "checker_label_or_budget", request_path)

    genesis_path, genesis_raw = inputs.dereference(request["genesis"], request_path, code)
    genesis = _parse(genesis_raw, genesis_path, code)
    _keys(genesis, {"schema_version", "algorithm_version", "audit_cycle_id", "checkpoint", "change_id",
                    "policy_inputs", "anchor", "origin_observation", "initial_sources", "initial_max_rounds"},
          code, "genesis_keys", genesis_path)
    _version(genesis["schema_version"])
    _integer(genesis["initial_max_rounds"], 1, code)
    if (genesis["algorithm_version"] != "canonical_v1" or
            any(genesis[key] != identity[key] for key in ("audit_cycle_id", "checkpoint", "change_id"))):
        _fail(code, "checker_genesis_identity", genesis_path)
    _keys(genesis["initial_sources"], set(SOURCE_NAMES), code, "genesis_sources", genesis_path)
    # 配置团队由 genesis 已绑定的冻结原配置承载；不取 caller 第一项或当前 cwd。
    config_path, config_raw = inputs.dereference(genesis["initial_sources"]["config"], genesis_path, code)
    config = _parse(config_raw, config_path, code)
    audit = config.get("audit") if isinstance(config, dict) else None
    teams = audit.get("teams") if isinstance(audit, dict) else None
    team = teams.get(identity["checkpoint"]) if isinstance(teams, dict) else None
    if (not isinstance(team, list) or not team or
            any(not isinstance(item, str) or not item.strip() for item in team) or len(set(team)) != len(team)):
        _fail(code, "checker_explicit_team_required", config_path)
    if checker["agentType"] != team[0]:
        _fail(code, "checker_configured_first_agent", request_path)

    anchor_path, anchor_raw = inputs.dereference(request["anchor"], request_path, code)
    genesis_anchor_path, genesis_anchor_raw = inputs.dereference(genesis["anchor"], genesis_path, code)
    if anchor_path != genesis_anchor_path or anchor_raw != genesis_anchor_raw:
        _fail(code, "checker_anchor_genesis_mismatch", anchor_path)
    anchor_record = _parse(anchor_raw, anchor_path, code)
    _keys(anchor_record, {"schema_version", "status", "value", "observations"}, code, "anchor_keys", anchor_path)
    _version(anchor_record["schema_version"])
    if anchor_record["status"] != "present":
        _fail(code, "checker_present_anchor_required", anchor_path)
    anchor = anchor_record["value"]
    _keys(anchor, {"checkpoint", "primary_goal", "in_scope", "out_of_scope_hints", "source_sha"},
          code, "anchor_value_keys", anchor_path)
    _id(anchor["primary_goal"], code)
    _id(anchor["source_sha"], code)
    if (anchor["checkpoint"] != identity["checkpoint"] or
            re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", anchor["source_sha"]) is None):
        _fail(code, "checker_anchor_identity", anchor_path)
    for key in ("in_scope", "out_of_scope_hints"):
        if not isinstance(anchor[key], list):
            _fail(code, "anchor_scope_array", anchor_path)
        for item in anchor[key]:
            if not isinstance(item, str):
                _fail(code, "anchor_scope_string", anchor_path)
    inputs.dereference(anchor_record["observations"], anchor_path, code)
    # 验证 request 引用的原字节，不冒充这里已做 native/闭包/全历史语义重算。
    for key in ("audit_index", "input_closure"):
        inputs.dereference(request[key], request_path, code)
    conclusions = request["conclusions"]
    if not isinstance(conclusions, list) or not conclusions:
        _fail(code, "checker_conclusions_required", request_path)
    seen: set[tuple[str, ...]] = set()
    for conclusion in conclusions:
        _keys(conclusion, {"id", "type", "severity", "category", "scope", "summary", "found_by", "variants", "conflict_state"},
              code, "conclusion_keys", request_path)
        for key in ("id", "type", "severity", "category"):
            _id(conclusion[key], code)
        # §8 scope 仅要求 string；空串仍是合法完整 key，不能新增准入门。
        if not isinstance(conclusion["scope"], str):
            _fail(code, "conclusion_scope", request_path)
        if not isinstance(conclusion["summary"], str):
            _fail(code, "conclusion_summary", request_path)
        key_tuple = tuple(conclusion[key] for key in ("type", "severity", "category", "scope"))
        if (key_tuple in seen or conclusion["severity"] not in ("minor", "major", "critical") or
                conclusion["conflict_state"] not in ("none", "unresolved_variants")):
            _fail(code, "conclusion_identity", request_path)
        seen.add(key_tuple)
        if not isinstance(conclusion["found_by"], list) or not conclusion["found_by"]:
            _fail(code, "conclusion_found_by", request_path)
        for role in conclusion["found_by"]:
            _id(role, code)
        if not isinstance(conclusion["variants"], list) or not conclusion["variants"]:
            _fail(code, "conclusion_variants", request_path)
        for variant in conclusion["variants"]:
            _keys(variant, {"finding", "members"}, code, "variant_keys", request_path)
            if not isinstance(variant["finding"], dict) or not isinstance(variant["members"], list) or not variant["members"]:
                _fail(code, "variant_shape", request_path)
            for member in variant["members"]:
                _keys(member, {"role_id", "role_index", "finding_index", "raw_ref"}, code, "member_keys", request_path)
                _id(member["role_id"], code)
                _integer(member["role_index"], 0, code)
                _integer(member["finding_index"], 0, code)
                _keys(member["raw_ref"], {"file", "pointer"}, code, "raw_ref_keys", request_path)
                _ref_shape(member["raw_ref"]["file"], code)
                _id(member["raw_ref"]["pointer"], code)

    literal = lambda value: _canonical(value).decode("ascii")
    if not anchor["in_scope"] and not anchor["out_of_scope_hints"]:
        instruction = ("本次anchor为partial anchor；仅按每条结论与primary_goal的语义相关性分类："
                       "相关返回on_topic，否则返回adjacent；不得返回off_topic。逐个完整key恰分类一次，"
                       "不返回scope-empty或confidence标注。")
    else:
        instruction = ("按完整anchor逐个完整key恰分类一次，classification仅为on_topic、adjacent或off_topic。"
                       "不返回scope-empty或confidence标注。")
    prompt = (instruction + '\n仅返回完整JSON object {"classifications":[{"key":[type,severity,category,scope],'
              '"classification":"on_topic|adjacent|off_topic"}]}；不汇总投票、不决定PASS。\n'
              + "request_sha256=" + request_ref["sha256"] + "\nanchor=" + literal(anchor)
              + "\nconclusions=" + literal(conclusions))
    expected = {"identity": identity, "request_sha256": request_ref["sha256"],
                "anchor": anchor, "conclusions": conclusions}
    script = 'export const meta = {"name":"audit-policy-checker","description":"Frozen independent drift check","phases":[{"title":"Drift"}]}\n'
    # JSON.parse 保留任意 finding 的 __proto__ 自有键，不使用 object literal 语义。
    script += "const EXPECTED_ARGS = JSON.parse(" + literal(literal(expected)) + ");\n"
    script += "const CHECKER = " + literal(checker) + ";\n"
    script += "const PROMPT = " + literal(prompt) + ";\n"
    script += """function same(a,b) {
  if (a === b) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object' || Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(b);
  return Object.keys(a).length === keys.length && keys.every(key => Object.prototype.hasOwnProperty.call(a,key) && same(a[key],b[key]));
}
if (!same(args,EXPECTED_ARGS)) throw new Error('E_RUN_IDENTITY');
phase('Drift');
const result = {schema_version:1,identity:EXPECTED_ARGS.identity,request_sha256:EXPECTED_ARGS.request_sha256,
  agentType:CHECKER.agentType,label:CHECKER.label,call_attempted:false,settled:false,raw:null,error:null,
  control:{timeout_ms:60000,stop_observed:false,return_reason:'all_settled'}};
let stop = false, finish;
const deadline = new Promise(resolve => { finish = resolve; });
const timer = setTimeout(() => { stop = true; finish('control_timeout'); }, 60000);
async function check() {
  result.call_attempted = true;
  try {
    const raw = await agent(PROMPT,{agentType:CHECKER.agentType,label:CHECKER.label,phase:'Drift'});
    if (!stop) result.raw = raw === undefined ? null : raw;
  } catch (error) { if (!stop) result.error = String(error); }
  if (!stop) result.settled = true;
  return 'all_settled';
}
const reason = await Promise.race([check(),deadline]);
clearTimeout(timer);
result.control = {timeout_ms:60000,stop_observed:stop,return_reason:reason};
const snapshot = JSON.parse(JSON.stringify(result));
stop = true;
return snapshot;
"""
    return script.encode("utf-8")


def _record(manifest: Json, manifest_ref: Json, sources: Json, effective: Json,
            state: Json, reservation: Json, closure: Json, script: Json, metadata: Json) -> Json:
    return {"schema_version": 1, "manifest": manifest_ref, "identity": _identity(manifest),
            "sources": sources, "effective_config": effective, "budgets": dict(BUDGETS), "roles": _roles(manifest),
            "workflow_script": script, "attempt_index": manifest["attempt_index"], "genesis": state["genesis_ref"],
            "prefix_head": reservation["event"]["previous_event"], "reservation": reservation["ref"], "input_closure": closure,
            "generated_at": metadata["generated_at"], "host_build_duration_ms": metadata["host_build_duration_ms"]}


class _FrozenInputs(_Inputs):
    """已校验闭包的 origin 索引；缺映射绝不回退到可变原路径。"""
    def __init__(self, raw: dict[str, bytes]) -> None:
        self.raw = raw

    def read(self, path: Path, code: str = "E_POLICY_SOURCE") -> bytes:
        if str(path) not in self.raw:
            _fail(code, "incomplete_pending_closure", path)
        return self.raw[str(path)]


class _CaptureInputs(_Inputs):
    """封存 origin 优先；仅新来源实读并收集，绝不改写既有快照。"""
    def __init__(self, frozen: _FrozenInputs) -> None:
        super().__init__()
        self.frozen = _FrozenInputs(dict(frozen.raw))

    def read(self, path: Path, code: str = "E_POLICY_SOURCE") -> bytes:
        if str(path) in self.frozen.raw:
            return self.frozen.read(path, code)
        return super().read(path, code)


def _verify_pending_graph(state: Json, manifest: Json, manifest_path: Path,
                          sources: Json, effective: Json, frozen: _Inputs) -> None:
    """仅验证本次 pending 的运行前依赖闭包，不冒充完整历史/policy 折叠。"""
    payload = state["pending"]["event"]["payload"]
    frozen.dereference(payload["manifest"], manifest_path)
    frozen.dereference(payload["workflow_script"], manifest_path)
    genesis_path, genesis_raw = frozen.dereference(state["genesis_ref"], manifest_path)
    genesis = _parse(genesis_raw, genesis_path)
    if genesis != state["genesis"]:
        _fail("E_OUTPUT_CONFLICT", "pending_genesis_conflict", genesis_path)
    for name, source in sources.items():
        frozen.dereference(source, manifest_path)
        if source["sha256"] != genesis["initial_sources"][name]["sha256"]:
            _fail("E_OUTPUT_CONFLICT", "pending_fixed_source_conflict", source["path"])
    for evidence in effective["resolved_mode"]["evidence"]:
        if "source" in evidence:
            frozen.dereference(evidence["source"], manifest_path)
    policy_path, policy_raw = frozen.dereference(manifest["evidence"]["policy_inputs"], manifest_path)
    if manifest["attempt_index"] == 1:
        if _hash(policy_raw) != genesis["policy_inputs"]["sha256"]:
            _fail("E_OUTPUT_CONFLICT", "pending_policy_conflict", policy_path)
    else:
        # Original provenance is an explicit time package, separate from current context.
        frozen = _StoredObserveInputs(genesis_path.parent)
        policy_path, policy_raw = frozen.dereference(genesis["policy_inputs"], genesis_path, "E_POLICY_SOURCE")
    policy = _parse(policy_raw, policy_path, "E_POLICY_SOURCE")
    _keys(policy, {"schema_version", "context", "spec_source", "anchor_selection", "fallback_sources"},
          "E_POLICY_SOURCE", "policy_input_keys", policy_path)
    _version(policy["schema_version"])
    frozen.dereference(policy["context"], policy_path)
    if policy["spec_source"] is not None:
        frozen.dereference(policy["spec_source"], policy_path)
    selection = policy["anchor_selection"]
    _keys(selection, {"primary_goal", "in_scope", "out_of_scope_hints"},
          "E_POLICY_SOURCE", "anchor_selection_keys")
    if selection["primary_goal"] is not None:
        _span(selection["primary_goal"], policy_path, frozen)
    for field in ("in_scope", "out_of_scope_hints"):
        if not isinstance(selection[field], list):
            _fail("E_POLICY_SOURCE", "scope_spans_required", policy_path)
        for span in selection[field]:
            _span(span, policy_path, frozen)
    anchor_path, anchor_raw = frozen.dereference(genesis["anchor"], genesis_path)
    anchor = _parse(anchor_raw, anchor_path, "E_POLICY_SOURCE")
    _keys(anchor, {"schema_version", "status", "value", "observations"}, "E_POLICY_SOURCE", "anchor_keys")
    _version(anchor["schema_version"])
    observation_path, observation_raw = frozen.dereference(anchor["observations"], anchor_path)
    observation = _parse(observation_raw, observation_path, "E_POLICY_SOURCE")
    _keys(observation, {"schema_version", "observations"}, "E_POLICY_SOURCE", "observation_keys")
    _version(observation["schema_version"])
    fallback = policy["fallback_sources"]
    observations = observation["observations"]
    if (not isinstance(fallback, list) or not isinstance(observations, list) or
            not fallback or len(fallback) != len(observations)):
        _fail("E_POLICY_SOURCE", "fallback_observations", observation_path)
    for entry, observed in zip(fallback, observations):
        _keys(entry, {"kind", "locator", "source"}, "E_POLICY_SOURCE", "fallback_keys")
        _keys(observed, {"kind", "locator", "outcome", "source"}, "E_POLICY_SOURCE", "fallback_observation_keys")
        _id(entry["locator"], "E_POLICY_SOURCE")
        locator = _path(entry["locator"], policy_path)
        if observed["kind"] != entry["kind"] or observed["locator"] != str(locator):
            _fail("E_POLICY_SOURCE", "fallback_observation_mismatch", observation_path)
        if entry["source"] is None:
            if observed["source"] is not None or observed["outcome"] != "missing":
                _fail("E_POLICY_SOURCE", "fallback_missing_observation", observation_path)
        else:
            source_path, _ = frozen.dereference(entry["source"], policy_path)
            observed_path, _ = frozen.dereference(observed["source"], observation_path)
            if source_path != locator or observed_path != locator or observed["outcome"] not in ("read", "no_anchor"):
                _fail("E_POLICY_SOURCE", "fallback_source_mismatch", locator)
    origin_path, origin_raw = frozen.dereference(genesis["origin_observation"], genesis_path)
    origin = _parse(origin_raw, origin_path, "E_POLICY_SOURCE")
    _keys(origin, {"schema_version", "checkpoint", "change_id", "files", "warnings"},
          "E_POLICY_SOURCE", "origin_observation_keys")
    _version(origin["schema_version"])
    if not isinstance(origin["files"], list):
        _fail("E_POLICY_SOURCE", "origin_files", origin_path)
    for item in origin["files"]:
        _keys(item, {"file", "attribution"}, "E_POLICY_SOURCE", "origin_file_keys")
        frozen.dereference(item["file"], origin_path)


def _resume_build(state: Json, manifest: Json, manifest_path: Path, run: Path, inputs: _Inputs,
                  sources: Json, policy: Json, repo: Path) -> Json:
    pending = state["pending"]
    payload = pending["event"]["payload"]
    current_ref = inputs.reference(manifest_path)
    if (payload["manifest"] != current_ref or payload["identity"] != _identity(manifest) or
            payload["attempt_index"] != manifest["attempt_index"]):
        _fail("E_RESOURCE_PENDING", "pending_reservation_resume_only", manifest_path)
    script_ref = inputs.reference(run / "workflow.js", "E_OUTPUT_CONFLICT")
    if payload["workflow_script"] != script_ref or _workflow(manifest, current_ref["sha256"]) != inputs.raw[script_ref["path"]]:
        _fail("E_OUTPUT_CONFLICT", "pending_script_conflict", run)
    closure_ref = inputs.reference(run / "input-closure.json", "E_OUTPUT_CONFLICT")
    closure = _parse(inputs.raw[closure_ref["path"]], run / "input-closure.json", "E_OUTPUT_CONFLICT")
    _keys(closure, {"schema_version", "algorithm_version", "sources"}, "E_OUTPUT_CONFLICT", "closure_keys")
    _version(closure["schema_version"], "E_OUTPUT_CONFLICT")
    if closure["algorithm_version"] != "canonical_v1" or not isinstance(closure["sources"], list):
        _fail("E_OUTPUT_CONFLICT", "closure_schema", run)
    captured: dict[str, bytes] = {}
    entries = closure["sources"]
    for entry in entries:
        _keys(entry, {"origin", "sha256", "blob"}, "E_OUTPUT_CONFLICT", "closure_entry")
        _ref_shape({"path": entry["origin"], "sha256": entry["sha256"]}, "E_OUTPUT_CONFLICT")
        if not Path(entry["origin"]).is_absolute():
            _fail("E_OUTPUT_CONFLICT", "closure_origin_absolute", run)
        if entry["origin"] in captured:
            _fail("E_OUTPUT_CONFLICT", "closure_duplicate_origin", run)
        blob_path = Path(state["genesis_ref"]["path"]).parent / "blobs" / (entry["sha256"] + ".blob")
        expected_blob = {"path": str(blob_path), "sha256": entry["sha256"]}
        if entry["blob"] != expected_blob:
            _fail("E_OUTPUT_CONFLICT", "closure_blob_mapping", entry["origin"])
        _safe_write_path(blob_path, Path(state["genesis_ref"]["path"]).parent)
        _, blob = inputs.dereference(entry["blob"], run / "input-closure.json", "E_OUTPUT_CONFLICT")
        if _hash(blob) != entry["sha256"]:
            _fail("E_OUTPUT_CONFLICT", "pending_input_conflict", entry["origin"])
        captured[entry["origin"]] = blob
    if entries != sorted(entries, key=lambda entry: (entry["origin"], entry["sha256"])):
        _fail("E_OUTPUT_CONFLICT", "closure_order", run)
    frozen = _FrozenInputs(captured)
    try:
        policy_path, policy_raw = frozen.dereference(manifest["evidence"]["policy_inputs"], manifest_path)
        frozen_policy = _parse(policy_raw, policy_path, "E_POLICY_SOURCE")
        _keys(frozen_policy, {"schema_version", "context", "spec_source", "anchor_selection", "fallback_sources"},
              "E_POLICY_SOURCE", "policy_input_keys", policy_path)
        proposal_source = None
        if frozen_policy["spec_source"] is not None:
            proposal_source, _ = frozen.dereference(frozen_policy["spec_source"], policy_path)
        effective = _effective_policy(policy, manifest, repo, frozen, proposal_source)
        # 必需来源由 reservation/genesis/manifest 及 schema 边推导，不取闭包自报集合。
        _verify_pending_graph(state, manifest, manifest_path, sources, effective, frozen)
        metadata_path = run / "build-metadata.json"
        metadata = _parse(frozen.read(metadata_path), metadata_path, "E_OUTPUT_CONFLICT")
        _keys(metadata, {"generated_at", "host_build_duration_ms"}, "E_OUTPUT_CONFLICT", "build_metadata_keys")
        _integer(metadata["host_build_duration_ms"], 0, "E_OUTPUT_CONFLICT")
        _id(metadata["generated_at"], "E_OUTPUT_CONFLICT")
    except ExecutorError as error:
        _fail("E_OUTPUT_CONFLICT", error.reason, error.input_ref)
    # 缺 record 的窄恢复使用冻结外部叶子；完整记录重调用保留同输入比较。
    live_origins = {source["path"] for source in sources.values()} | {
        str(manifest_path), str(run / "workflow.js"), str(run / "build-metadata.json"),
        state["genesis_ref"]["path"]}
    if (run / "build-record.json").exists() and manifest["attempt_index"] == 1:
        live_origins.update(captured)
    for origin in live_origins:
        if inputs.read(Path(origin), "E_OUTPUT_CONFLICT") != frozen.read(Path(origin), "E_OUTPUT_CONFLICT"):
            _fail("E_OUTPUT_CONFLICT", "pending_input_conflict", origin)
    record = _record(manifest, current_ref, sources, effective, state, pending, closure_ref, script_ref, metadata)
    _publish(run / "build-record.json", _canonical(record), run, resume=True)
    return {"build_record": str(run / "build-record.json"), "workflow_script": str(run / "workflow.js"), "resume_only": True}


def _reserve_build(state: Json, scope: Path, manifest: Json, manifest_ref: Json, script_ref: Json) -> Json:
    # 此函数只接受 _replay_history 的实际产物；不接收 caller 的 policy_ok。
    view = _replay_history(state)
    _require_dispatch_policy(view)
    if manifest["round"] != view["charged_rounds"] + 1 or manifest["attempt_index"] != sum(entry["event"]["kind"] == "reserve" for entry in state["events"]) + 1:
        _fail("E_PREVIOUS_IDENTITY", "round_attempt_sequence")
    event = {"schema_version": 1, "seq": len(state["events"]) + 1, "genesis": state["genesis_ref"],
             "previous_event": state["head"], "kind": "reserve", "payload": {
                 "identity": _identity(manifest), "attempt_index": manifest["attempt_index"],
                 "manifest": manifest_ref, "workflow_script": script_ref,
                 "previous_round": view["latest_round"], "previous_attempt": view["latest_attempt"]}}
    event_ref = _publish(scope / "events" / f"{event['seq']:010d}.json", _canonical(event), scope)
    return {"event": event, "ref": event_ref}


def build(repo_path: Path, manifest_path: Path, output_dir: Path) -> Json:
    started = time.monotonic_ns()
    repo = Path(repo_path).resolve()
    manifest_path = Path(manifest_path).resolve()
    inputs = _Inputs()
    manifest_raw = inputs.read(manifest_path, "E_INPUT_SCHEMA")
    manifest = _parse(manifest_raw, manifest_path)
    _validate_manifest(manifest)
    policy = _load_fixed_policy(repo, inputs)
    if manifest["require_same_admitted_roles"] != policy["require_same_admitted_roles"]:
        _fail("E_MANIFEST_MISMATCH", "guard_mismatch")
    if not policy["require_same_admitted_roles"]:
        _fail("E_UNSUPPORTED", "guard_disabled_use_legacy")
    sources = {name: inputs.reference(path, "E_CONFIG_SOURCE") for name, path in policy["paths"].items()}
    reports = repo / ".aria" / "audit-reports"
    run = _safe_write_path(Path(output_dir), reports)
    if manifest["client_round_id"] not in run.name or not run.name.startswith(f"{manifest['checkpoint']}-R{manifest['round']}-"):
        _fail("E_OUTPUT_CONFLICT", "explicit_run_key_required", run)
    scope = _safe_write_path(reports / "_executor-ledgers" / _hash(_canonical([manifest["checkpoint"], manifest["change_id"]])), reports)
    for key in EVIDENCE_KEYS:
        if key.endswith("_path"):
            _safe_write_path(_path(manifest["evidence"][key], manifest_path), run)
    with _writer_lock(scope):
        state = _load_scope(scope, manifest, inputs)
        if state["genesis"] is not None:
            if not state["events"]:
                _fail("E_POLICY_SOURCE", "incomplete_bootstrap_requires_review", scope)
            for name, source in sources.items():
                if state["genesis"]["initial_sources"][name]["sha256"] != source["sha256"]:
                    _fail("E_SOURCE_DRIFT", "active_cycle_fixed_source_changed", source["path"])
            if state["pending"] is not None:
                pending_payload = state["pending"]["event"]["payload"]
                same_manifest = pending_payload["manifest"] == {"path": str(manifest_path), "sha256": _hash(manifest_raw)}
                if same_manifest:
                    reservation_seq = state["pending"]["event"]["seq"]
                    prefix_events = state["events"][:reservation_seq - 1]
                    prefix = {**state, "events": prefix_events, "pending": None,
                        "head": prefix_events[-1]["ref"] if prefix_events else None,
                        "reserve_count": state["reserve_count"] - 1}
                    _replay_history(prefix)
                    return _resume_build(state, manifest, manifest_path, run, inputs, sources, policy, repo)
                origin = manifest["evidence"]["cycle_origin"]
                if origin is None or origin != state["genesis_ref"] or _bound_result_ref(manifest["evidence"]["previous_round"], manifest_path, pending_payload["previous_round"], scope) != pending_payload["previous_round"]:
                    _fail("E_PREVIOUS_IDENTITY", "scope_origin_or_head", manifest_path)
                _fail("E_RESOURCE_PENDING", "pending_reservation_resume_only", manifest_path)
            if manifest["evidence"]["cycle_origin"] != state["genesis_ref"]:
                _fail("E_PREVIOUS_IDENTITY", "scope_origin_required", manifest_path)
            view = _replay_history(state)
            if (_bound_result_ref(manifest["evidence"]["previous_round"], manifest_path, view["latest_round"], scope) != view["latest_round"] or
                    manifest["round"] != view["charged_rounds"] + 1 or
                    manifest["attempt_index"] != state["reserve_count"] + 1 or
                    any(a["identity"]["client_round_id"] == manifest["client_round_id"] for a in view["attempts"])):
                _fail("E_PREVIOUS_IDENTITY", "scope_latest_head_or_attempt", manifest_path)
            # Later terminal evidence changes resources only, never old votes/policy.
            resources = view["resource_view"]
            preflight = manifest["evidence"]["dispatch_preflight"]
            incoming = _Inputs()
            preflight_reference = None
            if preflight is not None:
                calls, runs = _resource_state(view["resource_attempts"],
                    inputs=_FrozenInputs(view["frozen_raw"]), observes=state["events"], scope=scope)
                preflight_reference, observations = _read_preflight(preflight, manifest_path, incoming)
                _observe_resources(calls, runs, observations)
                resources = _resource_summary(calls)
            if not resources["next_round_dispatch_allowed"]:
                _fail("E_RESOURCE_PENDING", "prefix_unknown_calls")
            _require_dispatch_policy(view)
            for origin, raw in view["frozen_raw"].items():
                if origin not in inputs.raw:
                    inputs.raw[origin] = raw
            # Capture the new context/policy without re-anchoring the cycle.
            policy_path, policy_raw = inputs.dereference(manifest["evidence"]["policy_inputs"], manifest_path)
            policy_input = _parse(policy_raw, policy_path, "E_POLICY_SOURCE")
            _keys(policy_input, {"schema_version", "context", "spec_source", "anchor_selection", "fallback_sources"},
                  "E_POLICY_SOURCE", "policy_input_keys")
            _version(policy_input["schema_version"])
            inputs.dereference(policy_input["context"], policy_path)
            if policy_input["spec_source"] is not None:
                inputs.dereference(policy_input["spec_source"], policy_path)
            selection = policy_input["anchor_selection"]
            _keys(selection, {"primary_goal", "in_scope", "out_of_scope_hints"}, "E_POLICY_SOURCE", "anchor_selection_keys")
            for span in [selection["primary_goal"], *selection["in_scope"], *selection["out_of_scope_hints"]]:
                if span is not None:
                    _span(span, policy_path, inputs)
            for fallback in policy_input["fallback_sources"]:
                _keys(fallback, {"kind", "locator", "source"}, "E_POLICY_SOURCE", "fallback_keys")
                if fallback["source"] is not None:
                    inputs.dereference(fallback["source"], policy_path)
            if preflight_reference is not None:
                for raw in incoming.raw.values():
                    _freeze_blob(raw, scope)
                inputs.raw.update(incoming.raw)
                event = {"schema_version": 1, "seq": len(state["events"]) + 1,
                    "genesis": state["genesis_ref"], "previous_event": state["head"], "kind": "observe",
                    "payload": {"preflight": preflight_reference}}
                event_ref = _publish(scope / "events" / f"{event['seq']:010d}.json", _canonical(event), scope)
                state["events"].append({"event": event, "ref": event_ref}); state["head"] = event_ref
                inputs.read(Path(event_ref["path"]))
        if state["genesis"] is None and (manifest["evidence"]["previous_round"] is not None or manifest["round"] != 1 or manifest["attempt_index"] != 1):
            _fail("E_PREVIOUS_IDENTITY", "first_attempt_identity", manifest_path)
        if state["genesis"] is None and manifest["evidence"]["dispatch_preflight"] is not None:
            _fail("E_POLICY_SOURCE", "first_attempt_preflight_without_history")
        for name in ("workflow.js", "build-record.json", "input-closure.json", "build-metadata.json"):
            if (run / name).exists():
                _fail("E_OUTPUT_CONFLICT", "unreserved_existing_output", run / name)
        for key in EVIDENCE_KEYS:
            if key.endswith("_path") and _path(manifest["evidence"][key], manifest_path).exists():
                _fail("E_OUTPUT_CONFLICT", "future_locator_already_exists", manifest["evidence"][key])
        effective = _effective_policy(policy, manifest, repo, inputs)
        if state["genesis"] is None:
            observation = _origin_observation(repo, scope, manifest, inputs, manifest_path)
            # 验证政策/Span/fallback 完成后才创建 genesis；失败不预留轮次。
            policy_ref, anchor_ref = _freeze_policy_inputs(repo, manifest, manifest_path, inputs, scope)
            origin_ref = _freeze_blob(_canonical(observation), scope)
            inputs.read(Path(origin_ref["path"]))
            initial_sources = {name: _freeze_blob(inputs.raw[source["path"]], scope) for name, source in sources.items()}
            genesis = {"schema_version": 1, "algorithm_version": "canonical_v1", "audit_cycle_id": manifest["audit_cycle_id"],
                       "checkpoint": manifest["checkpoint"], "change_id": manifest["change_id"],
                       "policy_inputs": policy_ref, "anchor": anchor_ref, "origin_observation": origin_ref,
                       "initial_sources": initial_sources, "initial_max_rounds": policy["audit"]["max_rounds"]}
            genesis_ref = _publish(scope / "genesis.json", _canonical(genesis), scope)
            inputs.read(Path(genesis_ref["path"]))
            state.update({"genesis": genesis, "genesis_ref": genesis_ref})
        # 空已验证事件序列导出真实初态，且在 script/reserve 之前执行政策前置。
        _require_dispatch_policy(_replay_history(state))
        script_ref = _publish(run / "workflow.js", _workflow(manifest, _hash(manifest_raw)), run)
        inputs.read(Path(script_ref["path"]))
        metadata = {"generated_at": datetime.now(timezone.utc).isoformat(),
                    "host_build_duration_ms": max(0, (time.monotonic_ns() - started) // 1_000_000)}
        _publish(run / "build-metadata.json", _canonical(metadata), run)
        inputs.read(run / "build-metadata.json")
        closure_ref = _freeze_closure(inputs, scope, run / "input-closure.json")
        manifest_ref = {"path": str(manifest_path), "sha256": _hash(manifest_raw)}
        reservation = _reserve_build(state, scope, manifest, manifest_ref, script_ref)
        record = _record(manifest, manifest_ref, sources, effective, state, reservation, closure_ref, script_ref, metadata)
        _publish(run / "build-record.json", _canonical(record), run)
        return {"build_record": str(run / "build-record.json"), "workflow_script": str(run / "workflow.js"), "resume_only": False}


def _pointer(value: Any, pointer: str) -> Any:
    """Strict RFC 6901 lookup; no path search, aliases or inferred transcript paths."""
    code = "E_NATIVE_EVIDENCE"
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        _fail(code, "invalid_pointer")
    if not pointer:
        return value
    for token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", token):
            _fail(code, "invalid_pointer_escape")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token) and int(token) < len(value):
            value = value[int(token)]
        else:
            _fail(code, "pointer_not_found", pointer)
    return value


def _validate_report(report: Any) -> Json:
    """§8 validation also accepts preserved historical objects WITHOUT inventing raw."""
    code = "E_RAW_REPORT"
    if not isinstance(report, dict):
        _fail(code, "report_object")
    if (report.get("vote") not in ("PASS", "REVISE") or
            type(report.get("coverage_complete")) is not bool or
            any(not isinstance(report.get(k), list) for k in ("findings", "pending", "prior_findings"))):
        _fail(code, "report_fields")
    for finding in report["findings"]:
        if (not isinstance(finding, dict) or finding.get("severity") not in ("critical", "major", "minor") or
                finding.get("type") not in ("issue", "risk", "decision") or
                finding.get("category") not in ("implementation", "testing", "documentation", "architecture") or
                any(not isinstance(finding.get(k), str) for k in ("scope", "file", "failure_scenario")) or
                type(finding.get("line")) is not int or finding["line"] < 1):
            _fail(code, "finding_fields")
    if ((not report["coverage_complete"] or report["pending"] or
         any(f["severity"] in ("critical", "major") for f in report["findings"])) and report["vote"] != "REVISE"):
        _fail(code, "revise_required")
    return report


def _parse_report(raw: Any) -> Json:
    if not isinstance(raw, str):
        _fail("E_RAW_REPORT", "raw_string_required")
    text = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fenced is not None:
        text = fenced[1]
    try:
        data = text.encode("utf-8")
    except UnicodeError:
        return _fail("E_RAW_REPORT", "raw_utf8")
    return _validate_report(_parse(data, Path("raw"), "E_RAW_REPORT"))


def _normalize_native_node(t0: int, node: Any) -> Json:
    _integer(t0, 0, "E_NATIVE_TIME")
    if not isinstance(node, dict) or node.get("type") != "workflow_agent":
        _fail("E_NATIVE_EVIDENCE", "workflow_agent_required")
    for field in ("agentId", "agentType", "label"):
        _id(node.get(field), "E_NATIVE_EVIDENCE")
    if "model" not in node or (node["model"] is not None and not isinstance(node["model"], str)):
        _fail("E_NATIVE_EVIDENCE", "actual_model_required")
    if node.get("state") not in ("start", "progress", "done"):
        _fail("E_NATIVE_SCHEMA", "unknown_agent_state")
    q: Any = node.get("queuedAt")
    _integer(q, t0, "E_NATIVE_TIME")
    start, duration = node.get("startedAt"), node.get("durationMs")
    # Absence is allowed only for unfinished nodes; explicit null is not an integer.
    if "startedAt" in node:
        _integer(start, q, "E_NATIVE_TIME")
    if "durationMs" in node:
        _integer(duration, 0, "E_NATIVE_TIME")
    if node["state"] == "done":
        if start is None or duration is None:
            _fail("E_NATIVE_TIME", "done_completion_fields_required")
        completion = start + duration
    else:
        if duration is not None:
            _fail("E_NATIVE_EVIDENCE", "unfinished_with_completion_duration")
        completion = None
    return {"queued_at_ms": q, "started_at_ms": start, "duration_ms": duration,
            "completed_at_ms": completion}


_NO_HISTORICAL_REPORT = object()


def _classify_seat(t0: int, node: Any, raw: Any, *,
                   historical_report: Any = _NO_HISTORICAL_REPORT) -> Json:
    """Pure time/first-match/parser kernel. Historical objects never become raw bytes.

    Production callers never pass historical_report. The separate partial replay may
    validate a preserved report object, explicitly without a production raw hash/ref.
    """
    _integer(t0, 0, "E_NATIVE_TIME")
    result: Json = {"queued_at_ms": None, "started_at_ms": None, "duration_ms": None,
        "completed_at_ms": None, "native_deadline_ms": t0 + 300000,
        "execution_state": "not_dispatched", "unfinished_at_native_deadline": False,
        "dispatched_at_or_after_native_deadline": None, "report": None, "parse_error": None,
        "late_raw_sha256": None}
    if node is None:
        return result
    result.update(_normalize_native_node(t0, node))
    q, completion, deadline = result["queued_at_ms"], result["completed_at_ms"], result["native_deadline_ms"]
    result["dispatched_at_or_after_native_deadline"] = q >= deadline
    result["unfinished_at_native_deadline"] = q < deadline and (completion is None or completion >= deadline)
    if completion is None:
        result["execution_state"] = "dispatched_no_completion"
    elif completion - q > 120000 or completion >= deadline:
        result["execution_state"] = "completed_late"
        if isinstance(raw, str):
            try:
                result["late_raw_sha256"] = _hash(raw.encode("utf-8"))
            except UnicodeError:
                _fail("E_NATIVE_EVIDENCE", "raw_utf8")
    elif raw is None and historical_report is _NO_HISTORICAL_REPORT:
        result["execution_state"] = "completed_no_result"
    else:
        try:
            report = (_parse_report(raw) if historical_report is _NO_HISTORICAL_REPORT
                      else _validate_report(historical_report))
        except ExecutorError as error:
            result.update(execution_state="completed_parse_error", parse_error=error.reason)
        else:
            result.update(execution_state="completed_admitted", report=report)
    return result


def _aggregate_admitted(roles: list[Json]) -> Json:
    """canonical_v1 over ordered, already classified native rows; never prior findings.

    Each admitted row carries index/role_id/report/raw_ref from _classify_native.
    Return conclusions/complete comparison_keys and actual population/raw vote facts.
    This pure kernel does not authenticate files or accept a claimed participant set.
    """
    if not isinstance(roles, list):
        _fail('E_PREVIOUS_IDENTITY', 'classified_roles_required')
    configured: list[str] = []
    admitted: list[str] = []
    votes: list[str] = []
    # Entries retain their exact finding and raw provenance until full-C grouping.
    buckets: dict[tuple[str, str], list[tuple[int, int, str, Json, Json]]] = {}
    states = {'not_dispatched', 'dispatched_no_completion', 'completed_late',
              'completed_no_result', 'completed_parse_error', 'completed_admitted'}
    for index, role in enumerate(roles):
        if (not isinstance(role, dict) or type(role.get('index')) is not int or
                role['index'] != index or not isinstance(role.get('role_id'), str) or
                not role['role_id'].strip() or role['role_id'] in configured or
                role.get('execution_state') not in states):
            _fail('E_PREVIOUS_IDENTITY', 'classified_role_identity')
        configured.append(role['role_id'])
        if role['execution_state'] != 'completed_admitted':
            continue
        report = _validate_report(role.get('report'))
        raw_ref = role.get('raw_ref')
        if not isinstance(raw_ref, dict):
            _fail('E_POLICY_SOURCE', 'admitted_raw_reference')
        _keys(raw_ref, {'file', 'pointer'}, 'E_POLICY_SOURCE', 'admitted_raw_reference')
        _ref_shape(raw_ref['file'])
        _id(raw_ref['pointer'], 'E_POLICY_SOURCE')
        admitted.append(role['role_id'])
        votes.append(report['vote'])
        for finding_index, finding in enumerate(report['findings']):
            bucket = (finding['category'], finding['scope'])
            buckets.setdefault(bucket, []).append((index, finding_index, role['role_id'], finding, raw_ref))
    conclusions: list[Json] = []
    severity_order = {'minor': 0, 'major': 1, 'critical': 2}
    for (category, scope), entries in buckets.items():
        severity = max((e[3]['severity'] for e in entries), key=lambda s: severity_order[s])
        conflict = 'unresolved_variants' if len({_canonical(e[3]) for e in entries}) > 1 else 'none'
        for finding_type in sorted({e[3]['type'] for e in entries}):
            typed = [e for e in entries if e[3]['type'] == finding_type]
            variants: dict[bytes, Json] = {}
            found_by: list[str] = []
            for role_index, finding_index, role_id, finding, raw_ref in typed:
                encoded = _canonical(finding)
                variant = variants.setdefault(encoded, {'finding': json.loads(encoded), 'members': []})
                variant['members'].append({'role_id': role_id, 'role_index': role_index,
                    'finding_index': finding_index, 'raw_ref': json.loads(_canonical(raw_ref))})
                if role_id not in found_by:
                    found_by.append(role_id)
            earliest = typed[0][3]
            summary = earliest.get('summary')
            if not isinstance(summary, str):
                summary = earliest['failure_scenario']
            conclusions.append({'id': _hash(f'{category}:{scope}:{severity}:{finding_type}'.encode('utf-8'))[:8],
                'type': finding_type, 'severity': severity, 'category': category, 'scope': scope,
                'summary': ' '.join(summary.split()[:50]), 'found_by': found_by,
                'variants': [variants[key] for key in sorted(variants)], 'conflict_state': conflict})
    key_fields = ('type', 'severity', 'category', 'scope')
    conclusions.sort(key=lambda c: tuple(c[k] for k in key_fields))
    keys = sorted({tuple(c[k] for k in key_fields) for c in conclusions})
    return {'configured_roles': configured, 'admitted_roles': admitted,
            'conclusions': conclusions, 'comparison_keys': [list(key) for key in keys],
            'incomplete': len(admitted) != len(configured), 'all_failed_void': not admitted,
            'unanimous_pass': bool(votes) and all(vote == 'PASS' for vote in votes)}


def _round_identity(identity: Any) -> None:
    code = 'E_PREVIOUS_IDENTITY'
    _keys(identity, set(IDENTITY_KEYS), code, 'round_identity_keys')
    _integer(identity['round'], 1, code)
    for key in IDENTITY_KEYS:
        if key != 'round':
            _id(identity[key], code)
    if (identity['checkpoint'] not in CHECKPOINTS or
            re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', identity['candidate_sha']) is None):
        _fail(code, 'round_identity')


def _compare_rounds(current: Json, previous: Json | None, require_same_admitted_roles: bool) -> Json:
    """Pair {identity, roles} facts from adjacent VERIFIED effective heads only.

    No files/head validation is implied here: the history caller supplies that
    proof. Missing legacy roles/identity is diagnostic, never equality evidence.
    The false vector tests the formula, not production's untouched legacy route.
    """
    if type(require_same_admitted_roles) is not bool:
        _fail('E_CONFIG_TYPE', 'guard_not_boolean')
    _round_identity(current.get('identity'))
    identity = current['identity']
    aggregate = _aggregate_admitted(current['roles'])
    prior: Json | None = None
    if previous is None:
        if identity['round'] != 1:
            _fail('E_PREVIOUS_REQUIRED', 'adjacent_effective_round_required')
        reason = 'first_round'
    else:
        if not isinstance(previous, dict) or identity['round'] == 1:
            _fail('E_PREVIOUS_IDENTITY', 'unexpected_previous_round')
        if 'identity' in previous:
            _round_identity(previous['identity'])
            old = previous['identity']
            if (any(old[k] != identity[k] for k in ('audit_cycle_id', 'checkpoint', 'change_id')) or
                    old['round'] != identity['round'] - 1 or old['client_round_id'] == identity['client_round_id']):
                _fail('E_PREVIOUS_IDENTITY', 'previous_round_identity')
            if 'roles' in previous:
                prior = _aggregate_admitted(previous['roles'])
        if prior is None:
            reason = 'missing_participant_evidence'
        elif not aggregate['admitted_roles'] or not prior['admitted_roles']:
            reason = 'empty_population'
        elif set(aggregate['admitted_roles']) != set(prior['admitted_roles']):
            reason = 'population_changed'
        else:
            reason = 'same_population'
    equal = prior is not None and aggregate['comparison_keys'] == prior['comparison_keys']
    comparable = reason == 'same_population' if require_same_admitted_roles else None
    stable = equal and (not require_same_admitted_roles or comparable is True)
    return {**aggregate, 'conclusion_keys_equal': equal, 'population_comparable': comparable,
            'population_reason': reason if require_same_admitted_roles else 'disabled',
            'conclusions_stable': stable,
            'converged': stable and aggregate['unanimous_pass'] and not aggregate['all_failed_void']}


def _policy_leaf(value: Any) -> Json:
    _keys(value, {'value', 'source', 'pointer'}, 'E_POLICY_SOURCE', 'fixed_policy_leaf')
    _ref_shape(value['source'])
    if not isinstance(value['pointer'], str) or not value['pointer'].startswith('/'):
        _fail('E_POLICY_SOURCE', 'fixed_policy_pointer')
    return value


def _policy_reason(view: Json, identity: Json, config: Json, anchor: Json) -> str:
    if view['all_failed_void']:
        reason = 'all_failed_void'
    elif identity['round'] == 1:
        reason = 'first_round'
    elif not config['convergence_mode']['value']:
        reason = 'disabled_by_config'
    elif not view['conclusions']:
        reason = 'empty_conclusions'
    elif anchor['record']['status'] == 'missing':
        reason = 'anchor_missing_observed'
    else:
        reason = 'required'
    return reason


def _policy_drift(view: Json, attempt: Json, config: Json, anchor: Json) -> Json:
    """Consume _verify_drift facts, never a caller's skipped/required/action flag.

    Native/tool linkage and the anchor observations must already be verified by
    the file-facing caller. This kernel validates full classification coverage,
    derives request reason/partial annotations, and computes binary64 ratios.
    """
    reason = _policy_reason(view, attempt['identity'], config, anchor)
    ratio: float | None = 0.0 if reason == 'empty_conclusions' else None
    skipped = False
    drift = attempt['drift']
    if reason != 'required':
        if drift is not None:
            _fail('E_POLICY_SOURCE', 'unexpected_checker_evidence')
    else:
        if not isinstance(drift, dict):
            _fail('E_POLICY_SOURCE', 'required_checker_evidence_missing')
        calls = drift.get('auxiliary_calls')
        if not isinstance(calls, list) or len(calls) != 1 or calls[0].get('call_attempted') is not True:
            _fail('E_POLICY_SOURCE', 'verified_checker_call_required')
        call = calls[0]
        if drift.get('kind') == 'tool_error':
            failure = drift.get('tool_failure')
            if not isinstance(failure, dict):
                _fail('E_POLICY_SOURCE', 'tool_failure_evidence')
            _keys(failure, {'call', 'response'}, 'E_POLICY_SOURCE', 'tool_failure_evidence')
            for event in failure.values():
                _keys(event, {'file', 'line', 'event_uuid'}, 'E_POLICY_SOURCE', 'tool_failure_event')
                _ref_shape(event['file'])
                _integer(event['line'], 1, 'E_POLICY_SOURCE')
                _id(event['event_uuid'], 'E_POLICY_SOURCE')
            skipped = True
        elif drift.get('kind') == 'workflow':
            _ref_shape(drift.get('native_record'))
            control = drift.get('control')
            if not isinstance(control, dict):
                _fail('E_POLICY_SOURCE', 'checker_control')
            _keys(control, {'timeout_ms', 'stop_observed', 'return_reason'}, 'E_POLICY_SOURCE', 'checker_control')
            if (type(control['timeout_ms']) is not int or control['timeout_ms'] != 60000 or
                    type(control['stop_observed']) is not bool or
                    control['return_reason'] not in ('all_settled', 'control_timeout') or
                    control['stop_observed'] != (control['return_reason'] == 'control_timeout')):
                _fail('E_POLICY_SOURCE', 'checker_control')
            if control['stop_observed']:
                if call.get('settled') is not False or call.get('raw') is not None or call.get('error') is not None:
                    _fail('E_POLICY_SOURCE', 'checker_timeout_facts')
                skipped = True
            elif call.get('error') is not None:
                if not isinstance(call['error'], str) or call.get('raw') is not None or call.get('settled') is not True:
                    _fail('E_POLICY_SOURCE', 'checker_error_facts')
                skipped = True
            elif call.get('settled') is not True:
                _fail('E_POLICY_SOURCE', 'checker_completion_facts')
        else:
            _fail('E_POLICY_SOURCE', 'checker_kind')
        if not skipped:
            raw = call.get('raw')
            if not isinstance(raw, str):
                _fail('E_POLICY_SOURCE', 'checker_raw_string')
            raw_ref = call.get('raw_ref')
            _keys(raw_ref, {'file', 'pointer'}, 'E_POLICY_SOURCE', 'checker_raw_ref')
            _ref_shape(raw_ref['file'])
            _id(raw_ref['pointer'], 'E_POLICY_SOURCE')
            body = _parse(raw.encode('utf-8'), Path(raw_ref['file']['path']), 'E_POLICY_SOURCE')
            _keys(body, {'classifications'}, 'E_POLICY_SOURCE', 'checker_classifications')
            if not isinstance(body['classifications'], list):
                _fail('E_POLICY_SOURCE', 'checker_classifications_array')
            expected = {tuple(key) for key in view['comparison_keys']}
            seen: set[tuple[str, ...]] = set()
            off_topic = 0
            partial = not anchor['record']['value']['in_scope'] and not anchor['record']['value']['out_of_scope_hints']
            for item in body['classifications']:
                _keys(item, {'key', 'classification'}, 'E_POLICY_SOURCE', 'classification_keys')
                key = item['key']
                if not isinstance(key, list) or len(key) != 4 or any(not isinstance(k, str) for k in key):
                    _fail('E_POLICY_SOURCE', 'classification_full_key')
                full = tuple(key)
                if (full not in expected or full in seen or
                        item['classification'] not in ('on_topic', 'adjacent', 'off_topic') or
                        (partial and item['classification'] == 'off_topic')):
                    _fail('E_POLICY_SOURCE', 'classification_coverage_or_partial')
                seen.add(full)
                off_topic += item['classification'] == 'off_topic'
            if seen != expected:
                _fail('E_POLICY_SOURCE', 'classification_coverage')
            ratio = off_topic / len(view['conclusions']) if view['conclusions'] else 0.0
    action = 'NONE'
    if ratio is not None:
        if ratio >= config['refocus_threshold']['value']:
            action = 'REFOCUS_ROUND'
        elif ratio >= config['warn_threshold']['value']:
            action = 'WARN'
    return {'drift_required': reason == 'required', 'drift_reason': reason, 'drift_ratio': ratio,
            'drift_check_skipped': skipped, 'drift_action': action}


def _apply_policy(genesis: Json, attempts: list[Json], effective_config: Json, anchor: Json) -> Json:
    """Fold an entire VERIFIED prefix from zero, without accepting derived state.

    attempts are ordered {identity, attempt_index, audit: _classify_native output,
    drift: _verify_drift output|null}. genesis/config/anchor are already validated
    frozen inputs; anchor={record: AnchorRecord, source: FileRef}. This is NOT an
    authorization or file-verification API. Dispositions attached to attempts are
    original-source projections produced only by the frozen ledger replay.

    Return {attempts: [comparison/aggregation/verdict/policy/policy_sources],
    policy: final prefix policy, policy_sources: per-value source dependencies}.
    Resource permission stays exclusively in _resource_view; no merge permission.
    """
    limit = genesis.get('initial_max_rounds')
    _integer(limit, 1, 'E_POLICY_SOURCE')
    _keys(genesis.get('initial_sources'), set(SOURCE_NAMES), 'E_POLICY_SOURCE', 'policy_genesis_sources')
    for source in genesis['initial_sources'].values():
        _ref_shape(source)
    guard = _policy_leaf(effective_config.get('require_same_admitted_roles'))
    if type(guard['value']) is not bool:
        _fail('E_CONFIG_TYPE', 'guard_not_boolean')
    limit_source = _policy_leaf(effective_config.get('max_rounds'))
    config = effective_config.get('drift_guard')
    if not isinstance(config, dict):
        _fail('E_POLICY_SOURCE', 'drift_fixed_config')
    for key in ('warn_threshold', 'refocus_threshold', 'convergence_mode'):
        _policy_leaf(config.get(key))
    for key in ('warn_threshold', 'refocus_threshold'):
        threshold = config[key]['value']
        if (isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or
                not math.isfinite(threshold) or not 0 <= threshold <= 1):
            _fail('E_POLICY_SOURCE', 'drift_threshold')
    if (config['warn_threshold']['value'] > config['refocus_threshold']['value'] or
            type(config['convergence_mode']['value']) is not bool):
        _fail('E_POLICY_SOURCE', 'drift_config')
    _keys(anchor, {'record', 'source'}, 'E_POLICY_SOURCE', 'frozen_anchor_input')
    _ref_shape(anchor['source'])
    record = anchor['record']
    _keys(record, {'schema_version', 'status', 'value', 'observations'}, 'E_POLICY_SOURCE', 'anchor_record')
    _version(record['schema_version'])
    _ref_shape(record['observations'])
    if record['status'] == 'present':
        value = record['value']
        _keys(value, {'checkpoint', 'primary_goal', 'in_scope', 'out_of_scope_hints', 'source_sha'},
              'E_POLICY_SOURCE', 'anchor_value')
        _id(value['primary_goal'], 'E_POLICY_SOURCE')
        if value['checkpoint'] != genesis['checkpoint']:
            _fail('E_POLICY_SOURCE', 'anchor_checkpoint')
        for key in ('in_scope', 'out_of_scope_hints'):
            if not isinstance(value[key], list) or any(not isinstance(v, str) for v in value[key]):
                _fail('E_POLICY_SOURCE', 'anchor_scope')
        partial = not value['in_scope'] and not value['out_of_scope_hints']
    elif record['status'] == 'missing' and record['value'] is None:
        partial = False
    else:
        _fail('E_POLICY_SOURCE', 'anchor_status')
    contract = genesis['initial_sources']['contract']
    initial_sources = [contract, limit_source, genesis['initial_sources']['config'], genesis['initial_sources']['defaults']]
    fixed_sources = [guard, *config.values(), anchor['source'], record['observations']]
    dependencies: list[Json] = []
    disposition_sources: list[Json] = []
    policy: Json = {'algorithm_version': 'canonical_v1', 'is_refocus': False,
        'consecutive_refocus_count': 0, 'pending_refocus': False, 'charged_rounds': 0,
        'effective_limit': limit, 'remaining_rounds': limit, 'drift_required': False,
        'drift_reason': 'first_round', 'drift_ratio': None, 'drift_check_skipped': False,
        'drift_action': 'NONE', 'terminal_state': None, 'overridden_by_user': False,
        'degraded': False, 'anchor_scope_empty': partial,
        'drift_classification_confidence': 'low' if partial else None}

    def sources() -> Json:
        result = {key: json.loads(_canonical([*initial_sources, *fixed_sources, *dependencies])) for key in policy}
        result['algorithm_version'] = [dict(contract)]
        result['effective_limit'] = json.loads(_canonical([*initial_sources, *disposition_sources]))
        for key in ('anchor_scope_empty', 'drift_classification_confidence'):
            result[key] = json.loads(_canonical([contract, anchor['source']]))
        return result

    rows: list[Json] = []
    previous: Json | None = None
    normal: list[list[list[str]]] = []
    clients: set[str] = set()
    runs: set[str] = set()
    if not isinstance(attempts, list):
        _fail('E_POLICY_SOURCE', 'verified_attempts_required')
    for attempt_index, attempt in enumerate(attempts, 1):
        # No input count/remaining/approved flag participates in this decision.
        _require_dispatch_policy(policy)
        _round_identity(attempt.get('identity'))
        identity = attempt['identity']
        if (type(attempt.get('attempt_index')) is not int or attempt['attempt_index'] != attempt_index or
                identity['round'] != policy['charged_rounds'] + 1 or
                any(identity[k] != genesis[k] for k in ('audit_cycle_id', 'checkpoint', 'change_id')) or
                identity['client_round_id'] in clients):
            _fail('E_PREVIOUS_IDENTITY', 'policy_attempt_sequence')
        clients.add(identity['client_round_id'])
        audit = attempt['audit']
        _ref_shape(audit.get('native_record'))
        _id(audit.get('workflow_run_id'), 'E_PREVIOUS_IDENTITY')
        if audit['workflow_run_id'] in runs:
            _fail('E_PREVIOUS_IDENTITY', 'policy_duplicate_run')
        runs.add(audit['workflow_run_id'])
        dependencies.append(audit['native_record'])
        dependencies.extend(role['raw_ref'] for role in audit['roles'] if role.get('raw_ref') is not None)
        current = {'identity': identity, 'roles': audit['roles']}
        view = _compare_rounds(current, previous, guard['value'])
        drift = _policy_drift(view, attempt, config, anchor)
        if attempt['drift'] is not None:
            evidence = attempt['drift']
            if evidence.get('native_record') is not None:
                run = evidence.get('workflow_run_id')
                _id(run, 'E_PREVIOUS_IDENTITY')
                if run in runs:
                    _fail('E_PREVIOUS_IDENTITY', 'policy_duplicate_run')
                runs.add(run)
                dependencies.append(evidence['native_record'])
            else:
                dependencies.extend(evidence['tool_failure'].values())
        is_refocus = policy['pending_refocus']
        policy = {**policy, **drift, 'is_refocus': is_refocus}
        action = drift['drift_action']
        if not view['all_failed_void']:
            policy['charged_rounds'] += 1
            if action == 'REFOCUS_ROUND':
                policy['consecutive_refocus_count'] += 1
                if policy['consecutive_refocus_count'] >= 2:
                    action = policy['drift_action'] = 'TERMINATE'
            elif drift['drift_ratio'] is not None:
                policy['consecutive_refocus_count'] = 0
            policy['remaining_rounds'] = max(0, limit - policy['charged_rounds'])
            previous = current
            if not is_refocus:
                normal.append(view['comparison_keys'])
            view['unanimous_pass'] = view['unanimous_pass'] and action != 'WARN'
            view['converged'] = view['converged'] and view['unanimous_pass'] and action not in ('REFOCUS_ROUND', 'TERMINATE')
            oscillating = (not is_refocus and len(normal) >= 3 and
                           normal[-1] == normal[-3] and normal[-1] != normal[-2])
            terminal = ('CONVERGED' if view['converged'] else 'DRIFT_TERMINATED' if action == 'TERMINATE'
                        else 'OSCILLATION' if oscillating else 'MAX_ROUNDS_EXHAUSTED'
                        if policy['remaining_rounds'] == 0 else None)
            policy['terminal_state'] = terminal
            policy['pending_refocus'] = action == 'REFOCUS_ROUND' and terminal is None
        severity = {c['severity'] for c in view['conclusions']}
        verdict = ('FAIL' if 'critical' in severity or action == 'TERMINATE' else
                   'PASS_WITH_WARNINGS' if 'major' in severity else 'PASS')
        rows.append({**view, 'verdict': verdict, 'policy': dict(policy), 'policy_sources': sources()})
        # The decision happened AFTER this base row; never retroactively rewrite it.
        if 'disposition' in attempt:
            decision = attempt['disposition']
            policy = _disposition_view(policy, decision['action'])
            limit = policy['effective_limit']
            disposition_sources.extend([decision['evidence'], decision['sidecar']])
            dependencies.extend([decision['evidence'], decision['sidecar']])
    return {'attempts': rows, 'policy': dict(policy), 'policy_sources': sources()}


def _interruption_body(event: Any, agent_id: str, event_uuid: str) -> bool:
    """Validate a full event, not marker substrings or a human-authorization claim."""
    if (not isinstance(event, dict) or event.get("type") != "user" or
            event.get("agentId") != agent_id or event.get("uuid") != event_uuid):
        _fail("E_NATIVE_EVIDENCE", "interruption_event_identity")
    message = event.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        _fail("E_NATIVE_EVIDENCE", "interruption_message_role")
    body = message.get("content")
    if isinstance(body, list):
        if not body or any(not isinstance(b, dict) or b.get("type") != "text" or
                           not isinstance(b.get("text"), str) for b in body):
            _fail("E_NATIVE_EVIDENCE", "interruption_text_blocks")
        body = "".join(b["text"] for b in body)
    if body not in ("[Request interrupted by user]", "[Request interrupted by user for tool use]"):
        _fail("E_NATIVE_EVIDENCE", "interruption_full_body")
    return True


def _verify_termination(native: Json, index: Json, index_path: Path, inputs: _Inputs) -> dict[str, Json]:
    """Both audit and drift indexes carry these same explicit TerminationLinks.

    Every supplied reference is checked, including links on done nodes. No reference
    is the only unknown case; a broken reference is never silently discarded.
    """
    code = "E_NATIVE_EVIDENCE"
    if index.get("workflow_run_id") != native.get("runId"):
        _fail(code, "termination_run_mismatch", index_path)
    links = index.get("termination_refs")
    if not isinstance(links, list):
        _fail(code, "termination_refs_array", index_path)
    verified: dict[str, Json] = {}
    for link in links:
        _keys(link, {"native_pointer", "agent_id", "event"}, code, "termination_link")
        _id(link["agent_id"], code)
        pointer = link["native_pointer"]
        if not isinstance(pointer, str) or re.fullmatch(r"/workflowProgress/(0|[1-9][0-9]*)", pointer) is None:
            _fail(code, "termination_node_pointer", index_path)
        node = _pointer(native, pointer)
        if (not isinstance(node, dict) or node.get("type") != "workflow_agent" or
                node.get("agentId") != link["agent_id"] or pointer in verified):
            _fail(code, "termination_node_identity", index_path)
        event_ref = link["event"]
        _keys(event_ref, {"file", "line", "agent_id", "event_uuid"}, code, "jsonl_ref")
        _integer(event_ref["line"], 1, code)
        _id(event_ref["event_uuid"], code)
        if event_ref["agent_id"] != link["agent_id"]:
            _fail(code, "termination_agent_mismatch", index_path)
        path, data = inputs.dereference(event_ref["file"], index_path, code)
        # JSONL is LF-delimited bytes. Unicode U+2028/U+2029 inside JSON is NOT a line break.
        lines = data.split(b"\n")
        if event_ref["line"] > len(lines) or not lines[event_ref["line"] - 1]:
            _fail(code, "jsonl_line_bounds", path)
        event = _parse(lines[event_ref["line"] - 1], path, code)
        _interruption_body(event, link["agent_id"], event_ref["event_uuid"])
        verified[pointer] = {**event_ref, "file": {"path": str(path), "sha256": _hash(data)}}
    return verified


def _native_build(repo: Path, manifest_path: Path, build_path: Path, inputs: _Inputs) -> tuple[Json, Json]:
    """Validate build evidence, not prefix policy (TASK-008/010 owns full replay)."""
    code = "E_NATIVE_EVIDENCE"
    raw = inputs.read(manifest_path, "E_INPUT_SCHEMA")
    manifest = _parse(raw, manifest_path)
    _validate_manifest(manifest)
    build = _parse(inputs.read(build_path, code), build_path, code)
    _keys(build, {"schema_version", "manifest", "identity", "sources", "effective_config", "budgets", "roles",
                  "workflow_script", "attempt_index", "genesis", "prefix_head", "reservation", "input_closure",
                  "generated_at", "host_build_duration_ms"}, code, "build_record_keys", build_path)
    _version(build["schema_version"], code)
    _integer(build["attempt_index"], 1, code)
    _integer(build["host_build_duration_ms"], 0, code)
    _id(build["generated_at"], code)
    manifest_origin, manifest_raw = inputs.dereference(build["manifest"], build_path, code)
    if (manifest_origin != manifest_path or manifest_raw != raw or
            _canonical(build["identity"]) != _canonical(_identity(manifest)) or
            build["attempt_index"] != manifest["attempt_index"]):
        _fail("E_RUN_IDENTITY", "build_manifest_identity", build_path)
    if (_canonical(build["budgets"]) != _canonical(BUDGETS) or
            _canonical(build["roles"]) != _canonical(_roles(manifest))):
        _fail(code, "build_roles_or_budgets", build_path)
    _keys(build["sources"], set(SOURCE_NAMES), code, "build_sources", build_path)
    for name, path in _fixed_paths(repo).items():
        source_path, source_raw = inputs.dereference(build["sources"][name], build_path, "E_SOURCE_DRIFT")
        if source_path != path:
            _fail("E_SOURCE_DRIFT", "fixed_source_path", path)
        if inputs.read(path, "E_SOURCE_DRIFT") != source_raw:
            _fail("E_SOURCE_DRIFT", "fixed_source_changed", path)
    script_path, script = inputs.dereference(build["workflow_script"], build_path, code)
    if script != _workflow(manifest, _hash(raw)):
        _fail("E_RUN_IDENTITY", "build_script_not_generated", script_path)
    genesis_path, genesis_raw = inputs.dereference(build["genesis"], build_path, code)
    genesis = _parse(genesis_raw, genesis_path, code)
    _keys(genesis, {"schema_version", "algorithm_version", "audit_cycle_id", "checkpoint", "change_id",
                    "policy_inputs", "anchor", "origin_observation", "initial_sources", "initial_max_rounds"},
          code, "native_build_genesis", genesis_path)
    _version(genesis["schema_version"], code)
    _integer(genesis["initial_max_rounds"], 1, code)
    if (genesis["algorithm_version"] != "canonical_v1" or
            any(genesis[k] != manifest[k] for k in ("audit_cycle_id", "checkpoint", "change_id"))):
        _fail(code, "native_build_genesis_identity", genesis_path)
    if build["prefix_head"] is not None:
        inputs.dereference(build["prefix_head"], build_path, code)
    _, reserve_raw = inputs.dereference(build["reservation"], build_path, code)
    reserve = _parse(reserve_raw, build_path, code)
    _keys(reserve, {"schema_version", "seq", "genesis", "previous_event", "kind", "payload"},
          code, "native_build_reserve", build_path)
    _version(reserve["schema_version"], code)
    _integer(reserve["seq"], 1, code)
    if (reserve.get("kind") != "reserve" or
            reserve.get("genesis") != build["genesis"] or reserve.get("previous_event") != build["prefix_head"]):
        _fail(code, "build_reservation", build_path)
    payload: Any = reserve.get("payload")
    _keys(payload, {"identity", "attempt_index", "manifest", "workflow_script", "previous_round", "previous_attempt"},
          code, "reservation_payload", build_path)
    if any(_canonical(payload[k]) != _canonical(build[k]) for k in
           ("identity", "attempt_index", "manifest", "workflow_script")):
        _fail(code, "reservation_binding", build_path)
    closure_path, closure_raw = inputs.dereference(build["input_closure"], build_path, code)
    closure = _parse(closure_raw, closure_path, code)
    _keys(closure, {"schema_version", "algorithm_version", "sources"}, code, "build_closure", closure_path)
    _version(closure["schema_version"], code)
    if closure["algorithm_version"] != "canonical_v1" or not isinstance(closure["sources"], list):
        _fail(code, "build_closure_schema", closure_path)
    captured: dict[str, bytes] = {}
    for entry in closure["sources"]:
        _keys(entry, {"origin", "sha256", "blob"}, code, "closure_source", closure_path)
        _ref_shape({"path": entry["origin"], "sha256": entry["sha256"]}, code)
        origin = entry["origin"]
        if not Path(origin).is_absolute() or origin in captured:
            _fail(code, "closure_duplicate_or_relative_origin", closure_path)
        _, blob = inputs.dereference(entry["blob"], closure_path, code)
        if _hash(blob) != entry["sha256"]:
            _fail(code, "closure_blob_hash", closure_path)
        captured[origin] = blob
    if closure["sources"] != sorted(closure["sources"], key=lambda e: (e["origin"], e["sha256"])):
        _fail(code, "build_closure_order", closure_path)
    frozen = _FrozenInputs(captured)
    policy = _load_fixed_policy(repo, inputs)
    effective = _effective_policy(policy, manifest, repo, frozen)
    if _canonical(build["effective_config"]) != _canonical(effective):
        _fail(code, "build_effective_config", build_path)
    state = {"genesis": genesis, "genesis_ref": build["genesis"],
             "pending": {"event": reserve}}
    _verify_pending_graph(state, manifest, manifest_path, build["sources"], effective, frozen)
    for path in [manifest_path, script_path, *(_fixed_paths(repo).values())]:
        if inputs.read(path, code) != frozen.read(path, code):
            _fail(code, "build_closure_source_mismatch", path)
    return manifest, build


def _classify_native(repo_path: Path, manifest_path: Path, build_record_path: Path,
                     workflow_run_id: str, native_record_path: Path, index_path: Path, *,
                     inputs: _Inputs | None = None) -> Json:
    """Strict audit wrapper. No capture, collect publication or policy authorization.

    inputs may be a verified origin->frozen-bytes view. Nested refs always resolve
    against their original carrier, never a blob directory or inferred session path.
    """
    inputs = inputs if inputs is not None else _Inputs()
    repo = Path(repo_path).resolve()
    manifest_path = Path(os.path.abspath(manifest_path))
    build_record_path = Path(os.path.abspath(build_record_path))
    native_record_path = Path(os.path.abspath(native_record_path))
    index_path = Path(os.path.abspath(index_path))
    manifest, build = _native_build(repo, manifest_path, build_record_path, inputs)
    code = "E_NATIVE_EVIDENCE"
    if index_path != _path(manifest["evidence"]["post_audit_index_path"], manifest_path):
        _fail(code, "manifest_audit_index_locator", index_path)
    index = _parse(inputs.read(index_path, code), index_path, code)
    _keys(index, {"schema_version", "identity", "attempt_index", "workflow_run_id", "native_record", "termination_refs"},
          code, "audit_index_keys", index_path)
    _version(index["schema_version"], code)
    _integer(index["attempt_index"], 1, code)
    if (_canonical(index["identity"]) != _canonical(build["identity"]) or
            index["attempt_index"] != build["attempt_index"] or index["workflow_run_id"] != workflow_run_id):
        _fail(code, "audit_index_identity", index_path)
    origin, raw = inputs.dereference(index["native_record"], index_path, code)
    if origin != native_record_path:
        _fail(code, "audit_index_native_path", index_path)
    native = _parse(raw, native_record_path, code)
    if not isinstance(native, dict):
        _fail(code, "native_object", origin)
    _id(workflow_run_id, "E_RUN_IDENTITY")
    script = native.get("script")
    if not isinstance(script, str):
        _fail("E_RUN_IDENTITY", "native_script_string", origin)
    try:
        script_hash = _hash(script.encode("utf-8"))
    except UnicodeError:
        _fail("E_RUN_IDENTITY", "native_script_utf8", origin)
    if (native.get("runId") != workflow_run_id or
            script_hash != build["workflow_script"]["sha256"] or
            _canonical(native.get("args")) != _canonical({"identity": build["identity"],
                "manifest_sha256": build["manifest"]["sha256"]})):
        _fail("E_RUN_IDENTITY", "native_run_script_args", origin)
    if native.get("status") != "completed" or not isinstance(native.get("workflowProgress"), list):
        _fail(code, "complete_native_return_required", origin)
    _integer(native.get("startTime"), 0, "E_NATIVE_TIME")
    _integer(native.get("durationMs"), 0, "E_NATIVE_TIME")
    _integer(native.get("agentCount"), 0, code)
    snapshot: Any = native.get("result")
    _keys(snapshot, {"schema_version", "identity", "manifest_sha256", "control", "results"}, code, "snapshot_keys", origin)
    _version(snapshot["schema_version"], code)
    if (_canonical(snapshot["identity"]) != _canonical(build["identity"]) or
            snapshot["manifest_sha256"] != build["manifest"]["sha256"]):
        _fail("E_RUN_IDENTITY", "snapshot_identity", origin)
    control = snapshot["control"]
    _keys(control, {"round_timer_ms", "stop_observed", "return_reason"}, code, "control_keys", origin)
    _integer(control["round_timer_ms"], 1, code)
    if (control["round_timer_ms"] != 300000 or type(control["stop_observed"]) is not bool or
            control["return_reason"] not in ("all_settled", "control_timeout") or
            control["stop_observed"] != (control["return_reason"] == "control_timeout")):
        _fail(code, "control_snapshot", origin)
    snapshots = snapshot["results"]
    if not isinstance(snapshots, list) or len(snapshots) != len(build["roles"]):
        _fail(code, "snapshot_role_count", origin)
    expected = {role["label"]: role for role in build["roles"]}
    nodes: dict[str, tuple[str, Json]] = {}
    agents: set[str] = set()
    for i, node in enumerate(native["workflowProgress"]):
        if not isinstance(node, dict) or not isinstance(node.get("type"), str):
            _fail(code, "native_progress_schema", origin)
        if node["type"] != "workflow_agent":
            continue
        label = node.get("label")
        if not isinstance(label, str) or label not in expected or label in nodes:
            _fail(code, "native_label_mapping", origin)
        _normalize_native_node(native["startTime"], node)
        if node["agentType"] != expected[label]["agentType"] or node["agentId"] in agents:
            _fail(code, "native_agent_mapping", origin)
        agents.add(node["agentId"])
        nodes[label] = (f"/workflowProgress/{i}", node)
    if native["agentCount"] != len(nodes):
        _fail(code, "native_agent_count", origin)
    terminations = _verify_termination(native, index, index_path, inputs)
    native_file = {"path": str(origin), "sha256": _hash(raw)}
    roles: list[Json] = []
    intervals: list[tuple[int, int]] = []
    for role, seat in zip(build["roles"], snapshots):
        _keys(seat, {"index", "role_id", "agentType", "label", "attempted", "settled", "raw", "error"},
              code, "snapshot_seat_keys", origin)
        _integer(seat["index"], 0, code)
        if (any(seat[k] != role[k] for k in ("index", "role_id", "agentType", "label")) or
                type(seat["attempted"]) is not bool or type(seat["settled"]) is not bool or
                (seat["error"] is not None and not isinstance(seat["error"], str))):
            _fail(code, "snapshot_seat_identity", origin)
        if (control["return_reason"] == "all_settled" and
                (not seat["attempted"] or not seat["settled"])):
            _fail(code, "all_settled_incomplete_seat", origin)
        mapped = nodes.get(role["label"])
        pointer, node = mapped if mapped is not None else (None, None)
        if (seat["attempted"] != (node is not None) or
                (not seat["attempted"] and seat["settled"]) or
                (not seat["settled"] and (seat["raw"] is not None or seat["error"] is not None)) or
                (seat["error"] is not None and seat["raw"] is not None)):
            _fail(code, "snapshot_call_contradiction", origin)
        value = _classify_seat(native["startTime"], node, seat["raw"])
        if seat["settled"] and value["completed_at_ms"] is None:
            _fail(code, "settled_without_native_completion", origin)
        node_ref = {"file": native_file, "pointer": pointer} if node is not None else None
        if value["completed_at_ms"] is not None:
            termination, termination_ref = "completed", node_ref
        elif pointer in terminations:
            termination, termination_ref = "interrupted_observed", terminations[pointer]
        else:
            termination, termination_ref = "unknown", None
        raw_ref = None
        raw_hash = None
        if seat["raw"] is not None:
            raw_ref = {"file": native_file, "pointer": f"/result/results/{role['index']}/raw"}
            # For a non-string bad value the hash identifies the exact evidence FILE;
            # its pointer preserves the type. Never stringify a malformed value as a vote.
            try:
                raw_hash = (_hash(seat["raw"].encode("utf-8")) if isinstance(seat["raw"], str) else _hash(raw))
            except UnicodeError:
                _fail(code, "raw_utf8", origin)
        value.update({**role, "attempted": seat["attempted"], "settled": seat["settled"],
            "native_agent_id": node["agentId"] if node is not None else None,
            "actual_model": node["model"] if node is not None else None, "native_ref": node_ref,
            "termination_evidence": termination, "termination_ref": termination_ref,
            "raw_ref": raw_ref, "raw_sha256": raw_hash,
            "late_raw_ref": raw_ref if value["execution_state"] == "completed_late" else None,
            "late_raw_unavailable_reason": "not_captured_in_frozen_snapshot" if
                value["execution_state"] == "completed_late" and raw_ref is None else None})
        roles.append(value)
        if node is not None:
            q, completion = value["queued_at_ms"], value["completed_at_ms"]
            if completion != q:
                intervals.append((q, 1))
                if completion is not None:
                    intervals.append((completion, -1))
    active = 0
    for _, delta in sorted(intervals):
        active += delta
        if active > 2:
            _fail("E_CONCURRENCY", "native_unreturned_calls_exceed_two", origin)
    return {"workflow_run_id": workflow_run_id, "native_record": native_file,
        "native_start_time_ms": native["startTime"],
        "native_deadline_ms": native["startTime"] + 300000, "native_duration_ms": native["durationMs"],
        "native_status": native["status"], "host_build_duration_ms": build["host_build_duration_ms"],
        "control_native_alignment": "unknown", "control_origin": "timer_installation", "control_timer_ms": 300000,
        "roles": roles}


def _verify_drift(index_path: Path, request_ref: Json, checker_script_path: Path, *,
                  inputs: _Inputs | None = None) -> Json:
    """Verify frozen checker facts only; classification/policy belong to TASK-010.

    request_ref is the expected prepare artifact, not an index-selected request.
    checker_script_path is the expected tool target. A verified frozen origin view
    is also used by the renderer; no dependency falls back to mutable live bytes.
    Unsupported tool-error layouts fail closed, never become successful calls.
    """
    inputs = inputs if inputs is not None else _Inputs()
    code = "E_NATIVE_EVIDENCE"
    index_path = Path(os.path.abspath(index_path))
    checker_script_path = Path(os.path.abspath(checker_script_path))
    regenerated = _render_policy_workflow(request_ref, inputs=inputs)
    if inputs.read(checker_script_path, code) != regenerated:
        _fail("E_RUN_IDENTITY", "checker_script_not_generated", checker_script_path)
    request_path, request_raw = inputs.dereference(request_ref, index_path, code)
    request = _parse(request_raw, request_path, code)
    index = _parse(inputs.read(index_path, code), index_path, code)
    _keys(index, {"schema_version", "identity", "attempt_index", "request", "kind", "workflow_run_id",
                  "native_record", "termination_refs", "tool_failure"}, code, "drift_index_keys", index_path)
    _version(index["schema_version"], code)
    _integer(index["attempt_index"], 1, code)
    indexed_request_path, indexed_request_raw = inputs.dereference(index["request"], index_path, code)
    if (indexed_request_path != request_path or indexed_request_raw != request_raw or
            _canonical(index["identity"]) != _canonical(request["identity"]) or
            index["attempt_index"] != request["attempt_index"]):
        _fail(code, "drift_index_request_identity", index_path)
    anchor_path, anchor_raw = inputs.dereference(request["anchor"], request_path, code)
    anchor = _parse(anchor_raw, anchor_path, code)["value"]
    expected_args = {"identity": request["identity"], "request_sha256": _hash(request_raw),
                     "anchor": anchor, "conclusions": request["conclusions"]}
    checker = request["checker"]
    call: Json = {"agentType": checker["agentType"], "label": checker["label"], "call_attempted": True,
        "native_agent_id": None, "actual_model": None, "native_ref": None,
        "queued_at_ms": None, "started_at_ms": None, "duration_ms": None, "completed_at_ms": None,
        "termination_evidence": "unknown", "termination_ref": None,
        "settled": False, "raw": None, "raw_ref": None, "raw_sha256": None, "error": None}
    value: Json = {"kind": index["kind"], "request": {"path": str(request_path), "sha256": _hash(request_raw)},
        "workflow_run_id": index["workflow_run_id"], "native_record": None, "native_start_time_ms": None, "native_duration_ms": None,
        "control_origin": "timer_installation", "control_native_alignment": "unknown", "control_timer_ms": 60000,
        "control": None, "failure_observation": None, "tool_failure": None, "auxiliary_calls": [call]}
    if index["kind"] == "tool_error":
        if (index["workflow_run_id"] is not None or index["native_record"] is not None or
                index["termination_refs"] != []):
            _fail(code, "tool_error_branch_fields", index_path)
        failure = index["tool_failure"]
        _keys(failure, {"call", "response"}, code, "tool_failure_keys", index_path)

        def event(reference: Any) -> tuple[Json, Json]:
            _keys(reference, {"file", "line", "event_uuid"}, code, "session_event_ref", index_path)
            _integer(reference["line"], 1, code)
            _id(reference["event_uuid"], code)
            path, data = inputs.dereference(reference["file"], index_path, code)
            lines = data.split(b"\n")
            if reference["line"] > len(lines) or not lines[reference["line"] - 1]:
                _fail(code, "session_event_line", path)
            body = _parse(lines[reference["line"] - 1], path, code)
            if not isinstance(body, dict) or body.get("uuid") != reference["event_uuid"]:
                _fail(code, "session_event_uuid", path)
            return body, {**reference, "file": {"path": str(path), "sha256": _hash(data)}}

        tool_call, call_ref = event(failure["call"])
        response, response_ref = event(failure["response"])
        if (call_ref["file"] != response_ref["file"] or call_ref["line"] >= response_ref["line"] or
                tool_call["uuid"] == response["uuid"]):
            _fail(code, "tool_failure_session_order", index_path)
        call_message, response_message = tool_call.get("message"), response.get("message")
        if (tool_call.get("type") != "assistant" or response.get("type") != "user" or
                not isinstance(call_message, dict) or call_message.get("role") != "assistant" or
                not isinstance(response_message, dict) or response_message.get("role") != "user" or
                response.get("sourceToolAssistantUUID") != tool_call["uuid"]):
            _fail(code, "tool_failure_message_identity", index_path)
        calls, responses = call_message.get("content"), response_message.get("content")
        if not isinstance(calls, list) or not isinstance(responses, list):
            _fail("E_POLICY_SOURCE", "unsupported_workflow_tool_error_shape", index_path)
        uses = [b for b in calls if isinstance(b, dict) and b.get("type") == "tool_use"]
        results = [b for b in responses if isinstance(b, dict) and b.get("type") == "tool_result"]
        if len(uses) != 1 or len(results) != 1:
            _fail("E_POLICY_SOURCE", "unsupported_workflow_tool_error_shape", index_path)
        use, result = uses[0], results[0]
        _id(use.get("id"), code)
        if (use.get("name") != "Workflow" or result.get("tool_use_id") != use["id"] or
                result.get("is_error") is not True):
            _fail(code, "workflow_tool_error_link", index_path)
        target: Any = use.get("input")
        _keys(target, {"scriptPath", "args"}, "E_POLICY_SOURCE", "unsupported_workflow_tool_input", index_path)
        if (target["scriptPath"] != str(checker_script_path) or
                _canonical(target["args"]) != _canonical(expected_args)):
            _fail("E_RUN_IDENTITY", "workflow_tool_target", index_path)
        error_body = result.get("content")
        if isinstance(error_body, list):
            if (not error_body or any(not isinstance(b, dict) or b.get("type") != "text" or
                                      not isinstance(b.get("text"), str) for b in error_body)):
                _fail("E_POLICY_SOURCE", "unsupported_workflow_tool_error_body", index_path)
        elif not isinstance(error_body, str):
            _fail("E_POLICY_SOURCE", "unsupported_workflow_tool_error_body", index_path)
        # A failed transport is not proof that no agent exists or a slot is free.
        call.update(error=error_body, tool_call_ref=call_ref, tool_response_ref=response_ref)
        value.update(failure_observation="tool_error", control_origin=None, control_timer_ms=None,
            tool_failure={"call": call_ref, "response": response_ref})
        return value
    if (index["kind"] != "workflow" or index["tool_failure"] is not None or
            index["native_record"] is None):
        _fail(code, "workflow_branch_fields", index_path)
    _id(index["workflow_run_id"], code)
    audit_path, audit_raw = inputs.dereference(request["audit_index"], request_path, code)
    audit = _parse(audit_raw, audit_path, code)
    _keys(audit, {"schema_version", "identity", "attempt_index", "workflow_run_id", "native_record", "termination_refs"},
          code, "checker_audit_index", audit_path)
    _version(audit["schema_version"], code)
    _integer(audit["attempt_index"], 1, code)
    _id(audit["workflow_run_id"], code)
    if (_canonical(audit["identity"]) != _canonical(request["identity"]) or
            audit["attempt_index"] != request["attempt_index"] or
            audit["workflow_run_id"] == index["workflow_run_id"]):
        _fail("E_RUN_IDENTITY", "checker_not_independent_run", index_path)
    audit_native_path, audit_native_raw = inputs.dereference(audit["native_record"], audit_path, code)
    audit_native = _parse(audit_native_raw, audit_native_path, code)
    if (not isinstance(audit_native, dict) or audit_native.get("runId") != audit["workflow_run_id"] or
            not isinstance(audit_native.get("workflowProgress"), list)):
        _fail(code, "checker_audit_native_identity", audit_native_path)
    auditor_ids: set[str] = set()
    for node in audit_native["workflowProgress"]:
        if not isinstance(node, dict):
            _fail(code, "checker_audit_progress", audit_native_path)
        if node.get("type") == "workflow_agent":
            _id(node.get("agentId"), code)
            auditor_ids.add(node["agentId"])
    native_path, native_raw = inputs.dereference(index["native_record"], index_path, code)
    native = _parse(native_raw, native_path, code)
    if not isinstance(native, dict) or not isinstance(native.get("script"), str):
        _fail("E_RUN_IDENTITY", "checker_native_script", native_path)
    try:
        script = native["script"].encode("utf-8")
    except UnicodeError:
        _fail("E_RUN_IDENTITY", "checker_native_script_utf8", native_path)
    if (native.get("runId") != index["workflow_run_id"] or _hash(script) != _hash(regenerated) or
            _canonical(native.get("args")) != _canonical(expected_args)):
        _fail("E_RUN_IDENTITY", "checker_native_run_script_args", native_path)
    if native.get("status") != "completed" or not isinstance(native.get("workflowProgress"), list):
        _fail(code, "checker_complete_native_return_required", native_path)
    _integer(native.get("startTime"), 0, "E_NATIVE_TIME")
    _integer(native.get("durationMs"), 0, "E_NATIVE_TIME")
    _integer(native.get("agentCount"), 0, code)
    snapshot: Any = native.get("result")
    _keys(snapshot, {"schema_version", "identity", "request_sha256", "agentType", "label", "call_attempted",
                     "settled", "raw", "error", "control"}, code, "checker_snapshot_keys", native_path)
    _version(snapshot["schema_version"], code)
    if (_canonical(snapshot["identity"]) != _canonical(request["identity"]) or
            snapshot["request_sha256"] != _hash(request_raw) or
            snapshot["agentType"] != checker["agentType"] or snapshot["label"] != checker["label"] or
            snapshot["call_attempted"] is not True or type(snapshot["settled"]) is not bool or
            (snapshot["error"] is not None and not isinstance(snapshot["error"], str))):
        _fail(code, "checker_snapshot_identity", native_path)
    control = snapshot["control"]
    _keys(control, {"timeout_ms", "stop_observed", "return_reason"}, code, "checker_control_keys", native_path)
    _integer(control["timeout_ms"], 1, code)
    if (control["timeout_ms"] != 60000 or type(control["stop_observed"]) is not bool or
            control["return_reason"] not in ("all_settled", "control_timeout") or
            control["stop_observed"] != (control["return_reason"] == "control_timeout") or
            snapshot["settled"] == control["stop_observed"] or
            (not snapshot["settled"] and (snapshot["raw"] is not None or snapshot["error"] is not None)) or
            (snapshot["error"] is not None and snapshot["raw"] is not None)):
        _fail(code, "checker_control_snapshot", native_path)
    nodes: list[tuple[str, Json]] = []
    for i, node in enumerate(native["workflowProgress"]):
        if not isinstance(node, dict) or not isinstance(node.get("type"), str):
            _fail(code, "checker_progress_schema", native_path)
        if node["type"] != "workflow_agent":
            continue
        times = _normalize_native_node(native["startTime"], node)
        if (node["label"] != checker["label"] or node["agentType"] != checker["agentType"] or
                node["agentId"] in auditor_ids):
            _fail(code, "checker_node_identity", native_path)
        nodes.append((f"/workflowProgress/{i}", node))
        call.update(times)
    if len(nodes) > 1 or native["agentCount"] != len(nodes):
        _fail(code, "checker_single_node_count", native_path)
    if (snapshot["settled"] and snapshot["error"] is None and call["completed_at_ms"] is None):
        _fail(code, "checker_return_without_native_completion", native_path)
    terminations = _verify_termination(native, index, index_path, inputs)
    native_ref = {"path": str(native_path), "sha256": _hash(native_raw)}
    if nodes:
        pointer, node = nodes[0]
        node_ref = {"file": native_ref, "pointer": pointer}
        call.update(native_agent_id=node["agentId"], actual_model=node["model"], native_ref=node_ref)
        if call["completed_at_ms"] is not None:
            call.update(termination_evidence="completed", termination_ref=node_ref)
        elif pointer in terminations:
            call.update(termination_evidence="interrupted_observed", termination_ref=terminations[pointer])
    raw = snapshot["raw"]
    if raw is not None:
        try:
            raw_hash = _hash(raw.encode("utf-8")) if isinstance(raw, str) else _hash(native_raw)
        except UnicodeError:
            _fail(code, "checker_raw_utf8", native_path)
        call.update(raw_ref={"file": native_ref, "pointer": "/result/raw"}, raw_sha256=raw_hash)
    call.update(settled=snapshot["settled"], raw=raw, error=snapshot["error"])
    value.update(native_record=native_ref, native_start_time_ms=native["startTime"], native_duration_ms=native["durationMs"],
        control=control, verified_termination_refs=terminations,
        failure_observation="control_timeout" if control["stop_observed"] else
            "error" if snapshot["error"] is not None else None)
    return value




class _StoredObserveInputs(_Inputs):
    """Hash-addressed observe leaves, resolved using their original carriers.

    The event retains the original preflight FileRef. Its bytes and every referenced
    native/JSONL file live in blobs; no live-origin fallback is permitted on replay.
    Each observe is a separate time package, including when an origin is reused.
    """
    def __init__(self, scope: Path) -> None:
        super().__init__()
        self.scope = scope
        self.blobs = _Inputs()

    def dereference(self, value: Any, carrier: Path, code: str = "E_NATIVE_EVIDENCE") -> tuple[Path, bytes]:
        _ref_shape(value, code)
        origin = _path(value["path"], carrier)
        blob = self.scope / "blobs" / (value["sha256"] + ".blob")
        raw = self.blobs.read(blob, code)
        if _hash(raw) != value["sha256"]:
            _fail(code, "observe_blob_hash", blob)
        if str(origin) in self.raw and self.raw[str(origin)] != raw:
            _fail(code, "observe_conflicting_origin", origin)
        self.raw[str(origin)] = raw
        return origin, raw


def _read_preflight(reference: Json, carrier: Path, inputs: _Inputs) -> tuple[Json, list[Json]]:
    code = "E_NATIVE_EVIDENCE"
    path, raw = inputs.dereference(reference, carrier, code)
    preflight = _parse(raw, path, code)
    _keys(preflight, {"schema_version", "observations"}, code, "preflight_keys", path)
    _version(preflight["schema_version"], code)
    if not isinstance(preflight["observations"], list):
        _fail(code, "observations_array", path)
    observations: list[Json] = []
    seen: set[str] = set()
    for item in preflight["observations"]:
        _keys(item, {"workflow_run_id", "native_record", "termination_refs"}, code, "observation_keys", path)
        run = item["workflow_run_id"]
        _id(run, "E_RUN_IDENTITY")
        if run in seen:
            _fail(code, "duplicate_observed_run", path)
        seen.add(run)
        native_path, native_raw = inputs.dereference(item["native_record"], path, code)
        native = _parse(native_raw, native_path, code)
        if not isinstance(native, dict) or native.get("runId") != run or not isinstance(native.get("script"), str):
            _fail("E_RUN_IDENTITY", "observation_run_script", native_path)
        if (native.get("status") != "completed" or not isinstance(native.get("workflowProgress"), list) or
                not isinstance(native.get("result"), dict)):
            _fail(code, "observation_complete_native_required", native_path)
        _integer(native.get("startTime"), 0, "E_NATIVE_TIME")
        _integer(native.get("durationMs"), 0, "E_NATIVE_TIME")
        _integer(native.get("agentCount"), 0, code)
        nodes: dict[str, Json] = {}
        for i, node in enumerate(native["workflowProgress"]):
            if not isinstance(node, dict) or not isinstance(node.get("type"), str):
                _fail(code, "observation_progress", native_path)
            if node["type"] != "workflow_agent":
                continue
            _normalize_native_node(native["startTime"], node)
            if node["agentId"] in nodes:
                _fail(code, "observation_duplicate_agent", native_path)
            nodes[node["agentId"]] = {"node": node, "pointer": f"/workflowProgress/{i}"}
        if native["agentCount"] != len(nodes):
            _fail(code, "observation_agent_count", native_path)
        terms = _verify_termination(native, item, path, inputs)
        observations.append({"native": native, "nodes": nodes, "terminations": terms,
            "native_record": {"path": str(native_path), "sha256": _hash(native_raw)}})
    return {"path": str(path), "sha256": _hash(raw)}, observations


def _resource_summary(calls: list[Json], *, for_checker: bool = False) -> Json:
    unknown = [call for call in calls if call["termination_evidence"] == "unknown"]
    slots = max(0, 2 - len(unknown))
    if for_checker and slots == 0:
        _fail("E_RESOURCE_PENDING", "no_slot_for_independent_checker")
    return {"calls": calls, "unknown_calls": unknown, "available_slots": slots,
            "next_round_dispatch_allowed": not unknown}


def _observe_resources(calls: list[Json], runs: dict[str, Json], observations: list[Json]) -> None:
    """Only the fresh resource rows mutate. Never the verified audit/drift results."""
    for observation in observations:
        native = observation["native"]
        run = native["runId"]
        if run not in runs:
            _fail("E_RUN_IDENTITY", "observation_unregistered_run")
        baseline = runs[run]
        if (native["script"] != baseline["script"] or
                _canonical(native.get("args")) != _canonical(baseline.get("args"))):
            _fail("E_RUN_IDENTITY", "observation_script_args")
        if _canonical(native["result"]) != _canonical(baseline["result"]):
            _fail("E_NATIVE_EVIDENCE", "observation_snapshot_changed")
        if native["startTime"] != baseline["startTime"]:
            _fail("E_NATIVE_TIME", "observation_start_time_changed")
        if native["durationMs"] < baseline["durationMs"]:
            _fail("E_NATIVE_TIME", "observation_duration_regressed")
        rows = [row for row in calls if row["workflow_run_id"] == run and row["native_ref"] is not None]
        if set(observation["nodes"]) != {row["native_agent_id"] for row in rows}:
            _fail("E_NATIVE_EVIDENCE", "observation_call_population")
        for row in rows:
            mapped = observation["nodes"][row["native_agent_id"]]
            node, pointer = mapped["node"], mapped["pointer"]
            if node["label"] != row["label"] or node["agentType"] != row["agentType"]:
                _fail("E_NATIVE_EVIDENCE", "observation_call_identity")
            times = _normalize_native_node(native["startTime"], node)
            if times["queued_at_ms"] != row["queued_at_ms"]:
                _fail("E_NATIVE_TIME", "observation_queue_changed")
            for key in ("started_at_ms", "duration_ms", "completed_at_ms"):
                if row[key] is not None and times[key] != row[key]:
                    _fail("E_NATIVE_TIME", "observation_known_time_changed")
            row.update(times)
            node_ref = {"file": observation["native_record"], "pointer": pointer}
            row["native_ref"] = node_ref
            if times["completed_at_ms"] is not None:
                row.update(termination_evidence="completed", termination_ref=node_ref)
            elif pointer in observation["terminations"]:
                row.update(termination_evidence="interrupted_observed",
                           termination_ref=observation["terminations"][pointer])
            # An absent newer interruption reference cannot erase a verified one.
        runs[run] = native


def _resource_state(attempts: list[Json], *, inputs: _Inputs | None = None,
                    observes: list[Json] | None = None, scope: Path | None = None
                    ) -> tuple[list[Json], dict[str, Json]]:
    """Fold ALL verified _classify_native/_verify_drift outputs, including voids.

    TASK-008 supplies the complete recursively verified attempt history; this is
    not its replacement or a policy gate. No self-reported complete/policy/allowed
    field is consumed. Every audit source population is cross-checked, even if the
    caller shortens its rows. Observes supplement evidence, not the set of calls.
    Tool failures without a native identity remain unknown and cannot be released
    by guessing a later run. Interrupted is an observation, not OS exit/authority.
    """
    inputs = inputs if inputs is not None else _Inputs()
    calls: list[Json] = []
    runs: dict[str, Json] = {}
    code = "E_NATIVE_EVIDENCE"
    for attempt in attempts:
        if not isinstance(attempt, dict):
            _fail(code, "verified_attempt_required")
        audit = "roles" in attempt
        rows = attempt.get("roles" if audit else "auxiliary_calls")
        if not isinstance(rows, list):
            _fail(code, "verified_call_rows_required")
        run = attempt.get("workflow_run_id")
        native_ref = attempt.get("native_record")
        if not audit and native_ref is None:
            # The verified tool-error/failed pre-node call is never a free slot.
            if len(rows) != 1 or rows[0].get("call_attempted") is not True:
                _fail(code, "unknown_auxiliary_call_required")
            row = rows[0]
            calls.append({"workflow_run_id": run, "native_agent_id": None,
                "agentType": row["agentType"], "label": row["label"], "native_ref": None,
                "queued_at_ms": None, "started_at_ms": None, "duration_ms": None,
                "completed_at_ms": None, "termination_evidence": "unknown", "termination_ref": None,
                "tool_call_ref": row.get("tool_call_ref"), "tool_response_ref": row.get("tool_response_ref")})
            continue
        _id(run, "E_RUN_IDENTITY")
        if not isinstance(run, str):
            _fail("E_RUN_IDENTITY", "resource_run_string")
        native_path, raw = inputs.dereference(native_ref, Path("/"), code)
        native = _parse(raw, native_path, code)
        if (not isinstance(native, dict) or native.get("runId") != run or run in runs or
                native.get("startTime") != attempt.get("native_start_time_ms")):
            _fail("E_RUN_IDENTITY", "resource_native_identity", native_path)
        runs[run] = native
        nodes = {f"/workflowProgress/{i}": node for i, node in enumerate(native["workflowProgress"])
                 if node["type"] == "workflow_agent"}
        if audit:
            snapshots = native["result"]["results"]
            if (len(rows) != len(snapshots) or any(
                    row.get("attempted") is not snap["attempted"] or
                    any(row.get(k) != snap[k] for k in ("index", "role_id", "label", "agentType"))
                    for row, snap in zip(rows, snapshots))):
                _fail(code, "resource_audit_population", native_path)
        elif len(rows) != 1 or rows[0].get("call_attempted") is not True:
            _fail(code, "resource_checker_population", native_path)
        mapped: set[str] = set()
        for row in rows:
            attempted = row.get("attempted" if audit else "call_attempted")
            if type(attempted) is not bool:
                _fail(code, "resource_attempted_boolean")
            if not attempted:
                if row.get("native_ref") is not None:
                    _fail(code, "unattempted_native_call")
                continue
            node_ref = row.get("native_ref")
            if node_ref is None and not audit and not nodes:
                calls.append({"workflow_run_id": run, "native_agent_id": None,
                    "agentType": row["agentType"], "label": row["label"], "native_ref": None,
                    "queued_at_ms": None, "started_at_ms": None, "duration_ms": None,
                    "completed_at_ms": None, "termination_evidence": "unknown", "termination_ref": None})
                continue
            _keys(node_ref, {"file", "pointer"}, code, "resource_native_ref")
            if not isinstance(node_ref, dict):
                _fail(code, "resource_native_ref")
            row_path, row_raw = inputs.dereference(node_ref["file"], native_path, code)
            pointer = node_ref["pointer"]
            if row_path != native_path or row_raw != raw or pointer not in nodes or pointer in mapped:
                _fail(code, "resource_call_source")
            mapped.add(pointer)
            node = nodes[pointer]
            if (row.get("native_agent_id") != node["agentId"] or row.get("label") != node["label"] or
                    row.get("agentType") != node["agentType"]):
                _fail(code, "resource_call_mapping")
            times = _normalize_native_node(native["startTime"], node)
            if any(row.get(key) != value for key, value in times.items()):
                _fail("E_NATIVE_TIME", "resource_baseline_times")
            termination, term_ref = "unknown", None
            supplied_term = row.get("termination_ref")
            if row.get("termination_evidence") == "interrupted_observed":
                _keys(supplied_term, {"file", "line", "agent_id", "event_uuid"}, code, "resource_interruption")
                terms = _verify_termination(native, {"workflow_run_id": run, "termination_refs": [{
                    "native_pointer": pointer, "agent_id": node["agentId"], "event": supplied_term}]},
                    native_path, inputs)
                termination, term_ref = "interrupted_observed", terms[pointer]
            if times["completed_at_ms"] is not None:
                termination, term_ref = "completed", node_ref
            if row.get("termination_evidence") != termination:
                _fail(code, "resource_termination_contradiction")
            calls.append({"workflow_run_id": run, "native_agent_id": node["agentId"],
                "agentType": node["agentType"], "label": node["label"], "native_ref": node_ref,
                **times, "termination_evidence": termination, "termination_ref": term_ref})
        if mapped != set(nodes):
            _fail(code, "resource_missing_attempted_calls")
    for entry in observes or []:
        event = entry["event"]
        if event["kind"] != "observe":
            continue
        if scope is None:
            _fail(code, "observe_scope_required")
        _keys(event["payload"], {"preflight"}, code, "observe_payload")
        _, observations = _read_preflight(event["payload"]["preflight"], Path(entry["ref"]["path"]),
                                          _StoredObserveInputs(scope))
        _observe_resources(calls, runs, observations)
    return calls, runs


def _resource_view(attempts: list[Json], *, inputs: _Inputs | None = None,
                   observes: list[Json] | None = None, scope: Path | None = None,
                   for_checker: bool = False) -> Json:
    """Rebuild the resource-only view from the complete verified prefix."""
    calls, _ = _resource_state(attempts, inputs=inputs, observes=observes, scope=scope)
    return _resource_summary(calls, for_checker=for_checker)


def _apply_preflight(state: Json, scope: Path, attempts: list[Json], preflight_ref: Json,
                     carrier: Path, *, inputs: _Inputs | None = None) -> Json:
    """Validate the entire observation transaction before freezing/appending.

    Caller supplies verified attempt outputs, never a policy boolean. This short
    transaction can append evidence while a reservation is pending, but cannot
    dispatch, commit it, consume a round or open any budget/terminal policy gate.
    """
    with _writer_lock(scope):
        genesis = state["genesis"]
        manifest = {key: genesis[key] for key in ("audit_cycle_id", "checkpoint", "change_id")}
        manifest["evidence"] = {"cycle_origin": state["genesis_ref"]}
        actual = _load_scope(scope, manifest, _Inputs())
        if actual["head"] != state["head"] or actual["genesis_ref"] != state["genesis_ref"]:
            _fail("E_SCOPE_BUSY", "observe_prefix_changed")
        calls, runs = _resource_state(attempts, inputs=inputs, observes=actual["events"], scope=scope)
        incoming = _Inputs()
        reference, observations = _read_preflight(preflight_ref, carrier, incoming)
        _observe_resources(calls, runs, observations)
        for raw in incoming.raw.values():
            _freeze_blob(raw, scope)
        event = {"schema_version": 1, "seq": len(actual["events"]) + 1,
            "genesis": actual["genesis_ref"], "previous_event": actual["head"],
            "kind": "observe", "payload": {"preflight": reference}}
        event_ref = _publish(scope / "events" / f"{event['seq']:010d}.json", _canonical(event), scope)
        actual["events"].append({"event": event, "ref": event_ref})
        actual["head"] = event_ref
        state.clear()
        state.update(actual)
        return _resource_summary(calls)



def _required_ref(value: Any, carrier: Path, code: str = 'E_POLICY_SOURCE') -> Json:
    _ref_shape(value, code)
    reference = _resolved_ref(value, carrier)
    if reference is None:
        _fail(code, 'required_reference', carrier)
    return reference


def _make_policy_request(manifest: Json, build_record: Json, audit: Json, anchor: Json,
                         audit_index: Json, input_closure: Json) -> Json:
    """Projection of verified inputs; not a caller authorization surface."""
    view = _aggregate_admitted(audit['roles'])
    identity = _identity(manifest)
    reason = _policy_reason(view, identity, build_record['effective_config']['drift_guard'], anchor)
    carrier = Path(build_record['manifest']['path'])
    genesis_ref = _required_ref(build_record['genesis'], carrier)
    return {'schema_version': 1, 'algorithm_version': 'canonical_v1', 'identity': identity,
        'attempt_index': manifest['attempt_index'], 'genesis': genesis_ref,
        'anchor': _required_ref(anchor['source'], Path(genesis_ref['path'])),
        'audit_index': audit_index, 'input_closure': input_closure,
        'conclusions': view['conclusions'], 'required': reason == 'required', 'reason': reason,
        'checker': {'agentType': manifest['roles'][0]['agentType'],
                    'label': 'drift:' + identity['client_round_id'], 'timeout_ms': 60000}
                   if reason == 'required' else None}


def _prepare_policy(repo_path: Path, manifest_path: Path, build_record_path: Path,
                    workflow_run_id: str, native_record_path: Path, output: Path,
                    previous_round: Path | None = None) -> Json:
    """Seal one reservation's audit view. Never publish a result or append a commit.

    Frozen CLI native paths are bound back to their original carrier before the
    existing classifier is called. No live native/JSONL can upgrade a sealed view.
    """
    started = time.monotonic_ns()
    repo = Path(repo_path).resolve()
    manifest_path = Path(os.path.abspath(manifest_path))
    build_record_path = Path(os.path.abspath(build_record_path))
    native_record_path = Path(os.path.abspath(native_record_path))
    output = _safe_write_path(Path(os.path.abspath(output)), repo / '.aria' / 'audit-reports')
    run = build_record_path.parent
    _safe_write_path(run, repo / '.aria' / 'audit-reports')
    if build_record_path != run / 'build-record.json' or output.parent != run:
        _fail('E_OUTPUT_CONFLICT', 'prepare_run_directory', output)
    inputs = _Inputs()
    manifest, build_record = _native_build(repo, manifest_path, build_record_path, inputs)
    identity = _identity(manifest)
    if (manifest['client_round_id'] not in run.name or
            not run.name.startswith(f"{manifest['checkpoint']}-R{manifest['round']}-") or
            not output.name.startswith(f"{manifest['checkpoint']}-R{manifest['round']}-") or
            manifest['client_round_id'] not in output.name or
            not output.name.endswith('-' + manifest['change_id'] + '-aggregated.json')):
        _fail('E_OUTPUT_CONFLICT', 'explicit_run_key_required', output)
    for key in EVIDENCE_KEYS:
        if key.endswith('_path'):
            _safe_write_path(_path(manifest['evidence'][key], manifest_path), run)
    scope = _safe_write_path(repo / '.aria' / 'audit-reports' / '_executor-ledgers' /
        _hash(_canonical([manifest['checkpoint'], manifest['change_id']])), repo / '.aria' / 'audit-reports')
    if _required_ref(build_record['genesis'], build_record_path)['path'] != str(scope / 'genesis.json'):
        _fail('E_PREVIOUS_IDENTITY', 'prepare_scope_genesis', build_record_path)
    index_path = _path(manifest['evidence']['post_audit_index_path'], manifest_path)
    closure_path = run / 'audit-closure.json'
    request_path = output.with_suffix('.policy-request.json')
    script_path = run / 'policy-workflow.js'
    prepare_path = run / 'prepare-record.json'
    for path in (closure_path, request_path, script_path, prepare_path):
        _safe_write_path(path, run)
    with _writer_lock(scope):
        state = _load_scope(scope, manifest, inputs)
        pending = state['pending']
        if (pending is None or pending['ref'] != _required_ref(build_record['reservation'], build_record_path) or
                pending['event']['payload']['manifest'] != inputs.reference(manifest_path) or
                pending['event']['payload']['identity'] != identity or
                pending['event']['payload']['attempt_index'] != manifest['attempt_index']):
            _fail('E_PREVIOUS_IDENTITY', 'prepare_exact_reservation', build_record_path)
        reserve_seq = pending['event']['seq']
        prefix_events = state['events'][:reserve_seq - 1]
        prefix = {**state, 'events': prefix_events, 'pending': None,
                  'head': prefix_events[-1]['ref'] if prefix_events else None,
                  'reserve_count': state['reserve_count'] - 1}
        if build_record['prefix_head'] != prefix['head'] or state['head'] != pending['ref']:
            _fail('E_PREVIOUS_IDENTITY', 'prepare_prefix_head', build_record_path)
        history = _replay_history(prefix)
        if (manifest['round'] != history['charged_rounds'] + 1 or
                manifest['attempt_index'] != state['reserve_count'] or
                _bound_result_ref(manifest['evidence']['previous_round'], manifest_path, history['latest_round'], scope) != history['latest_round']):
            _fail('E_PREVIOUS_IDENTITY', 'prepare_history_binding', manifest_path)
        if manifest['round'] > 1 and previous_round is None:
            _fail('E_PREVIOUS_REQUIRED', 'previous_round_required', manifest_path)
        expected_previous = _resolved_ref(manifest['evidence']['previous_round'], manifest_path)
        actual_previous = inputs.reference(Path(os.path.abspath(previous_round))) if previous_round is not None else None
        if (_bound_result_ref(actual_previous, manifest_path, history['latest_round'], scope) !=
                _bound_result_ref(expected_previous, manifest_path, history['latest_round'], scope)):
            _fail('E_PREVIOUS_IDENTITY', 'prepare_previous_argument', previous_round)
        if pending['event']['payload']['previous_attempt'] != history['latest_attempt']:
            _fail('E_PREVIOUS_IDENTITY', 'prepare_previous_attempt', build_record_path)
        for origin, raw in history['frozen_raw'].items():
            inputs.raw.setdefault(origin, raw)
        prior_record: Json | None = None
        # Read metadata separately: the audit closure must never reference the
        # request, script or record that will subsequently reference that closure.
        metadata_inputs = _Inputs()
        if prepare_path.exists():
            prior_record = _parse(metadata_inputs.read(prepare_path, 'E_OUTPUT_CONFLICT'),
                                  prepare_path, 'E_OUTPUT_CONFLICT')
            if not isinstance(prior_record, dict):
                _fail('E_OUTPUT_CONFLICT', 'prepare_record_object', prepare_path)
            _keys(prior_record, {'schema_version', 'identity', 'attempt_index', 'audit_index',
                'input_closure', 'policy_request', 'policy_script', 'generated_at', 'host_prepare_duration_ms'},
                'E_OUTPUT_CONFLICT', 'prepare_record_keys', prepare_path)
            _version(prior_record['schema_version'], 'E_OUTPUT_CONFLICT')
            _integer(prior_record['attempt_index'], 1, 'E_OUTPUT_CONFLICT')
            _integer(prior_record['host_prepare_duration_ms'], 0, 'E_OUTPUT_CONFLICT')
            _id(prior_record['generated_at'], 'E_OUTPUT_CONFLICT')
            if prior_record['identity'] != identity or prior_record['attempt_index'] != manifest['attempt_index']:
                _fail('E_OUTPUT_CONFLICT', 'prepare_metadata_identity', prepare_path)
            for key in ('audit_index', 'input_closure', 'policy_request', 'policy_script'):
                if prior_record[key] is not None:
                    _ref_shape(prior_record[key], 'E_OUTPUT_CONFLICT')
            if (_required_ref(prior_record['input_closure'], prepare_path)['path'] != str(closure_path) or
                    _required_ref(prior_record['policy_request'], prepare_path)['path'] != str(request_path) or
                    _required_ref(prior_record['audit_index'], prepare_path)['path'] != str(index_path)):
                _fail('E_OUTPUT_CONFLICT', 'prepare_metadata_paths', prepare_path)
            metadata_inputs.dereference(prior_record['policy_request'], prepare_path, 'E_OUTPUT_CONFLICT')
        if closure_path.exists():
            closure_ref = metadata_inputs.reference(closure_path)
            if prior_record is not None and closure_ref != _required_ref(prior_record['input_closure'], prepare_path):
                _fail('E_POLICY_SOURCE', 'prepare_closure_hash', closure_path)
            frozen = _history_closure(closure_ref, closure_path, scope, raw=_Inputs().read(closure_path))
            for origin, raw in inputs.raw.items():
                if origin not in frozen.raw or frozen.raw[origin] != raw:
                    _fail('E_OUTPUT_CONFLICT', 'prepare_input_changed', origin)
            index = _parse(frozen.read(index_path, 'E_NATIVE_EVIDENCE'), index_path, 'E_NATIVE_EVIDENCE')
            _ref_shape(index.get('native_record'), 'E_NATIVE_EVIDENCE')
            origin = _path(index['native_record']['path'], index_path)
            blob_path = scope / 'blobs' / (index['native_record']['sha256'] + '.blob')
            _safe_write_path(blob_path, scope)
            if native_record_path not in (origin, blob_path):
                _fail('E_NATIVE_EVIDENCE', 'prepare_native_mapping', native_record_path)
            supplied = _Inputs().read(native_record_path, 'E_POLICY_SOURCE')
            if _hash(supplied) != index['native_record']['sha256']:
                _fail('E_OUTPUT_CONFLICT', 'sealed_native_changed', native_record_path)
            if native_record_path == origin:
                if _Inputs().read(index_path, 'E_OUTPUT_CONFLICT') != frozen.read(index_path):
                    _fail('E_OUTPUT_CONFLICT', 'sealed_index_changed', index_path)
            audit = _classify_native(repo, manifest_path, build_record_path, workflow_run_id,
                                     origin, index_path, inputs=frozen)
        else:
            if prior_record is not None:
                _fail('E_POLICY_SOURCE', 'prepare_closure_missing', closure_path)
            audit = _classify_native(repo, manifest_path, build_record_path, workflow_run_id,
                                     native_record_path, index_path, inputs=inputs)
            closure_ref = _freeze_closure(inputs, scope, closure_path)
            frozen = _history_closure(closure_ref, closure_path, scope, raw=_Inputs().read(closure_path))
        audit_index = {'path': str(index_path), 'sha256': _hash(frozen.read(index_path))}
        refs = {'manifest': build_record['manifest'], 'build_record': inputs.reference(build_record_path),
            'genesis': build_record['genesis'], 'reservation': build_record['reservation'],
            'workflow_script': build_record['workflow_script'], 'prefix_head': build_record['prefix_head'],
            'previous_round': pending['event']['payload']['previous_round'],
            'previous_attempt': pending['event']['payload']['previous_attempt'], 'native_record': audit['native_record'],
            'config': build_record['sources']['config'], 'defaults': build_record['sources']['defaults'],
            'audit_index': audit_index, 'input_closure': closure_ref}
        _, request = _recompute_round(repo, {'inputs': refs}, frozen, state['genesis'], history['attempts'],
            carrier=output, observes=state['events'], scope=scope, preparing=True)
        request_ref = _publish(request_path, _canonical(request), run, resume=True)
        script_ref = None
        if request['required']:
            renderer_inputs = _FrozenInputs({**frozen.raw, str(closure_path): Path(closure_ref['path']).read_bytes(),
                                             str(request_path): _canonical(request)})
            script = _render_policy_workflow(request_ref, inputs=renderer_inputs)
            script_ref = _publish(script_path, script, run, resume=True)
        elif script_path.exists():
            _fail('E_OUTPUT_CONFLICT', 'unexpected_policy_script', script_path)
        record = {'schema_version': 1, 'identity': identity, 'attempt_index': manifest['attempt_index'],
            'audit_index': audit_index, 'input_closure': closure_ref, 'policy_request': request_ref,
            'policy_script': script_ref,
            'generated_at': prior_record['generated_at'] if prior_record is not None else datetime.now(timezone.utc).isoformat(),
            'host_prepare_duration_ms': prior_record['host_prepare_duration_ms'] if prior_record is not None
                                        else (time.monotonic_ns() - started) // 1000000}
        record_ref = _publish(prepare_path, _canonical(record), run, resume=True)
        native_blob = {'path': str(scope / 'blobs' / (audit['native_record']['sha256'] + '.blob')),
                       'sha256': audit['native_record']['sha256']}
        return {'policy_request': request_ref, 'policy_script': script_ref, 'prepare_record': record_ref,
                'audit_index': audit_index, 'input_closure': closure_ref, 'native_record': native_blob}



class _RoundResourceInputs(_StoredObserveInputs):
    """Current verified capture first; immutable observe-store fallback only.

    Before final publication, new checker leaves have deliberately not been
    persisted as blobs. Resource recomputation must consume that capture rather
    than requiring its own future publication. Existing history stays frozen.
    """
    def __init__(self, frozen: _FrozenInputs, scope: Path) -> None:
        super().__init__(scope)
        self.frozen = frozen

    def read(self, path: Path, code: str = 'E_POLICY_SOURCE') -> bytes:
        if str(path) in self.frozen.raw:
            return self.frozen.read(path, code)
        return super().read(path, code)

    def dereference(self, value: Any, carrier: Path, code: str = 'E_POLICY_SOURCE') -> tuple[Path, bytes]:
        _ref_shape(value, code)
        if str(_path(value['path'], carrier)) in self.frozen.raw:
            return self.frozen.dereference(value, carrier, code)
        return super().dereference(value, carrier, code)


def _render_round(result: Json, context: str, mode: str) -> bytes:
    """Deterministic aggregate view; quality verdict stays a bare frontmatter enum."""
    if mode != 'convergence':
        _fail('E_UNSUPPORTED', 'render_convergence_required')
    ident, policy = result['identity'], result['policy']
    fields = {'checkpoint': ident['checkpoint'], 'mode': mode, 'rounds': ident['round'],
        'converged': result['converged'], 'oscillation': policy['terminal_state'] == 'OSCILLATION',
        'overridden_by_user': policy['overridden_by_user'], 'degraded': policy['degraded'],
        'drift_terminated': policy['terminal_state'] == 'DRIFT_TERMINATED',
        'drift_check_skipped': policy['drift_check_skipped'], 'is_refocus': policy['is_refocus'],
        'verdict': result['verdict'], 'timestamp': result['generated_at'], 'context': context,
        'agents': result['configured_roles']}
    front = ['---', *[key + ': ' + (value if key in ('checkpoint', 'mode', 'verdict')
                                   else _canonical(value).decode('ascii'))
                      for key, value in fields.items()], '---']
    body = ['# Audit aggregate', '', '## Verdict', result['verdict'], '',
            'Quality verdict, convergence, resource clearance and merge permission are distinct.',
            'This report does not grant merge permission.', '']
    for title, value in [('Identity', ident), ('Participation', {k: result[k] for k in
            ('configured_roles', 'dispatched_roles', 'admitted_roles', 'roles')}),
            ('Conclusions', result['conclusions']), ('Convergence', {k: result[k] for k in
            ('comparison_keys', 'conclusion_keys_equal', 'population_comparable', 'population_reason',
             'incomplete', 'all_failed_void', 'unanimous_pass', 'conclusions_stable', 'converged')}),
            ('Policy and resources', {'policy': result['policy'],
                                     'next_round_dispatch_allowed': result['next_round_dispatch_allowed']}),
            ('Clocks', result['clock'])]:
        body += ['## ' + title, '```json', _canonical(value).decode('ascii'), '```', '']
    return ('\n'.join(front + body) + '\n').encode('utf-8')


DISPOSITION_OPTIONS = [
    {'label': '接受当前结论', 'action': 'accept_current'},
    {'label': '增加轮次', 'action': 'increase_rounds'},
    {'label': '降级为单轮', 'action': 'degrade_single'},
]
DISPOSITION_KEYS = {'schema_version', 'algorithm_version', 'identity', 'target_result', 'evidence',
                    'input_closure', 'action', 'token', 'effective_limit', 'remaining_rounds',
                    'overridden_by_user', 'degraded', 'converged'}


def _parse_human_disposition(index_path: Path, target: Json, identity: Json, policy: Json,
                             *, inputs: _Inputs | None = None, scope: Path | None = None) -> Json:
    """Parse an explicitly located native question/answer, never free-form consent.

    Full JSONL byte hashes and LF line numbers are checked before native linkage.
    No historical sample, wrapper approval flag, or tool notification is authority.
    """
    inputs = inputs if inputs is not None else _Inputs()
    index = _parse(inputs.read(index_path), index_path, 'E_POLICY_SOURCE')
    _keys(index, {'schema_version', 'target_result', 'question', 'response', 'options'},
          'E_POLICY_SOURCE', 'disposition_index')
    _version(index['schema_version'])
    question_target = _required_ref(index['target_result'], index_path)
    bound = (_bound_result_ref(question_target, index_path, target, scope, inputs=inputs)
             if scope is not None else question_target)
    if bound != target:
        _fail('E_POLICY_SOURCE', 'disposition_target_binding')
    if scope is None:
        inputs.dereference(index['target_result'], index_path)
    else:
        original = _HistoryGraph(scope).leaf(target, index_path, published=True)
        inputs.raw.setdefault(target['path'], original)
    if _canonical(index['options']) != _canonical(DISPOSITION_OPTIONS):
        _fail('E_POLICY_SOURCE', 'disposition_options')
    documents: dict[str, list[Any]] = {}

    def event(reference: Any) -> tuple[Json, Path]:
        _keys(reference, {'file', 'line', 'event_uuid'}, 'E_POLICY_SOURCE', 'session_event_ref')
        _integer(reference['line'], 1, 'E_POLICY_SOURCE'); _id(reference['event_uuid'], 'E_POLICY_SOURCE')
        path, raw = inputs.dereference(reference['file'], index_path)
        if not raw.endswith(b'\n') or b'\r' in raw:
            _fail('E_POLICY_SOURCE', 'session_jsonl_incomplete', path)
        if str(path) not in documents:
            documents[str(path)] = [_parse(line, path, 'E_POLICY_SOURCE') for line in raw[:-1].split(b'\n')]
        rows = documents[str(path)]
        if (reference['line'] > len(rows) or any(not isinstance(row, dict) for row in rows) or
                sum(row.get('uuid') == reference['event_uuid'] for row in rows) != 1):
            _fail('E_POLICY_SOURCE', 'session_event_identity', path)
        value = rows[reference['line']-1]
        if value.get('uuid') != reference['event_uuid']:
            _fail('E_POLICY_SOURCE', 'session_event_line', path)
        return value, path

    try:
        question, qpath = event(index['question'])
        response, rpath = event(index['response'])
        if (question['type'] != 'assistant' or question['message']['role'] != 'assistant' or
                response['type'] != 'user' or response['message']['role'] != 'user' or
                question.get('isMeta', False) is not False or response.get('isMeta', False) is not False or
                response.get('sourceToolAssistantUUID') != question['uuid'] or
                question['uuid'] == response['uuid'] or
                (qpath == rpath and index['response']['line'] <= index['question']['line'])):
            _fail('E_POLICY_SOURCE', 'native_question_response_identity')
        qblocks, rblocks = question['message']['content'], response['message']['content']
        if not isinstance(qblocks, list) or not isinstance(rblocks, list):
            _fail('E_POLICY_SOURCE', 'native_content_array')
        calls = [b for b in qblocks if isinstance(b, dict) and b.get('type') == 'tool_use']
        answers = [b for b in rblocks if isinstance(b, dict) and b.get('type') == 'tool_result']
        if len(calls) != 1 or len(answers) != 1:
            _fail('E_POLICY_SOURCE', 'native_unique_tool_pair')
        call, answer = calls[0], answers[0]
        _id(call['id'], 'E_POLICY_SOURCE')
        if (call['name'] != 'AskUserQuestion' or answer['tool_use_id'] != call['id'] or
                answer.get('is_error', False) is not False or not isinstance(answer.get('content'), str) or
                not answer['content']):
            _fail('E_POLICY_SOURCE', 'native_tool_link')
        # Reject duplicated uses/results anywhere in the complete referenced captures.
        for path, block_type, field in [(qpath, 'tool_use', 'id'), (rpath, 'tool_result', 'tool_use_id')]:
            count = 0
            for row in documents[str(path)]:
                message = row.get('message', {})
                content = message.get('content', []) if isinstance(message, dict) else []
                if isinstance(content, list):
                    count += sum(isinstance(b, dict) and b.get('type') == block_type and b.get(field) == call['id']
                                 for b in content)
            if count != 1:
                _fail('E_POLICY_SOURCE', 'duplicate_native_tool_identity')
        _keys(call['input'], {'questions'}, 'E_POLICY_SOURCE', 'native_question_input')
        questions = call['input']['questions']
        if not isinstance(questions, list) or len(questions) != 1:
            _fail('E_POLICY_SOURCE', 'exactly_one_question')
        q = questions[0]
        _keys(q, {'question', 'header', 'options', 'multiSelect'}, 'E_POLICY_SOURCE', 'native_question_shape')
        _id(q['question'], 'E_POLICY_SOURCE'); _id(q['header'], 'E_POLICY_SOURCE')
        if q['multiSelect'] is not False or not isinstance(q['options'], list) or len(q['options']) != 3:
            _fail('E_POLICY_SOURCE', 'native_single_select')
        for option, expected in zip(q['options'], DISPOSITION_OPTIONS):
            _keys(option, {'label', 'description'}, 'E_POLICY_SOURCE', 'native_option_shape')
            if (option['label'] != expected['label'] or not isinstance(option['description'], str) or
                    re.search(r'[一-鿿]', option['description']) is None):
                _fail('E_POLICY_SOURCE', 'native_option_label_or_description')
        context = {key: identity[key] for key in ('audit_cycle_id', 'checkpoint', 'change_id')}
        context.update(target_result=question_target, used_rounds=policy['charged_rounds'], effective_limit=policy['effective_limit'])
        marker = 'audit-disposition-context='
        lines = q['question'].split('\n')
        context_lines = [line for line in lines if marker in line]
        if context_lines != [marker + _canonical(context).decode('ascii')]:
            _fail('E_POLICY_SOURCE', 'disposition_context_binding')
        result = response['toolUseResult']
        _keys(result, {'questions', 'answers', 'annotations'}, 'E_POLICY_SOURCE', 'native_answer_shape')
        if (_canonical(result['questions']) != _canonical(questions) or result['annotations'] != {} or
                not isinstance(result['answers'], dict) or set(result['answers']) != {q['question']}):
            _fail('E_POLICY_SOURCE', 'native_answer_questions_or_annotations')
        selected = result['answers'][q['question']]
        actions = [o['action'] for o in DISPOSITION_OPTIONS if o['label'] == selected]
        if len(actions) != 1:
            _fail('E_POLICY_SOURCE', 'native_answer_label')
        return {'action': actions[0], 'token': [question['uuid'], call['id'], response['uuid']]}
    except (KeyError, TypeError, ValueError, IndexError):
        return _fail('E_POLICY_SOURCE', 'unrecognized_native_disposition_layout', index_path)


def _disposition_view(policy: Json, action: str) -> Json:
    """Fold one parsed action; resources and base-row booleans are not changed."""
    if (policy['terminal_state'] != 'MAX_ROUNDS_EXHAUSTED' or policy['remaining_rounds'] != 0 or
            policy['overridden_by_user'] or policy['degraded']):
        _fail('E_POLICY_SOURCE', 'disposition_requires_unhandled_exhausted_head')
    view = dict(policy)
    if action == 'increase_rounds':
        view.update(effective_limit=policy['effective_limit'] + 2,
                    remaining_rounds=policy['effective_limit'] + 2 - policy['charged_rounds'], terminal_state=None)
    elif action == 'accept_current':
        view['overridden_by_user'] = True
    elif action == 'degrade_single':
        view['degraded'] = True
    else:
        _fail('E_POLICY_SOURCE', 'unknown_disposition_action')
    return view


def _disposition_record(target: Json, evidence: Json, closure: Json, identity: Json,
                        decision: Json, view: Json) -> Json:
    return {'schema_version': 1, 'algorithm_version': 'canonical_v1', 'identity': identity,
        'target_result': target, 'evidence': evidence, 'input_closure': closure,
        'action': decision['action'], 'token': decision['token'], 'converged': False,
        **{key: view[key] for key in ('effective_limit', 'remaining_rounds', 'overridden_by_user', 'degraded')}}


def _collect_disposition(scope: Path, manifest: Json, output: Path, index_path: Path,
                         target: Json, *, checking: bool) -> Json:
    """Inside final's lock (or strictly read-only check), publish a later decision."""
    state = _load_scope(scope, manifest, _Inputs())
    replay_state = state
    pending = state['pending']
    if pending is not None:
        seq = pending['event']['seq']
        if seq != len(state['events']):
            _fail('E_POLICY_SOURCE', 'pending_disposition_view_sequence')
        prefix = state['events'][:seq-1]
        replay_state = {**state, 'events': prefix, 'pending': None,
            'head': prefix[-1]['ref'] if prefix else None, 'reserve_count': state['reserve_count']-1}
    history = _replay_history(replay_state)
    if pending is not None:
        # A later in-flight reservation is not a result or a consumed decision.
        # Validate its structural edges and prefix binding; do not manufacture a commit.
        _HistoryGraph(scope).walk(pending['ref'], Path(pending['ref']['path']), 'event')
        payload = pending['event']['payload']
        identity = payload['identity']
        _round_identity(identity)
        if (identity['round'] != history['charged_rounds']+1 or
                payload['attempt_index'] != state['reserve_count'] or
                payload['previous_round'] != history['latest_round'] or
                payload['previous_attempt'] != history['latest_attempt'] or
                any(identity[k] != state['genesis'][k] for k in ('audit_cycle_id','checkpoint','change_id')) or
                any(a['identity']['client_round_id'] == identity['client_round_id'] for a in history['attempts'])):
            _fail('E_PREVIOUS_IDENTITY', 'pending_disposition_view_identity')
        _require_dispatch_policy(history)
        if not history['resource_view']['next_round_dispatch_allowed']:
            _fail('E_RESOURCE_PENDING', 'pending_disposition_view_resources')
    existing = [d for d in history.get('dispositions', []) if d['target_result'] == target]
    side_path = output.with_suffix('.disposition.json')
    if existing:
        decision = existing[0]
        if not checking and index_path.exists():
            current = _Inputs()
            if current.reference(index_path) != decision['evidence']:
                _fail('E_POLICY_SOURCE', 'different_disposition_request')
            side = _parse(current.read(side_path), side_path, 'E_POLICY_SOURCE')
            closure_path, closure_raw = current.dereference(side['input_closure'], side_path)
            frozen = _history_closure(side['input_closure'], side_path, scope, raw=closure_raw)
            # An idempotent write request must retain every submitted evidence byte.
            index = _parse(current.read(index_path), index_path, 'E_POLICY_SOURCE')
            for key in ('question', 'response'):
                source = _path(index[key]['file']['path'], index_path)
                if current.read(source) != frozen.read(source):
                    _fail('E_POLICY_SOURCE', 'different_disposition_request')
        return {'sidecar': decision['sidecar'], 'view': decision['view']}
    if side_path.exists():
        _fail('E_POLICY_SOURCE', 'sidecar_without_disposition_event', side_path)
    if checking or not index_path.exists():
        return {}
    if (history['latest_round'] != target or not history['rounds'] or
            history['rounds'][-1]['all_failed_void'] or state['pending'] is not None):
        _fail('E_POLICY_SOURCE', 'disposition_not_current_head')
    capture = _Inputs()
    evidence = capture.reference(index_path)
    decision = _parse_human_disposition(index_path, target, manifest, history, inputs=capture, scope=scope)
    if any(tuple(d['token']) == tuple(decision['token']) for d in history.get('dispositions', [])):
        _fail('E_POLICY_SOURCE', 'disposition_token_replay')
    policy = {key: history[key] for key in history['rounds'][-1]['policy']}
    view = _disposition_view(policy, decision['action'])
    # All referenced history is retained, but mutable JSONL captures may have grown.
    for origin, raw in history['frozen_raw'].items():
        capture.raw.setdefault(origin, raw)
    closure_path = output.with_suffix('.disposition-closure.json')
    entries = [{'origin': origin, 'sha256': _hash(raw),
                'blob': {'path': str(scope/'blobs'/(_hash(raw)+'.blob')), 'sha256': _hash(raw)}}
               for origin, raw in sorted(capture.raw.items())]
    closure_raw = _canonical({'schema_version': 1, 'algorithm_version': 'canonical_v1', 'sources': entries})
    closure = {'path': str(closure_path), 'sha256': _hash(closure_raw)}
    side = _disposition_record(target, evidence, closure, _identity(manifest), decision, view)
    side_raw = _canonical(side)
    side_ref = {'path': str(side_path), 'sha256': _hash(side_raw)}
    event_path = scope/'events'/f"{len(state['events'])+1:010d}.json"
    event_raw = _canonical({'schema_version': 1, 'seq': len(state['events'])+1,
        'genesis': state['genesis_ref'], 'previous_event': state['head'], 'kind': 'disposition',
        'payload': {'target_result': target, 'evidence': evidence, 'sidecar': side_ref}})
    targets = [(closure_path, closure_raw), (side_path, side_raw), (event_path, event_raw)]
    targets += [(scope/'blobs'/(_hash(raw)+'.blob'), raw) for raw in capture.raw.values()]
    # Reject every conflict before the first write, including content-addressed blobs.
    for path, raw in targets:
        _safe_write_path(path, scope if path.is_relative_to(scope) else output.parent)
        if path.exists() and _Inputs().read(path) != raw:
            _fail('E_POLICY_SOURCE', 'disposition_publication_conflict', path)
    _freeze_closure(capture, scope, closure_path, resume=True)
    _publish(side_path, side_raw, output.parent, resume=True)
    _publish(event_path, event_raw, scope)
    return {'sidecar': side_ref, 'view': {**view, 'converged': False}}


def _publish_and_commit(result: Json, markdown: bytes, output: Path, closure: Json,
                        state: Json, reservation: Json, *, checking: bool = False) -> Json:
    """Single-file atomic publications, never a cross-file transaction.

    Preflight every existing target before any write. A missing sibling/commit
    is recoverable only from the same sealed closure and publication metadata.
    """
    scope = Path(state['genesis_ref']['path']).parent
    reserve_path = Path(reservation['path'])
    reserve = _parse(_Inputs().read(reserve_path), reserve_path, 'E_POLICY_SOURCE')
    seq = reserve['seq'] + 1
    event_path = scope / 'events' / f'{seq:010d}.json'
    raw = _canonical(result)
    md_path = output.with_suffix('.md')
    event = {'schema_version': 1, 'seq': seq, 'genesis': state['genesis_ref'],
        'previous_event': reservation, 'kind': 'commit', 'payload': {'reservation': reservation,
            'result': {'path': str(output), 'sha256': _hash(raw)},
            'markdown': {'path': str(md_path), 'sha256': _hash(markdown)}, 'input_closure': closure}}
    canonical = {'path': str(scope / 'blobs' / (_hash(raw) + '.blob')), 'sha256': _hash(raw)}
    display_changed = False
    targets = [(output, raw), (md_path, markdown), (event_path, _canonical(event))]
    for path, wanted in targets:
        if not path.exists():
            if checking:
                _fail('E_RESULT_MISMATCH', 'incomplete_publication', path)
            continue
        actual = _Inputs().read(path, 'E_RESULT_MISMATCH' if checking else 'E_OUTPUT_CONFLICT')
        if path == output and (checking or (event_path.exists() and md_path.exists())):
            display_changed = actual != wanted
            value = _parse(actual, path, 'E_RESULT_MISMATCH')
            if not isinstance(value, dict):
                _fail('E_RESULT_MISMATCH', 'result_object', path)
            actual = _canonical({**value, 'generated_at': result['generated_at']})
        if actual != wanted:
            _fail('E_RESULT_MISMATCH' if checking else 'E_OUTPUT_CONFLICT', 'publication_bytes', path)
    if not checking:
        _freeze_blob(raw, scope)
        for path, wanted in targets:
            if path != output or not display_changed:
                _publish(path, wanted, scope if path == event_path else output.parent, resume=True)
    result_ref = canonical if display_changed else {'path': str(output), 'sha256': _hash(raw)}
    committed_raw = _HistoryGraph(scope).leaf(event['payload']['result'], event_path, published=True)
    if committed_raw != raw:
        _fail('E_POLICY_SOURCE', 'committed_result_projection', output)
    return {'result': result_ref,
            'markdown': {'path': str(md_path), 'sha256': _hash(markdown)},
            'commit': {'path': str(event_path), 'sha256': _hash(_canonical(event))}}


def _collect_final(repo_path: Path, manifest_path: Path, build_record_path: Path,
                   workflow_run_id: str, native_record_path: Path, output: Path,
                   previous_round: Path | None = None, *, check_result: Path | None = None) -> Json:
    """Consume a sealed prepare view, project once for generation and validation.

    check_result never takes a writer lock, creates a directory or accepts a new
    source hash. Live evidence cannot upgrade the already captured audit view.
    Post-publication decisions use a separate frozen sidecar, never base mutation.
    """
    started = time.monotonic_ns()
    repo = Path(repo_path).resolve()
    manifest_path = Path(os.path.abspath(manifest_path))
    build_record_path = Path(os.path.abspath(build_record_path))
    native_record_path = Path(os.path.abspath(native_record_path))
    output = _safe_write_path(Path(os.path.abspath(output)), repo / '.aria' / 'audit-reports')
    checking = check_result is not None
    run = build_record_path.parent
    if build_record_path != run / 'build-record.json' or output.parent != run:
        _fail('E_OUTPUT_CONFLICT', 'final_run_directory', output)
    inputs = _Inputs()
    manifest, build_record = _native_build(repo, manifest_path, build_record_path, inputs)
    if (not run.name.startswith(f"{manifest['checkpoint']}-R{manifest['round']}-") or
            manifest['client_round_id'] not in run.name or
            not output.name.startswith(f"{manifest['checkpoint']}-R{manifest['round']}-") or
            manifest['client_round_id'] not in output.name or
            not output.name.endswith('-' + manifest['change_id'] + '-aggregated.json')):
        _fail('E_OUTPUT_CONFLICT', 'explicit_run_key_required', output)
    if checking and Path(os.path.abspath(check_result)) != output:
        _fail('E_ARGUMENTS', 'check_output_mismatch')
    scope = _safe_write_path(repo / '.aria' / 'audit-reports' / '_executor-ledgers' /
        _hash(_canonical([manifest['checkpoint'], manifest['change_id']])), repo / '.aria' / 'audit-reports')

    def collect() -> Json:
        state = _load_scope(scope, manifest, _Inputs())
        reservation = _required_ref(build_record['reservation'], build_record_path)
        matches = [e for e in state['events'] if e['ref'] == reservation and e['event']['kind'] == 'reserve']
        if len(matches) != 1:
            _fail('E_PREVIOUS_IDENTITY', 'final_exact_reservation')
        entry = matches[0]
        reserve = entry['event']
        before = state['events'][:reserve['seq']-1]
        prefix = {**state, 'events': before, 'head': before[-1]['ref'] if before else None,
                  'pending': None, 'reserve_count': sum(e['event']['kind'] == 'reserve' for e in before)}
        history = _replay_history(prefix)
        if (build_record['prefix_head'] != prefix['head'] or
                reserve['payload']['identity'] != _identity(manifest) or
                reserve['payload']['manifest'] != inputs.reference(manifest_path) or
                manifest['attempt_index'] != prefix['reserve_count']+1 or
                manifest['round'] != history['charged_rounds']+1 or
                reserve['payload']['previous_round'] != history['latest_round'] or
                reserve['payload']['previous_attempt'] != history['latest_attempt']):
            _fail('E_PREVIOUS_IDENTITY', 'final_prefix_binding')
        if manifest['round'] > 1 and previous_round is None:
            _fail('E_PREVIOUS_REQUIRED', 'previous_round_required')
        previous = inputs.reference(Path(os.path.abspath(previous_round))) if previous_round is not None else None
        if (_bound_result_ref(previous, manifest_path, history['latest_round'], scope) !=
                _bound_result_ref(manifest['evidence']['previous_round'], manifest_path, history['latest_round'], scope)):
            _fail('E_PREVIOUS_IDENTITY', 'final_previous_argument')
        after = state['events'][reserve['seq']:]
        if after:
            commit = after[0]['event']
            if (commit['kind'] != 'commit' or commit['payload'].get('reservation') != reservation):
                _fail('E_PREVIOUS_IDENTITY', 'final_adjacent_commit')
            if not checking and len(after) != 1 and not any(
                    e['event']['kind'] == 'disposition' and
                    e['event']['payload'].get('target_result') == commit['payload'].get('result') for e in after[1:]):
                if _path(manifest['evidence']['post_disposition_index_path'], manifest_path).exists():
                    _fail('E_POLICY_SOURCE', 'disposition_not_current_head')
                _fail('E_OUTPUT_CONFLICT', 'not_latest_reservation')
        elif state['head'] != reservation:
            _fail('E_PREVIOUS_IDENTITY', 'final_pending_head')
        for key in EVIDENCE_KEYS:
            if key.endswith('_path'):
                _safe_write_path(_path(manifest['evidence'][key], manifest_path), run)
        disposition_index = _path(manifest['evidence']['post_disposition_index_path'], manifest_path)
        if disposition_index.exists() and not after:
            _fail('E_POLICY_SOURCE', 'disposition_requires_published_base')
        prepare_path = run / 'prepare-record.json'
        prepared_raw = inputs.read(prepare_path)
        prepare = _parse(prepared_raw, prepare_path, 'E_POLICY_SOURCE')
        _validate_round_metadata(prepare, 'prepare', prepare_path,
                                 identity=_identity(manifest), attempt_index=manifest['attempt_index'])
        audit_closure_ref = _required_ref(prepare['input_closure'], prepare_path)
        closure_path, audit_closure_raw = inputs.dereference(audit_closure_ref, prepare_path)
        audit_frozen = _history_closure(audit_closure_ref, prepare_path, scope, raw=audit_closure_raw)
        index_path = _path(manifest['evidence']['post_audit_index_path'], manifest_path)
        index = _parse(audit_frozen.read(index_path), index_path, 'E_NATIVE_EVIDENCE')
        origin = _path(index['native_record']['path'], index_path)
        native_blob = scope / 'blobs' / (index['native_record']['sha256'] + '.blob')
        if native_record_path not in (origin, native_blob):
            _fail('E_RUN_IDENTITY', 'final_native_mapping', native_record_path)
        if _hash(inputs.read(native_record_path, 'E_NATIVE_EVIDENCE')) != index['native_record']['sha256']:
            _fail('E_RUN_IDENTITY', 'sealed_native_changed', native_record_path)
        if index['workflow_run_id'] != workflow_run_id:
            _fail('E_RUN_IDENTITY', 'final_workflow_run_id')
        if native_record_path == origin and inputs.read(index_path, 'E_NATIVE_EVIDENCE') != audit_frozen.read(index_path):
            _fail('E_NATIVE_EVIDENCE', 'sealed_index_changed', index_path)
        capture = _FrozenInputs(dict(audit_frozen.raw))
        capture.raw[str(closure_path)] = audit_closure_raw
        capture.raw[str(prepare_path)] = prepared_raw
        request_ref = _required_ref(prepare['policy_request'], prepare_path)
        expected_request_path = output.with_suffix('.policy-request.json')
        if request_ref['path'] != str(expected_request_path):
            _fail('E_POLICY_SOURCE', 'final_request_output_binding')
        request_path, request_raw = inputs.dereference(request_ref, prepare_path)
        capture.raw[str(request_path)] = request_raw
        request = _parse(request_raw, request_path, 'E_POLICY_SOURCE')
        if prepare['policy_script'] is not None:
            script_path, script_raw = inputs.dereference(prepare['policy_script'], prepare_path)
            if script_path != run / 'policy-workflow.js':
                _fail('E_POLICY_SOURCE', 'final_checker_script_path')
            capture.raw[str(script_path)] = script_raw
        refs = {'manifest': build_record['manifest'], 'build_record': inputs.reference(build_record_path),
            'genesis': build_record['genesis'], 'reservation': reservation,
            'workflow_script': build_record['workflow_script'], 'prefix_head': build_record['prefix_head'],
            'previous_round': reserve['payload']['previous_round'], 'previous_attempt': reserve['payload']['previous_attempt'],
            'native_record': _required_ref(index['native_record'], index_path),
            'config': build_record['sources']['config'], 'defaults': build_record['sources']['defaults'],
            'audit_index': _required_ref(prepare['audit_index'], prepare_path), 'policy_request': request_ref,
            'prepare_record': {'path': str(prepare_path), 'sha256': _hash(prepared_raw)},
            'input_closure': audit_closure_ref, 'drift_index': None}
        # Recompute required from native sources BEFORE using it to acquire drift.
        _, expected_request = _recompute_round(repo, {'inputs': refs}, capture, state['genesis'], history['attempts'],
            carrier=output, observes=before, scope=scope, preparing=True)
        if _canonical(request) != _canonical(expected_request):
            _fail('E_POLICY_SOURCE', 'request_not_recomputed')
        final_closure_path = run / 'final-closure.json'
        publication_path = run / 'publication-record.json'
        if not final_closure_path.exists() and (output.exists() or output.with_suffix('.md').exists() or after):
            _fail('E_POLICY_SOURCE', 'published_result_missing_final_seal', final_closure_path)
        if final_closure_path.exists():
            final_ref = inputs.reference(final_closure_path)
            frozen = _history_closure(final_ref, final_closure_path, scope, raw=inputs.read(final_closure_path))
            for name, raw in capture.raw.items():
                if frozen.read(Path(name)) != raw:
                    _fail('E_OUTPUT_CONFLICT', 'final_input_changed', name)
            # Existing drift/publication bytes are immutable, not new captures.
            publication_raw = inputs.read(publication_path)
            if frozen.read(publication_path) != publication_raw:
                _fail('E_OUTPUT_CONFLICT', 'publication_metadata_changed', publication_path)
            if expected_request['required']:
                drift_path = _path(manifest['evidence']['post_drift_index_path'], manifest_path)
                refs['drift_index'] = {'path': str(drift_path), 'sha256': _hash(frozen.read(drift_path))}
                if inputs.read(drift_path) != frozen.read(drift_path):
                    _fail('E_OUTPUT_CONFLICT', 'sealed_drift_index_changed', drift_path)
            refs['publication_record'] = {'path': str(publication_path), 'sha256': _hash(publication_raw)}
            refs['input_closure'] = final_ref
            _, _, result = _round_from_sources(repo, {'inputs': refs}, frozen, state['genesis'], history['attempts'],
                carrier=output, observes=before, scope=scope)
        else:
            if checking:
                _fail('E_POLICY_SOURCE', 'final_closure_required', final_closure_path)
            # Match final/check/history: verified audit origins stay frozen, while
            # genuinely new checker leaves are read and hash-checked before sealing.
            new_inputs = _CaptureInputs(capture)
            if expected_request['required']:
                drift_path = _path(manifest['evidence']['post_drift_index_path'], manifest_path)
                refs['drift_index'] = new_inputs.reference(drift_path)
                _verify_drift(drift_path, request_ref, run/'policy-workflow.js', inputs=new_inputs)
            for name, raw in new_inputs.raw.items():
                if name in capture.raw and capture.raw[name] != raw:
                    _fail('E_OUTPUT_CONFLICT', 'final_capture_changed', name)
                capture.raw[name] = raw
            # Validate all semantics before writing even publication metadata.
            prior_publication = publication_path.exists()
            publication_raw = inputs.read(publication_path) if prior_publication else _canonical({
                'schema_version': 1, 'identity': _identity(manifest), 'attempt_index': manifest['attempt_index'],
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'host_collect_duration_ms': (time.monotonic_ns()-started)//1000000})
            _validate_round_metadata(_parse(publication_raw, publication_path), 'publication', publication_path,
                                     identity=_identity(manifest), attempt_index=manifest['attempt_index'])
            capture.raw[str(publication_path)] = publication_raw
            refs['publication_record'] = {'path': str(publication_path), 'sha256': _hash(publication_raw)}
            _round_from_sources(repo, {'inputs': refs}, capture, state['genesis'], history['attempts'],
                carrier=output, observes=before, scope=scope)
            if not prior_publication:
                publication = _parse(publication_raw, publication_path)
                publication['host_collect_duration_ms'] = (time.monotonic_ns()-started)//1000000
                publication_raw = _canonical(publication)
                capture.raw[str(publication_path)] = publication_raw
                refs['publication_record']['sha256'] = _hash(publication_raw)
            _publish(publication_path, publication_raw, run, resume=True)
            final_ref = _freeze_closure(capture, scope, final_closure_path, resume=True)
            frozen = _history_closure(final_ref, final_closure_path, scope, raw=inputs.read(final_closure_path))
            refs['input_closure'] = final_ref
            _, _, result = _round_from_sources(repo, {'inputs': refs}, frozen, state['genesis'], history['attempts'],
                carrier=output, observes=before, scope=scope)
        if result is None:
            _fail('E_POLICY_SOURCE', 'final_projection_required')
        # The validator reuses the very same projection used by history and final.
        if checking:
            supplied = _parse(inputs.read(output, 'E_RESULT_MISMATCH'), output, 'E_RESULT_MISMATCH')
            _keys(supplied, RESULT_KEYS, 'E_RESULT_MISMATCH', 'result_keys', output)
            if _canonical({**supplied, 'generated_at': result['generated_at']}) != _canonical(result):
                _fail('E_RESULT_MISMATCH', 'result_projection', output)
            _recompute_round(repo, supplied, frozen, state['genesis'], history['attempts'],
                carrier=output, observes=before, scope=scope)
        policy_ref = state['genesis']['policy_inputs']
        policy_path = _path(policy_ref['path'], Path(state['genesis_ref']['path']))
        policy_input = _parse(frozen.read(policy_path), policy_path, 'E_POLICY_SOURCE')
        context = str(_path(policy_input['context']['path'], policy_path))
        markdown = _render_round(result, context, build_record['effective_config']['resolved_mode']['value'])
        published = _publish_and_commit(result, markdown, output, final_ref, state, reservation, checking=checking)
        if (disposition_index.exists() or output.with_suffix('.disposition.json').exists() or
                any(e['event']['kind'] == 'disposition' for e in state['events'])):
            target = {'path': str(output), 'sha256': _hash(_canonical(result))}
            published.update(_collect_disposition(scope, manifest, output, disposition_index, target, checking=checking))
        if checking:
            after_state = _load_scope(scope, manifest, _Inputs())
            if _canonical(after_state) != _canonical(state):
                _fail('E_SCOPE_BUSY', 'check_head_changed', scope)
        return published

    if checking:
        return collect()
    with _writer_lock(scope):
        return collect()


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        print(_canonical({'error_code': 'E_ARGUMENTS', 'reason': message, 'input_ref': ''}).decode('ascii'), file=sys.stderr)
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(description="Controlled audit executor")
    subparsers = parser.add_subparsers(dest="command", required=True)
    builder = subparsers.add_parser("build")
    builder.add_argument("--repo-path", type=Path, required=True)
    builder.add_argument("--manifest", type=Path, required=True)
    builder.add_argument("--output-dir", type=Path, required=True)
    collector = subparsers.add_parser('collect')
    for name in ('repo-path', 'manifest', 'build-record', 'native-record', 'output'):
        collector.add_argument('--' + name, type=Path, required=True)
    collector.add_argument('--workflow-run-id', required=True)
    collector.add_argument('--previous-round', type=Path)
    modes = collector.add_mutually_exclusive_group()
    modes.add_argument('--prepare-policy', action='store_true')
    modes.add_argument('--check-result', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'collect' and args.check_result is not None:
        if Path(os.path.abspath(args.check_result)) != Path(os.path.abspath(args.output)):
            parser.error('E_ARGUMENTS: check-result must equal output')
    try:
        if args.command == 'build':
            result = build(args.repo_path, args.manifest, args.output_dir)
        elif args.prepare_policy:
            result = _prepare_policy(args.repo_path, args.manifest, args.build_record,
                args.workflow_run_id, args.native_record, args.output, args.previous_round)
        else:
            result = _collect_final(args.repo_path, args.manifest, args.build_record,
                args.workflow_run_id, args.native_record, args.output, args.previous_round,
                check_result=args.check_result)
        print(_canonical(result).decode("ascii"))
        return 0
    except ExecutorError as error:
        print(_canonical({"error_code": error.error_code, "reason": error.reason,
                          "input_ref": error.input_ref}).decode("ascii"), file=sys.stderr)
        return 1
    except OSError:
        print(_canonical({"error_code": "E_CONFIG_SOURCE", "reason": "filesystem_error", "input_ref": ""}).decode("ascii"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
