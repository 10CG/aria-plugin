"""隔离恢复协议工件工厂；不提供恢复算法，不访问私有原生存储。

旧 executor/contract 只从本地已发布 Git 对象读取，且仅在临时项目执行
Python build。Workflow 脚本只作为 bytes 冻结，绝不交给 JS/Workflow 执行。
平台静态来源的小数据替身仅适用于隔离模块的 _RUNTIME_REJECTION_PROFILES
数据边界；不存在 caller bypass flag。所有真实恢复判断均由被测宿主完成。
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ENGINE = Path(__file__).resolve().parents[1]
PLUGIN = ENGINE.parents[1]
EXECUTOR = ENGINE / "scripts" / "audit_executor.py"
OLD_RELEASE = "2d8e223f"
OLD_EXECUTOR_SHA = "5b9a32e23d665e494a21dc002a1a8498db445462762fba52916ce79716333777"
OLD_CONTRACT_SHA = "27e145e159e5b828e2c60d9a743ca8a0ea59bfb11560ce4f1e8783e2ed711920"
FROZEN_SCRIPT_BYTES = 570716
NATIVE_VERSION = "2.1.318"
OPERATOR_ADAPTER = "operator_boundary_20261109_v1"
ACCEPTANCE_ADAPTER = "historical_evidence_acceptance_20261109_v1"


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_ref(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path.read_bytes())}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode(value))
    return file_ref(path)


def load_module(path):
    """加载临时副本，禁止向被测树写入 __pycache__。"""
    spec = importlib.util.spec_from_file_location("recovery_fixture_" + uuid.uuid4().hex, path)
    if spec is None or spec.loader is None:
        raise AssertionError("isolated executor module unavailable")
    module = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
    return module


def local_old_bytes(relative, expected_sha):
    result = subprocess.run(["git", "-C", str(PLUGIN), "show", OLD_RELEASE + ":" + relative],
                            capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError("FIXTURE_BASELINE_UNAVAILABLE: local Git object " + relative)
    if digest(result.stdout) != expected_sha:
        raise AssertionError("FIXTURE_BASELINE_HASH_MISMATCH: " + relative)
    return result.stdout


def tree_snapshot(root):
    """同时保护文件 bytes、目录/文件 mtime 与 mode；不把读引起的 atime 当写。"""
    root = Path(root)
    result = {}
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        result[str(path.relative_to(root))] = (
            info.st_mode, info.st_mtime_ns,
            digest(path.read_bytes()) if path.is_file() else None)
    return result


def _preview(binding, acceptance=False):
    prefix = "仅绑定：" if acceptance else "仅绑定此历史对象："
    text = (prefix + "\nchange_id: " + binding["identity"]["change_id"]
            + "\ncheckpoint: " + binding["identity"]["checkpoint"]
            + "\nreservation sha256:\n" + binding["reservation"]["sha256"]
            + "\nscript sha256:\n" + binding["script"]["sha256"] + "\n\n")
    if acceptance:
        return text + ("这是产品层的证据接受决定，不是补签“历史程序身份已经查明”。\n"
                       "不接受已知运行反证，不跳过任何启用审计，不批准推荐机制 Phase B。")
    return text + ("当前只有首个 reserve，尚未恢复。\n"
                   "操作者声明是有界可信输入，不伪称机器已证明全局无运行。\n"
                   "任何已知冲突仍拒绝；不直接修改旧账本。")


def operator_questions(binding):
    """三选项的已观察封闭布局；仅四个目标值随临时真实工件变化。"""
    return [{"header": "历史恢复边界", "multiSelect": False,
             "question": "对于推进机制原 post_planning 的570716-byte旧准备物，你能否确认它没有被另行授权或转交到其他会话/机器运行，并接受v1采用真实操作者声明支持的本机交互恢复，而不承诺全平台自动派发隔离？",
             "options": [
                 {"label": "确认唯一，采用交互恢复",
                  "description": "我确认该旧准备物由本对话及其明确委派的操作域管理，未另行授权/转交别处执行；接受只有真实操作者声明才能进入历史恢复。仍须完成规范审计、实现测试和发布，原件/预算不改；已知成功或未知运行会否决恢复，声明不覆盖反证。",
                  "preview": _preview(binding)},
                 {"label": "不能确认，保持挂起",
                  "description": "不提供这项事实声明。原预留保持pending，不把未知当未运行，不冒充完整goal已经完成。"},
                 {"label": "仍要求全自动全域证明",
                  "description": "不接受人工声明作为边界；继续要求跨会话/平台的可强制登记与派发栅栏。当前公开Workflow入口没有这一闭合能力，恢复保持阻塞，不再用纸面规则拼凑保证。"}]}]


def acceptance_questions(binding):
    """两选项的独立政策布局；不从 locator 的 policy/selection 生成授权。"""
    return [{"header": "恢复证据边界", "multiSelect": False,
             "question": "对这个已冻结的历史准备物，是否接受“真实原生容量拒绝 + 已取证的本机拒绝路径 + 你已确认的独占授权声明”作为受控恢复依据，明确接受历史执行映像身份未能独立核验的残余不确定，而不再要求补出该历史身份记录？",
             "options": [
                 {"label": "接受此边界，继续恢复",
                  "description": "仅对此旧对象接受上述依据；不声称已证明历史映像相同。已知成功或未知运行反证仍否决，原件/cycle/预算不改；仍须修订规范、完成全部启用审计、实现测试与发布后才实际恢复。",
                  "preview": _preview(binding, acceptance=True)},
                 {"label": "保留门槛，保持阻塞",
                  "description": "不接受这一残余不确定。旧 reserve 继续 pending；本轮目标保持未完成，不通过重建 cycle、追加证书或消耗审计轮数绕过缺口。",
                  "preview": "不新增恢复许可。\n旧准备物及剩余两轮审计预算保持原状。\n继续需要新的可信历史证据；现有记录尚不足以按当前门槛解锁。"}]}]


class RecoveryFixture:
    """拥有独立 HOME/config/repo/plugin 的可复用工厂；创建即有真实旧首 reserve。

    current executor/contract 复制进同一临时逻辑路径；仅在当前仍为旧版时
    附加无行为注释使两个 generation 可区分。compat.to 始终哈希实际副本。
    不改仓内代码、配置、ledger，不依赖 notes 或任何原生私有目录。
    """
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="aria-recovery-protocol-")
        try:
            self.root = Path(self.temporary.name)
            self.home = self.root / "home"
            self.config_root = self.home / ".claude-fixture"
            self.config_root.mkdir(parents=True)
            self.repo = self.root / "repo"
            self.repo.mkdir()
            self.plugin = self.root / "plugin"
            self.engine = self.plugin / "skills" / "audit-engine"
            (self.engine / "scripts").mkdir(parents=True)
            (self.engine / "references").mkdir()
            self.executor = self.engine / "scripts" / "audit_executor.py"
            self.contract = self.engine / "references" / "executor-contract.md"
            self.old_executor = local_old_bytes("skills/audit-engine/scripts/audit_executor.py", OLD_EXECUTOR_SHA)
            self.old_contract = local_old_bytes("skills/audit-engine/references/executor-contract.md", OLD_CONTRACT_SHA)
            self.executor.write_bytes(self.old_executor)
            self.contract.write_bytes(self.old_contract)
            for name in ("convergence-algorithm.md", "report-storage.md"):
                shutil.copyfile(ENGINE / "references" / name, self.engine / "references" / name)
            defaults = self.plugin / "skills" / "config-loader" / "DEFAULTS.json"
            defaults.parent.mkdir(parents=True)
            shutil.copyfile(PLUGIN / "skills" / "config-loader" / "DEFAULTS.json", defaults)
            self.environment = dict(os.environ, HOME=str(self.home),
                                    CLAUDE_CONFIG_DIR=str(self.config_root),
                                    PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1")
            self.roles = ["aria:backend-architect", "aria:qa-engineer", "aria:tech-lead"]
            write_json(self.repo / ".aria" / "config.json", {"audit": {
                "enabled": True, "mode": "convergence", "max_rounds": 5,
                "require_same_admitted_roles": True,
                "checkpoints": {"post_planning": "convergence"},
                "teams": {"post_planning": self.roles}}})
            self._git("init", "-q", str(self.repo))
            self._git("-C", str(self.repo), "-c", "user.name=Protocol Fixture", "-c",
                      "user.email=protocol@example.invalid", "commit", "-q", "--allow-empty", "-m", "fixture")
            head = self._git("-C", str(self.repo), "rev-parse", "HEAD").stdout.decode().strip()
            proposal = self.repo / "openspec" / "changes" / "protocol-fixture" / "proposal.md"
            proposal.parent.mkdir(parents=True)
            proposal.write_text("# Synthetic protocol fixture\n\n验证隔离恢复证据，不运行 Workflow。\n", encoding="utf-8")
            context = self.repo / "context.txt"
            context.write_text("Synthetic isolated recovery context", encoding="utf-8")
            text = proposal.read_bytes()
            policy = self.repo / "policy.json"
            write_json(policy, {"schema_version": 1, "context": file_ref(context),
                "spec_source": file_ref(proposal), "anchor_selection": {
                    "primary_goal": {"source": file_ref(proposal), "start": text.index("验证".encode()),
                                     "end": len(text) - 1}, "in_scope": [], "out_of_scope_hints": []},
                "fallback_sources": [{"kind": "proposal", "locator": str(proposal), "source": file_ref(proposal)}]})
            self.manifest_path = self.repo / "manifest.json"
            self.run_dir = self.repo / ".aria" / "audit-reports" / "post_planning-R1-client-old-protocol-fixture-aggregated"
            self.manifest = {"audit_cycle_id": "cycle-protocol-fixture", "client_round_id": "client-old",
                "checkpoint": "post_planning", "change_id": "protocol-fixture", "round": 1,
                "attempt_index": 1, "candidate_sha": head,
                "roles": [{"role_id": role, "agentType": role, "model_alias": "inherit", "prompt": "Independent review."}
                          for role in self.roles],
                "single_agent_ms": 120000, "round_ms": 300000, "max_parallel": 2,
                "require_same_admitted_roles": True,
                "evidence": {"schema_version": 1, "cycle_origin": None, "previous_round": None,
                    "dispatch_preflight": None, "policy_inputs": file_ref(policy),
                    "post_audit_index_path": str(self.run_dir / "audit-index.json"),
                    "post_drift_index_path": str(self.run_dir / "drift-index.json"),
                    "post_disposition_index_path": str(self.run_dir / "disposition-index.json")}}
            self._construct_exact_old_script()
            self.build_record_path = self.run_dir / "build-record.json"
            self.record = json.loads(self.build_record_path.read_bytes())
            self.script_path = self.run_dir / "workflow.js"
            self.scope = Path(self.record["genesis"]["path"]).parent
            self.binding = {"identity": copy.deepcopy(self.record["identity"]), "attempt_index": 1,
                "genesis": copy.deepcopy(self.record["genesis"]),
                "reservation": copy.deepcopy(self.record["reservation"]),
                "head": copy.deepcopy(self.record["reservation"]),
                "manifest": file_ref(self.manifest_path), "script": file_ref(self.script_path)}
            self.old_sources = copy.deepcopy(self.record["sources"])
            self.old_closure = copy.deepcopy(self.record["input_closure"])
            self.pinned_old_files = {str(p): p.read_bytes() for parent in (self.scope, self.run_dir)
                                     for p in parent.rglob("*") if p.is_file() and not p.name.endswith(".lock")}
            self.pinned_old_files[str(self.manifest_path)] = self.manifest_path.read_bytes()
            self._install_current_generation()
            self._make_static_profile()
            self.session_id = "11111111-2222-4333-8444-555555555555"
            project = "-" + str(self.repo).strip("/").replace("/", "-")
            self.native_path = self.config_root / "projects" / project / (self.session_id + ".jsonl")
            self.native_path.parent.mkdir(parents=True)
            self.operator_index = self.repo / "operator-index.json"
            self.acceptance_index = self.repo / "evidence-acceptance-index.json"
            self.target_path = self.repo / "recovery-target.json"
            # Mirror the actual legacy locator shape, not a newly invented schema.
            # Its descriptive kind/boolean are data, never authority.
            self.target_locator = {
                "kind": "operator_assisted_recovery_product_boundary_pending_owner",
                "identity": copy.deepcopy(self.binding["identity"]),
                "genesis": self.binding["genesis"], "reservation": self.binding["reservation"],
                "current_head": self.binding["head"], "script": self.binding["script"],
                "script_bytes": 570716, "initial_max_rounds": 5,
                "known_workflow_tool_call": "call_fixture_rejection",
                "known_request_uuid": "00000000-0000-4000-8000-000000000001",
                "known_response_uuid": "00000000-0000-4000-8000-000000000002",
                "no_recovery_executed": True}
            write_json(self.target_path, self.target_locator)
            args = {"identity": copy.deepcopy(self.record["identity"]),
                    "manifest_sha256": self.record["manifest"]["sha256"]}
            rejection = self._pair("Workflow", {"scriptPath": str(self.script_path), "args": args},
                                   1, "call_fixture_rejection", error=True)
            self.rows = [*rejection, *self._ask_pair("operator", 3), *self._ask_pair("acceptance", 5)]
            self._serial = 100
            self._base_rows = copy.deepcopy(self.rows)
            self._write_native()
        except BaseException:
            self.temporary.cleanup()
            raise

    def close(self):
        self.temporary.cleanup()

    def _git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.repo, env=self.environment,
                                capture_output=True, check=False)
        if result.returncode:
            raise AssertionError("temporary fixture Git setup failed")
        return result

    def _old_build(self, padding):
        reports = self.repo / ".aria" / "audit-reports"
        if reports.exists():
            shutil.rmtree(reports)
        self.manifest["roles"][0]["prompt"] = "Independent review." + "x" * padding
        write_json(self.manifest_path, self.manifest)
        result = subprocess.run([sys.executable, "-I", str(self.executor), "build",
            "--repo-path", str(self.repo), "--manifest", str(self.manifest_path),
            "--output-dir", str(self.run_dir)], cwd=self.repo, env=self.environment,
            capture_output=True, check=False)
        if result.returncode:
            raise AssertionError("FIXTURE_OLD_BUILD_FAILED: " + result.stdout.decode(errors="replace")
                                 + result.stderr.decode(errors="replace"))
        return (self.run_dir / "workflow.js").stat().st_size

    def _construct_exact_old_script(self):
        """校准合成 prompt 的字节增量；不改生成脚本或已经冻结的任何工件。"""
        base = self._old_build(0)
        unit = self._old_build(1) - base
        if unit <= 0 or (FROZEN_SCRIPT_BYTES - base) % unit:
            raise AssertionError("FIXTURE_PADDING_NOT_REPRESENTABLE: old renderer changed")
        padding = (FROZEN_SCRIPT_BYTES - base) // unit
        if padding < 0 or self._old_build(padding) != 570716:
            raise AssertionError("FIXTURE_OLD_SCRIPT_SIZE_MISMATCH")

    def _install_current_generation(self):
        current_executor = EXECUTOR.read_bytes()
        current_contract = (ENGINE / "references" / "executor-contract.md").read_bytes()
        if digest(current_executor) == OLD_EXECUTOR_SHA:
            current_executor += b"\n# Isolated successor generation; no recovery behavior supplied here.\n"
        if digest(current_contract) == OLD_CONTRACT_SHA:
            current_contract += b"\n<!-- Isolated successor generation, not a recovery implementation. -->\n"
        self.executor.write_bytes(current_executor)
        self.contract.write_bytes(current_contract)
        self.compat_path = self.engine / "references" / "pre-dispatch-recovery-compat.json"
        self.compat = {"schema_version": 1, "compatibility_id": "pre-dispatch-rejection-v1",
            "from": {"executor": OLD_EXECUTOR_SHA, "contract": OLD_CONTRACT_SHA},
            "to": {"executor": digest(current_executor), "contract": digest(current_contract)}}
        write_json(self.compat_path, self.compat)
        self.current_sources = copy.deepcopy(self.old_sources)
        self.current_sources.update(executor=file_ref(self.executor), contract=file_ref(self.contract))

    def _make_static_profile(self):
        """小 bytes 替身，无 ELF、私有窗口或生产可配置例外。"""
        blocks = [b"synthetic capacity read then reject", b"synthetic resolver error propagation",
                  b"synthetic throw before run identity"]
        self.static_windows = []
        offset = 0
        for block in blocks:
            self.static_windows.append({"start": offset, "end": offset + len(block), "sha256": digest(block)})
            offset += len(block)
        binary_sha = digest(b"".join(blocks))
        rows = [{**window, "bytes_hex": block.hex()} for window, block in zip(self.static_windows, blocks)]
        capacity = self.repo / "static-fixture" / "capacity.json"
        loader = self.repo / "static-fixture" / "loader.json"
        write_json(capacity, {"kind": "static_distribution_bytes_not_executed",
                             "binary_sha256": binary_sha, "windows": rows[:1]})
        write_json(loader, {"kind": "static_only_no_private_module_execution",
                           "binary_sha256": binary_sha, "windows": rows[1:]})
        self.runtime_profiles = {"2.1.318": {"binary_sha256": binary_sha,
            "capacity_source": str(capacity), "loader_source": str(loader),
            "windows": copy.deepcopy(self.static_windows)}}

    @staticmethod
    def _uuid(number):
        return "00000000-0000-4000-8000-" + f"{number:012d}"

    def _root(self, kind, number, content, *, parent=None, session=None):
        return {"type": kind, "uuid": self._uuid(number), "parentUuid": parent,
            "sessionId": session or self.session_id, "cwd": str(self.repo), "isSidechain": False,
            "version": NATIVE_VERSION, "timestamp": f"2026-01-01T00:{number // 60:02d}:{number % 60:02d}.000Z",
            "message": {"role": kind, "content": content}}

    def _pair(self, name, input_value, number, tool_id, *, error=False, session=None):
        request = self._root("assistant", number,
            [{"type": "tool_use", "id": tool_id, "name": name, "input": input_value}], session=session)
        error_text = ("<tool_use_error>Workflow script file " + str(self.script_path)
                      + " exceeds 524288 bytes</tool_use_error>")
        response = self._root("user", number + 1,
            [{"type": "tool_result", "tool_use_id": tool_id, "is_error": error,
              "content": error_text if error else "Synthetic tool response"}],
            parent=request["uuid"], session=session)
        response["sourceToolAssistantUUID"] = request["uuid"]
        if error:
            response["toolUseResult"] = ("Error: Workflow script file " + str(self.script_path)
                                         + " exceeds 524288 bytes")
        return request, response

    def _ask_pair(self, kind, number):
        questions = operator_questions(self.binding) if kind == "operator" else acceptance_questions(self.binding)
        request, response = self._pair("AskUserQuestion", {"questions": questions}, number, "call_fixture_" + kind)
        selected = questions[0]["options"][0]
        response["toolUseResult"] = {"questions": copy.deepcopy(questions),
            "answers": {questions[0]["question"]: selected["label"]},
            "annotations": {questions[0]["question"]: {"preview": selected["preview"]}}}
        return request, response

    def _write_native(self):
        self.native_path.write_bytes(b"\n".join(encode(row) for row in self.rows) + b"\n")
        self._refresh_indices()

    def _refresh_indices(self):
        raw_lines = self.native_path.read_bytes().split(b"\n")
        for kind, number, path, adapter in (("operator", 3, self.operator_index, OPERATOR_ADAPTER),
                                           ("acceptance", 5, self.acceptance_index, ACCEPTANCE_ADAPTER)):
            def locator(n):
                index = next(i for i, row in enumerate(self.rows) if row.get("uuid") == self._uuid(n))
                return {"path": str(self.native_path), "line": index + 1, "uuid": self._uuid(n),
                        "line_sha256": digest(raw_lines[index])}
            write_json(path, {"schema_version": 1, "adapter": adapter, "target": file_ref(self.target_path),
                "question": locator(number), "response": locator(number + 1), "tool_use_id": "call_fixture_" + kind})

    def restore_authorities(self):
        self.rows = copy.deepcopy(self._base_rows)
        write_json(self.target_path, self.target_locator)
        self._write_native()

    def _authority(self, kind):
        number = 3 if kind == "operator" else 5
        return (next(row for row in self.rows if row.get("uuid") == self._uuid(number)),
                next(row for row in self.rows if row.get("uuid") == self._uuid(number + 1)))

    def choose(self, kind, option_index):
        _, response = self._authority(kind)
        result = response["toolUseResult"]
        question = result["questions"][0]
        option = question["options"][option_index]
        result["answers"] = {question["question"]: option["label"]}
        result["annotations"] = ({question["question"]: {"preview": option["preview"]}}
                                 if "preview" in option else {})
        self._write_native()

    def rewrite_template(self, kind, *, preview=False):
        """请求、回答、annotations 一起改；负控不靠问答不相等提前触发。"""
        request, response = self._authority(kind)
        questions = request["message"]["content"][0]["input"]["questions"]
        option = questions[0]["options"][0]
        if preview:
            option["preview"] = option["preview"].replace(self.binding["script"]["sha256"], "0" * 64)
        else:
            option["description"] = "Synthetic caller-selected wording: allow known counterevidence."
        question_text = questions[0]["question"]
        response["toolUseResult"] = {"questions": copy.deepcopy(questions),
            "answers": {question_text: option["label"]},
            "annotations": {question_text: {"preview": option["preview"]}}}
        self._write_native()

    def wrong_target(self, kind):
        """只错一项独立 authority 的目标，FileRef 本身仍真实完整。"""
        wrong = copy.deepcopy(self.target_locator)
        wrong["identity"]["change_id"] = "different-synthetic-target"
        other = self.repo / (kind + "-wrong-target.json")
        write_json(other, wrong)
        path = self.operator_index if kind == "operator" else self.acceptance_index
        index = json.loads(path.read_bytes())
        index["target"] = file_ref(other)
        write_json(path, index)

    def api_copy(self, kind):
        """保留同文副本但将其放入 API envelope；非 root 记录不能授权。"""
        request, response = self._authority(kind)
        for row in (request, response):
            inner = copy.deepcopy(row)
            row.clear()
            row.update(type="api-request-blob", uuid=inner["uuid"], data=inner,
                       cwd=str(self.repo), sessionId=self.session_id, isSidechain=False)
        self._write_native()

    def append_unrelated_message(self):
        self._serial += 2
        self.rows.append(self._root("user", self._serial, [{"type": "text", "text": "Unrelated synthetic note"}]))
        self._write_native()

    def append_workflow(self, *, status, related=True, new_root=False):
        """success 或无回执 unknown；无关调用的路径/hash/六字段/cycle 均不同。"""
        if status not in ("success", "unknown"):
            raise ValueError(status)
        self._serial += 2
        identity = copy.deepcopy(self.record["identity"])
        manifest_sha = self.record["manifest"]["sha256"]
        script = str(self.script_path)
        if not related:
            identity.update(audit_cycle_id="unrelated-cycle", client_round_id="unrelated-client",
                            change_id="unrelated-change", checkpoint="post_spec", candidate_sha="e" * 40, round=2)
            manifest_sha = "f" * 64
            script = str(self.repo / "unrelated.js")
        session = "66666666-7777-4888-8999-000000000000" if new_root else self.session_id
        request, response = self._pair("Workflow", {"scriptPath": script,
            "args": {"identity": identity, "manifest_sha256": manifest_sha}},
            self._serial, "call_fixture_extra_" + str(self._serial), session=session)
        response["toolUseResult"] = {"runId": "synthetic-associated-run", "status": "completed"}
        response["message"]["content"][0]["content"] = "Workflow completed: synthetic-associated-run"
        added = [request, response] if status == "success" else [request]
        if new_root:
            path = self.native_path.with_name(session + ".jsonl")
            path.write_bytes(b"\n".join(encode(row) for row in added) + b"\n")
            return path
        self.rows.extend(added)
        self._write_native()
        return self.native_path

    def successor(self, recovery_event, additional_sources=()):
        """只构造普通 attempt2/round1 manifest 与无 authority 布尔的 sources index。"""
        manifest = copy.deepcopy(self.manifest)
        manifest["client_round_id"] = "client-successor"
        manifest["attempt_index"] = 2
        manifest["round"] = 1
        for role in manifest["roles"]:
            role["prompt"] = "Independent successor review."
        run = self.run_dir.with_name("post_planning-R1-client-successor-protocol-fixture-aggregated")
        manifest["evidence"].update(cycle_origin=self.binding["genesis"], previous_round=None, dispatch_preflight=None,
            post_audit_index_path=str(run / "audit-index.json"),
            post_drift_index_path=str(run / "drift-index.json"),
            post_disposition_index_path=str(run / "disposition-index.json"))
        path = self.repo / "successor-manifest.json"
        write_json(path, manifest)
        index = self.repo / "recovery-sources.json"
        write_json(index, {"schema_version": 1, "recovery_event": recovery_event,
                          "additional_sources": sorted({str(Path(p).resolve()) for p in additional_sources})})
        return path, run, index

    def event_paths(self):
        return sorted((self.scope / "events").glob("*.json"))

    def assert_old_unchanged(self, test_case):
        for path, raw in self.pinned_old_files.items():
            test_case.assertEqual(Path(path).read_bytes(), raw, path)
