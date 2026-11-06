# audit-engine Execution Flow & Modes

> 完整执行流程: 入口逻辑 → pre_merge gate → convergence/challenge 模式。从 SKILL.md §执行流程 提取 (iter-2, 2026-05-28)。

## 入口逻辑

导航：[严格配置入口](#严格配置入口) · [受守卫的 Workflow/convergence](#受守卫的-workflowconvergence) · [Capture adapter](#capture-adapter) · [人类处置](#人类处置)。下方原入口与 Convergence/Challenge、散文汇总仅用于 guard=false；true 在独占配方结束后返回，不落入 legacy 临时 persist 或 AI 聚合。Pre-merge gate、每轮 sibling probe 与不可变 anchor 两支共用。

### 严格配置入口

在 config-loader 的任何验证回落/静默返回之前运行此壳。`EXECUTOR` 是**当前插件**的脚本绝对路径，`REPO` 是显式主仓根。它调用当前源码 `_load_fixed_policy`：先分别验证原始 JSON/object/guard boolean 与 DEFAULTS=false 注册，再合并；项目源确实不存在才按缺省处理，读取/解析失败不当 off。非零即停止，不能继续调用通用 loader。该入口不 build、不创建 manifest，不迁移旧报告。

```python
# AUDIT_EXECUTOR_ROUTE_V1_BEGIN
import importlib.util, json, pathlib, sys
sys.dont_write_bytecode = True
executor, repo = map(pathlib.Path, sys.argv[1:3])
spec = importlib.util.spec_from_file_location('audit_executor_route', executor)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
policy = module._load_fixed_policy(repo)
print(json.dumps({'require_same_admitted_roles': policy['require_same_admitted_roles']}))
# AUDIT_EXECUTOR_ROUTE_V1_END
```

把上壳提取到独立临时目录，`python3 -I ROUTE.py "$EXECUTOR" "$REPO"`，捕获 stdout/stderr 并核退出码。仅成功且字段严格为 false 才继续下方原入口（默认团队、旧报告原样）；true 先读以下完整配方。不能凭“已批准 Phase B/想尽快完成”跳启用门；不为了支持 true 另选模型、覆载团队或把 challenge 改成 convergence。即使后文有 file-scope/lane 降级，helper 仍从固定源核模式，不接受 caller 的 mode_ok。

### 受守卫的 Workflow/convergence

以下变量全部是本次明确的绝对路径/真实值，不复制示例历史路径。运行命令均捕获 stdout/stderr、核退出码；任一 helper/capture 非零即停止并呈现 error_code 与输入引用，不回 legacy，不读 MD 推断 PASS。Workflow 工具不可用、显式团队缺失、agents_config/动态换席/model override、固定源不能解析为 convergence 均 unsupported；不要自动换 mode/后端。完整 schema 为 [executor-contract.md](./executor-contract.md) §4、§10；程序宿主是当前 [audit_executor.py](../scripts/audit_executor.py)；[agent-team-audit/SKILL.md](../../agent-team-audit/SKILL.md) 确实存在，提供既有单轮审计指令，不是本次 build/prepare/final/check 的程序宿主。插件 DEFAULTS=false；Aria 本仓 TASK-015 的显式 true 采用已单独验证，见[配置采用证据](../../../../.aria/audit-reports/audit-executor-minimal-repair/config-adoption-evidence.json)。这里不激活配置；各采用项目的有效值仍从原始 JSON 严格解析，不从本段或历史授权猜启用状态。

1. **入口与资源**：保留 pre_merge 专属 completeness gate（非 pre_merge 不运行），先完成原 Step 0 的 anchor 来源选择。每次下一轮、恢复、void 补跑前检查同 cycle 的全部 attempted 审计与 auxiliary_calls，逐项列 runId、native_ref/termination_ref；任一 unknown 则暂停**下一轮（含 void 补跑）的全部新增** Workflow/agent 派发，不凭本轮 PASS、候选 SHA 未变或 `next_round_dispatch_allowed` 单字段放行，不宣称 OS 清理。未派发席不占槽。若已有 pending reservation，先走原 manifest/原 build 路径恢复，不新建 cycle/attempt。稍后取得原件时可 capture 下方 preflight：只用同 run/script/startTime/agentId/label/agentType/q 的较晚观察，不改旧结果 C/raw/票；build 重放全部 prefix 才能解除资源阻断。终态已知不等于能越有效额度、CONVERGED/DRIFT_TERMINATED/OSCILLATION、accept_current/degrade_single。
2. **冻结输入**：VM 外固定 audit_cycle_id，跨轮/会话复用；新物理 attempt 用唯一 client_round_id 与递增 attempt_index，逻辑 round=已计费有效轮+1，void 不加逻辑号。manifest 精确含 identity 六项、attempt_index、roles、120000/300000/2、require_same_admitted_roles=true、evidence。roles 按项目原始 audit.teams[checkpoint] 逐项保持 role_id=agentType=原字符串，model_alias 仅追溯，prompt 冻结完整审计 context、原 dispatch frontmatter 模板与契约 §8 raw JSON 要求（vote/coverage_complete/findings/pending/prior_findings）；不继承旧票。evidence 的 schema_version=1，cycle_origin/previous_round/dispatch_preflight 初始可合法 null；其它为真实 policy_inputs FileRef 与本 run-dir 内未来 post_audit_index_path/post_drift_index_path/post_disposition_index_path 三字符串，禁止未来 hash。后继 cycle_origin 与紧邻有效 previous_round 取已校验链的实际 FileRef，不对展示结果重新拼 hash。policy_inputs 按 §10.2 写真实 context/spec_source、UTF-8 byte spans、fallback_sources；逐项实际读取适用 fallback，不以缺 wrapper 冒充缺锚，后续复用原 genesis anchor。已有 legacy scope 不包装成新 genesis。Aria 本项目的 PR #38 继续暂停、历史不回填；不把此项目边界扩大到其他项目同号 PR。
3. **每轮 sibling probe**：先按本文件下方权威节运行，保留三态 advisory 措辞，未核实不等于无竞品；不删探针以消 hint。运行时再执行 build：

```bash
python3 -I "$EXECUTOR" build --repo-path "$REPO" --manifest "$MANIFEST" --output-dir "$RUN_DIR" >"$BUILD_RECEIPT" 2>"$BUILD_ERROR"
```

4. 读取成功 stdout 的 `build_record/workflow_script/resume_only`（前两项是路径字符串，不是 FileRef），读真实 build-record。`resume_only=true` **不再次 Workflow**，只回收原回执 runId/Transcript入口及原件；回执缺失/活性 unknown 就暂停，不把“找不到回执”当从未启动。仅 `resume_only=false` 且 prefix 资源/政策允许时调用：

```javascript
Workflow({scriptPath: build_receipt.workflow_script,
  args: {identity: build_record.identity, manifest_sha256: build_record.manifest.sha256}})
```

5. 保存实际工具回执并取其**真实 runId**和 Transcript 入口；按显式路径读 Workflow 原件 `/runId /script /args /result /workflowProgress`，不能用 label/scriptPath 当 runId、顶层 status 当逐席完成。用「Capture adapter」audit 模式写 manifest 的 audit locator，然后 prepare：

```bash
python3 -I "$CAPTURE" audit --binding "$BUILD_RECORD" --run-id "$RUN_ID" --native "$LIVE_NATIVE" --transcript-entry "$TRANSCRIPT_ENTRY" --output "$AUDIT_INDEX"
python3 -I "$EXECUTOR" collect --repo-path "$REPO" --manifest "$MANIFEST" --build-record "$BUILD_RECORD" --workflow-run-id "$RUN_ID" --native-record "$LIVE_NATIVE" --output "$ROUND_RESULT" "${PREVIOUS_ARGS[@]}" --prepare-policy >"$PREPARE_RECEIPT" 2>"$PREPARE_ERROR"
```

`PREVIOUS_ARGS=()` 在逻辑 R1（含首次有效轮前 void 重试）；R>1 为 `(--previous-round "$PREVIOUS_RESULT")`，等于 manifest.evidence.previous_round 的实际路径。capture 同样捕获输出/核退出码；可重复传 `--agent-events` **实际 agent JSONL 文件**。prepare 成功仅冻结审计证据；此时不得消费 round-result/宣称发布。读取其 `policy_request/policy_script/prepare_record/audit_index/input_closure/native_record` FileRef，按各原始 carrier/hash 解引用，不把 blob 目录当相对路径 base。

6. **仅 request.required=true**：先核冻结 request 原字节及可用资源槽；这是同一 reservation 的必要辅助检查，不是下一轮。`_resource_summary(for_checker=True)` 按全部已验证调用计算 available_slots，两槽均 unknown 就停，不能伪造 checker 失败或以软超时释放槽；仅剩一槽时不额外并行派其他席。读取 request.anchor 指向的 AnchorRecord.value，调用独立新实例（不复用审计 agentId，不增加投票席）：

```javascript
Workflow({scriptPath: prepare_receipt.policy_script.path,
  args: {identity: request.identity, request_sha256: prepare_receipt.policy_request.sha256,
    anchor: anchor_record.value, conclusions: request.conclusions}})
```

用其独立回执 runId/native/Transcript入口调用 capture drift，`--binding "$PREPARE_RECEIPT"`；输出到 manifest.post_drift_index_path。request.required=false 时不调用 checker、不伪造 drift index。顶层 checker Workflow 在取得 runId 前实际工具错误，才可用 drift_error 模式绑定主会话原始 tool_use/tool_result（--session/--call-uuid/--response-uuid）；未知布局阻断，不能拿缺源当 fail-open。helper 验证请求/脚本/独立身份/原生时间和完整 classifications，失败本身不证明资源释放；无可验证终态的 auxiliary 调用仍为 unknown，不宣称 OS 已退出。
7. **发布与只读重算**：`FROZEN_NATIVE` 必须取 PREPARE_RECEIPT.native_record.path（同字节冻结副本）。首次 final 的 `_CaptureInputs` 重用封存 audit origins，只实读并校验新 checker 来源后冻结 final closure；live audit 增长不回填旧票，新的 checker 缺源/漂移即停。此闭包校验不是任意外部文件的来源认证。以下两次**基础参数完全相同**，不回 live 原件、不换 previous 或 output；check 只多一个 `--check-result`：

```bash
python3 -I "$EXECUTOR" collect --repo-path "$REPO" --manifest "$MANIFEST" --build-record "$BUILD_RECORD" --workflow-run-id "$RUN_ID" --native-record "$FROZEN_NATIVE" --output "$ROUND_RESULT" "${PREVIOUS_ARGS[@]}" >"$FINAL_RECEIPT" 2>"$FINAL_ERROR"
python3 -I "$EXECUTOR" collect --repo-path "$REPO" --manifest "$MANIFEST" --build-record "$BUILD_RECORD" --workflow-run-id "$RUN_ID" --native-record "$FROZEN_NATIVE" --output "$ROUND_RESULT" "${PREVIOUS_ARGS[@]}" --check-result "$ROUND_RESULT" >"$CHECK_RECEIPT" 2>"$CHECK_ERROR"
```

8. **消费后返回（不落入下方 legacy）**：仅 check exit=0 后，逐项核 stdout 的 result/markdown/commit FileRef 及存在时的 sidecar 引用，确认 JSON/MD/commit 齐全、身份相同、commit 为本 reservation 的提交；sidecar 必须由同次 check 合法验证。使用 check 返回的 result FileRef 解引用（展示 generated_at 变化时可指向原 blob），不改成 `hash(ROUND_RESULT)`。只读 JSON 的 configured_roles/dispatched_roles/admitted_roles、population_comparable、conclusion_keys_equal、conclusions_stable、converged 与 policy；canonical_v1 是 helper 唯一权威，不做另一轮 AI 去重/矛盾判定。incomplete 与 convergence/resource gate 正交，不增“全员准入”门。按已校验 policy 保持既有收敛/振荡/耗尽路由、refocus 与 void 计数；unknown 即使存在有效票也仍禁止下次派发。半发布只允许同 reservation/同冻结输入幂等补齐 JSON/MD/commit，不能重派或覆盖不同字节。

### Capture adapter

这是可提取的实际宿主壳，不是新的 AB runner。将下方 `AUDIT_EXECUTOR_CAPTURE_V1_BEGIN/END` 之间的 Python 原文保存到新独立临时目录 `$CAPTURE`，用 `python3 -I` 运行；不要在原件目录运行解释器。不新增插件持久脚本。所有路径须由真实回执 Transcript 入口或主控显式实际文件路径取得；入口不存在/原件不可取得立即阻断并请求提供显式入口，不猜固定 home、顶层 subagents 或平台字段。`--transcript-entry` 只登记已取得入口，不声称它是 native 字段或真实性证明。

- audit：binding=build-record；drift/drift_error：binding=prepare stdout；question/disposition：binding=成功 check stdout。返回引用先核 hash/原始 carrier。audit/drift 的 run-id/native/transcript-entry 各恰一个；preflight 可各重复同等次数，覆盖同 cycle 既往审计及辅助 runs，写独立 observations 文件供下次 manifest.dispatch_preflight 引用。
- `--agent-events` 仅收显式 agent JSONL 原件列表；壳按真实 agentId 映射 workflowProgress 位置，按 LF **字节**算行号，uuid 取原事件。正文完全匹配中断事件才形成 TerminationLink，不从 prompt/assistant 子串造终态。提供错 agent 文件/坏引用直接拒绝，未提供证据保持 unknown；不产生 complete/verified 之类自报布尔。
- 每份输入两次完整读字节相等才取 hash；变动即停。冻结后 live 增长不回填旧视图。index 写入采用不存在则独占创建、相同字节幂等、不同字节拒绝。壳不代替 helper 的 schema/预算/政策验证；输出成功不是报告可消费。

```python
# AUDIT_EXECUTOR_CAPTURE_V1_BEGIN
import argparse, hashlib, json, pathlib, sys

def require(ok):
    if not ok:
        raise ValueError('capture evidence mismatch')

CAPTURED = {}

def stable(path):
    path = pathlib.Path(path).absolute()
    first = path.read_bytes()
    require(first == path.read_bytes())
    require(str(path) not in CAPTURED or CAPTURED[str(path)] == first)
    CAPTURED[str(path)] = first
    return path, first

def parse(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value)
            value[key] = item
        return value
    def invalid(_):
        raise ValueError('nonfinite JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')

def ref(path):
    path, raw = stable(path)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}

def document(path):
    path, raw = stable(path)
    return path, parse(raw)

def dereference(value, carrier):
    require(isinstance(value, dict) and set(value) == {'path', 'sha256'})
    path = pathlib.Path(value['path'])
    if not path.is_absolute():
        path = pathlib.Path(carrier).parent / path
    actual = ref(path)
    require(actual['sha256'] == value['sha256'])
    return document(actual['path'])

def events(path):
    path, raw = stable(path)
    require(raw.endswith(b'\n') and b'\r' not in raw)
    rows = [parse(line) for line in raw[:-1].split(b'\n')]
    require(all(isinstance(row, dict) for row in rows))
    # Keep the hash from these exact LF-delimited bytes, not a later live read.
    file = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
    return rows, file

def event(path, uuid):
    rows, file = events(path)
    matches = [(i, row) for i, row in enumerate(rows, 1) if row.get('uuid') == uuid]
    require(isinstance(uuid, str) and bool(uuid) and len(matches) == 1)
    line, row = matches[0]
    return row, {'file': file, 'line': line, 'event_uuid': row['uuid']}

def native_runs(a):
    require(len(a.native) == len(a.run_id) == len(a.transcript_entry) and bool(a.native))
    runs, ids = [], set()
    for path, run_id, entry in zip(a.native, a.run_id, a.transcript_entry):
        require(pathlib.Path(entry).exists() and isinstance(run_id, str) and bool(run_id))
        origin, native = document(path)
        require(native['runId'] == run_id and run_id not in {r['workflow_run_id'] for r in runs})
        require(native['status'] == 'completed' and isinstance(native['result'], dict))
        nodes = {}
        for i, node in enumerate(native['workflowProgress']):
            if node['type'] == 'workflow_agent':
                agent_id = node['agentId']
                require(isinstance(agent_id, str) and bool(agent_id) and agent_id not in ids)
                ids.add(agent_id)
                nodes[agent_id] = '/workflowProgress/' + str(i)
        require(type(native['agentCount']) is int and native['agentCount'] == len(nodes))
        runs.append({'workflow_run_id': run_id, 'native_record': ref(origin), 'termination_refs': []})
        runs[-1]['_nodes'] = nodes
    for path in a.agent_events:
        rows, file = events(path)
        found = {row['agentId'] for row in rows if 'agentId' in row}
        require(len(found) == 1 and found <= ids)
        agent_id = next(iter(found))
        run = next(r for r in runs if agent_id in r['_nodes'])
        for line, row in enumerate(rows, 1):
            if row.get('type') != 'user' or row.get('message', {}).get('role') != 'user':
                continue
            body = row['message'].get('content')
            if isinstance(body, list):
                if not body or any(not isinstance(b, dict) or b.get('type') != 'text' or not isinstance(b.get('text'), str) for b in body):
                    continue
                body = ''.join(b['text'] for b in body)
            if body not in ('[Request interrupted by user]', '[Request interrupted by user for tool use]'):
                continue
            uuid = row.get('uuid')
            require(row.get('agentId') == agent_id and isinstance(uuid, str) and bool(uuid))
            require(sum(r.get('uuid') == uuid for r in rows) == 1)
            pointer = run['_nodes'][agent_id]
            require(not any(link['native_pointer'] == pointer for link in run['termination_refs']))
            run['termination_refs'].append({'native_pointer': pointer, 'agent_id': agent_id,
                'event': {'file': file, 'line': line, 'agent_id': agent_id, 'event_uuid': uuid}})
    for run in runs:
        del run['_nodes']
    return runs

OPTIONS = [{'label': label, 'action': action} for label, action in [
    ('接受当前结论', 'accept_current'), ('增加轮次', 'increase_rounds'), ('降级为单轮', 'degrade_single')]]

def main():
    p = argparse.ArgumentParser()
    p.add_argument('kind', choices=['audit', 'drift', 'drift_error', 'preflight', 'question', 'disposition'])
    p.add_argument('--binding', required=True)
    p.add_argument('--output', required=True)
    for name in ('native', 'run-id', 'transcript-entry', 'agent-events'):
        p.add_argument('--' + name, action='append', default=[])
    for name in ('session', 'call-uuid', 'response-uuid'):
        p.add_argument('--' + name)
    a = p.parse_args()
    carrier, binding = document(a.binding)
    if a.kind in ('audit', 'drift', 'preflight'):
        runs = native_runs(a)
        if a.kind == 'preflight':
            value = {'schema_version': 1, 'observations': runs}
        else:
            require(len(runs) == 1)
            run = runs[0]
            if a.kind == 'audit':
                value = {'schema_version': 1, 'identity': binding['identity'], 'attempt_index': binding['attempt_index'], **run}
            else:
                request_path, request = dereference(binding['policy_request'], carrier)
                require(request['required'] is True)
                value = {'schema_version': 1, 'identity': request['identity'], 'attempt_index': request['attempt_index'],
                    'request': ref(request_path), 'kind': 'workflow', **run, 'tool_failure': None}
    elif a.kind == 'drift_error':
        require(not a.native and not a.run_id and not a.agent_events)
        request_path, request = dereference(binding['policy_request'], carrier)
        require(request['required'] is True)
        _, call = event(a.session, a.call_uuid)
        _, response = event(a.session, a.response_uuid)
        value = {'schema_version': 1, 'identity': request['identity'], 'attempt_index': request['attempt_index'],
            'request': ref(request_path), 'kind': 'tool_error', 'workflow_run_id': None, 'native_record': None,
            'termination_refs': [], 'tool_failure': {'call': call, 'response': response}}
    else:
        _, result = dereference(binding['result'], carrier)
        policy, identity = result['policy'], result['identity']
        require(policy['terminal_state'] == 'MAX_ROUNDS_EXHAUSTED')
        if a.kind == 'question':
            context = {key: identity[key] for key in ('audit_cycle_id', 'checkpoint', 'change_id')}
            context.update(target_result=binding['result'], used_rounds=policy['charged_rounds'], effective_limit=policy['effective_limit'])
            value = {'questions': [{'question': '本次审计轮次已耗尽，请选择后续路径。\naudit-disposition-context=' + canonical(context).decode('ascii'),
                'header': '审计处置', 'multiSelect': False,
                'options': [{'label': o['label'], 'description': d} for o, d in zip(OPTIONS,
                    ['接受本次未收敛结论并继续，保留未收敛标记', '仅为本周期增加两轮，仍受资源及终局约束', '以最后有效轮为最终结论，保留降级标记'])]}]}
        else:
            _, question = event(a.session, a.call_uuid)
            _, response = event(a.session, a.response_uuid)
            value = {'schema_version': 1, 'target_result': binding['result'], 'question': question, 'response': response, 'options': OPTIONS}
    raw = canonical(value)
    output = pathlib.Path(a.output)
    if output.exists():
        require(stable(output)[1] == raw)
    else:
        with output.open('xb') as f:
            f.write(raw)

if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, StopIteration):
        print('capture blocked: check explicit original input references', file=sys.stderr)
        raise SystemExit(1)
# AUDIT_EXECUTOR_CAPTURE_V1_END
```

### 人类处置

耗尽时先展示最后结论/四元组变化/未收敛原因，再用 capture 的 question 模式从成功 CHECK_RECEIPT 生成实际 AskUserQuestion 输入（`--binding "$CHECK_RECEIPT" --output "$QUESTION_INPUT"`），将其完整 JSON 交给真实 AskUserQuestion。只准一题、multiSelect=false，label 固定三项“接受当前结论”“增加轮次”“降级为单轮”，description 中文；正文含程序生成的唯一 ASCII `audit-disposition-context=` 行，绑定实际 cycle/checkpoint/change、当前耗尽有效 head 的返回 FileRef、charged_rounds/effective_limit。不能手填 approved=true，也不能引用本项目 legacy 接受作新授权。

真实回答后，以主会话显式 `--session` 原件及真实提问 assistant.uuid / 回答 user.uuid 分别作 `--call-uuid/--response-uuid`，capture disposition 到 manifest 的 disposition locator；不要把工具通知或中断当用户选择。再用第7步**相同参数** final/check，helper `_parse_human_disposition` 核 LF行/全文件hash/uuid/sourceToolAssistantUUID/tool_use_id、原input.questions、单选答案及 context，并只发布不可变 sidecar/事件。消费 check 返回的 base+合法 sidecar，不改旧 JSON/MD，不重跑审计；+2仅一次，accept/degrade 均保持 converged=false 并阻止继续派发。问答布局未适配或原件不足即停，不从散文猜授权。

### Legacy 入口 (仅 guard=false)

```
1. 读取配置: config-loader → audit.* 块
   - audit.enabled == false → 静默返回
   - checkpoint 未启用 → 静默返回 ——「是否启用」按本步五档优先级链判定 (first-match, 命中即止;
     与 phase-c-integrator/SKILL.md C.2 pre_hook 步骤 3「按优先级链判定 pre_merge 是否启用」共用
     同一条, 调用方据此判断是否调用 completeness gate 本身):
     - 级 1: 原始 audit.checkpoints (经旧配置兼容映射、未经 config-loader 第 4 步验证、也未与
       DEFAULTS.json 合并的视图, 用于区分「用户显式 off」与「DEFAULTS 填的 off」) 中该 checkpoint
       自身有显式键 → 取其值, 到此为止 (非 "off" → 可能启用, 照常进入; "off" → 静默返回)
     - 级 2a: 否则 (以下读 config-loader 合并视图) audit.mode == "adaptive" → 取 adaptive_rules
       上界 (checkpoints 显式值 > adaptive_rules 推导值 > 默认 off; 入口层不解析被审 change 的
       OpenSpec Level, 故三档中只要有一档非 "off" 即视为可能启用、照常进入该 checkpoint 的执行
       流程, 由 completeness gate 在 §1.4 做精确分格)
     - 级 2b: 否则 audit.mode == "convergence" → 视为启用, 照常进入 (config-example.md 对
       convergence/challenge 逐字是「所有检查点强制使用该模式」)
     - 级 2c: 否则 audit.mode == "challenge" → 同 2b
     - 级 2d: 否则 audit.mode == "manual" → 视为 "off", 静默返回
     - 级 3: 否则 (audit.mode 不属上述四值枚举) → 照常进入, 交由 completeness gate 判
       config_unreadable —— 本层读的是 config-loader 合并视图; 按该表, 验证会对非法值告警并
       回落缺省 (config-loader/SKILL.md §错误处理 未就此场景逐字写明, 属推断), 真正可能撞到
       这一档的是直读原始 config、不经 config-loader 校验的 completeness gate 本身。三个非
       排除 checkpoint 都已显式且纳入集非空时, mode 写错也不会被 completeness gate 暴露 (格
       SC-15.10-typo-mode-lazy-when-inclusion-nonempty 锁住), 不改变其它 checkpoint 的处置

2. 确定模式 (为该 checkpoint 的实际执行选 mode, 此时具体是哪个 change 已明确; 与上方「是否启用」
   共用级 1, 但 2a 不取上界 —— 直接按该 change 的 Level 精确推导 (Level 取不到时例外,
   按下方「Level 取不到时不当 "off"」一条取值), 见上方 Step 1 括注):
   - mode 参数显式指定 → 使用指定值
   - audit.mode == "adaptive" → 按 adaptive_rules 推导
   - checkpoints 显式配置 > adaptive_rules 推导 > 默认 off
   - Level 取不到时不当 "off": 三种来源 —— spec_level_undetermined (Level 解析不出:
     proposal 无 Level 行 / Level 行存在但取不出 1-3 / proposal.md 缺失或不可读) 被
     allow_incomplete_checkpoints 豁免为 bypassed、allow_dangling_change_ids 的
     dangling-skip、其余 Level 解析失败但不短路 —— 一律按档位取值: adaptive 档取
     adaptive_rules 三档的上界 (最严的非 "off" 值, 默认配置 = challenge; 三档全 "off"
     时上界即 "off", 不执行); convergence / challenge 档取档位值本身 (dangling 的
     change_id 不改变本步取值); manual 档取 "off"。依据: 两个宽松开关是放宽检查,
     不是关掉动作 (audit-engine SKILL.md 配置注释「开启后 pre_merge 仍执行」「开启后
     写盘仍执行」); Level 不知道不等于 owner 配了 off (owner 裁定, 2026-10-15)
   - 多 change 归约: 作用域含多个 change 时逐 change 按上述规则 (含上一条 Level 取不到
     的取值) 精确推导后归约 —— 任一 change 非 "off" ⇒ 该 checkpoint 的审计执行, 归约
     模式取各 change 精确结果中最严的非 "off" 值 (严格度序 off < convergence <
     challenge); 全部为 "off" 才不执行。与 Pre-merge 门侧 §1.4 的前置归约 R-1 / R-2
     同口径 (owner 裁定, 2026-10-15)
   - 本步精确推导的结果若为 "off" ⇒ 不执行该 checkpoint 的审计; 对 pre_merge 而言, completeness
     gate 仍照常运行 (不受本步推导结果影响), 其 fail/error 仍按下方 Pre-merge 节 Step 5 阻塞;
     本条只决定门放行之后是否进入 Convergence/Challenge 流程 —— mode 非 off 时放行后进入该
     流程, 精确推导为 off 时放行后 (即便 completeness gate 已判 verdict=pass, 如 Pre-merge 节
     §1.4 的格 D / 格 E) 也不进入: 门的 pass 只确认前置 checkpoint 证据齐全, 不代表 pre_merge
     本身该跑 (两者正交, 见下方 Pre-merge 节 Step 5)
   - 上条括注里的格 E 例子按「Level 取不到时不当 "off"」一条归约 —— adaptive 档取上界、
     convergence / challenge 档取档位值, 归约后通常非 "off"、会进入审计; 仅 manual 档与
     三档全 "off" 的 adaptive 配置归约后仍为 "off"。格 E 的门侧 [INFO] 行文案 (「pre_merge
     取 "off"」) 描述的是门内逐对解析, 不是本步取值

3. 加载 Agent 分组:
   - agents_config 参数 > config.json teams[checkpoint] > 默认分组

4. 执行审计 (按模式分支)
```

## Pre-merge: Checkpoint Report Completeness Gate

> Spec: `openspec/changes/pre-merge-completeness-gate-change-scope/proposal.md` §1–§4
> (主仓)。本文件中 §1.1–§1.4 与 SC-N 均指该文件的对应小节/编号 (不限本节之后 —— 上方「入口
> 逻辑」的两道启用守卫与「确定模式」同样适用); 本节是其**权威可执行版**。
>
> **新增**: 2026-04-23, 修复 Forgejo Issue #26 checkpoint 完整性 gate — 与 Issue #27 (change_id dangling reference gate, 见 [pre-write-validation.md](./pre-write-validation.md)) 互补。
>
> **#26 + #27 互补说明**:
> - **#26 (本节)** = 横向完整性 — 该跑的 checkpoint 都跑了 (completeness)
> - **#27 (写盘前)** = 纵向真实性 — 报告引用的 change_id 都真实存在 (authenticity)
> 两者均在 pre_merge 阶段运行, 错误输出均走 audit trail。完整性门自本 spec 起带 change 维度。

**触发条件**: 仅在 `checkpoint == "pre_merge"` 时执行, 在调用任何 Agent 之前运行。

```
Checkpoint Report Completeness Gate (pre_merge 专属):

  Step 1: 读取配置
    config-loader → audit.checkpoints.*
    config-loader → audit.allow_incomplete_checkpoints (默认 false)
    脚本侧等价实现: 直读 .aria/config.json + 内联缺省与旧配置兼容映射 (config-loader 无程序化入口), 相等性由 SC-21 锁

  Step 2: 豁免检查
    如果 audit.allow_incomplete_checkpoints == true
      → 仍逐对评估三态并全部留痕, 只把 missing / scope_unresolved / spec_level_undetermined / no_spec_unverifiable 降为 verdict=bypassed (exit 0) 并短路终止求值; no_spec_contradicted / change_id_unanchored 不被本键豁免
      → 记录 [WARN] incomplete checkpoint gate bypassed: missing={cp}@{change_id},... ; scope_unresolved={0|1}, 写入 audit trail

  Step 3: 枚举需校验的 checkpoint
    对每个 (checkpoint, change_id) 对, 按 §1.3 五档优先级链 (first-match, 命中即止) 解析
    resolved_mode: 级 1 对原始 audit.checkpoints (经旧配置兼容映射、未经 config-loader 第 4 步
    验证、也未与 DEFAULTS.json 合并的视图) 求该 checkpoint 是否有显式键; 级 2a 起读「原始 + 旧
    配置兼容映射 + 内联缺省」后的合并视图 (completeness gate 自身内联实现, 不经 config-loader
    第 4 步验证 —— 与入口逻辑级 3 读的「经校验」合并视图是两个不同的视图, 见上方 Step 1「脚本侧
    等价实现」) —— mode == "adaptive" 时只在落到本档才去读该 change 的 proposal.md 解析
    OpenSpec Level N (按需/惰性, 不是上方「是否启用」判定取的上界), 取 adaptive_rules.level_N;
    mode == "convergence"/"challenge" 分别取该值; mode == "manual" 取 "off"; mode 不属四值
    枚举 → error_kind=config_unreadable, exit 2 (未经校验的非法值才会真正撞到这一档)。
    allow_dangling_change_ids=true 时: 级 1 (explicit) 不受影响; 该 change_id 锚点缺失 (S1 已知)
    对级 2b/2c/2d/级 3 一律先于其各自分支求值即短路取 resolved_mode="off"、
    enabled_by="dangling-skip" (不再按 mode 正常取值); 落到级 2a (mode == "adaptive") 时, 锚点
    缺失与 Level 解析失败 (按需/惰性解析该 change 的 proposal.md, 非 adaptive 档不解析 Level)
    由同一次 Level 解析调用发现、不做区分, 同样取 resolved_mode="off"、
    enabled_by="dangling-skip"。pre_merge 本身未显式配置时, 该 id 的纳入集因此只剩 explicit
    档非 off 的键, 空纳入集落 §1.4 格 E (pre_merge 本身若显式配置, 按其自身解析结果走, 不受此
    限)。满足以下全部条件则纳入校验:
      - resolved_mode == "on"(字符串)或 resolved_mode 为非 "off" 的模式字符串
      - key != "pre_merge"(排除自身)
      - key != "post_closure"(事后审计, 不做前置依赖)
      - key != "mid_post_spec"(Aria #79: 事件条件触发, 启用但无漂移时合法
        不产出报告 → 不做前置依赖, 否则启用即会误阻 pre_merge)
      - key != "mid_implementation"(audit.mid_implementation 的 threshold=50 为任务进度阈值,
        事件条件触发, 启用但进度未过阈值时合法不产出报告 → 不做前置依赖, 否则启用即会误阻 pre_merge)
      - key != "post_brainstorm"(brainstorm 为 A.0.5 可选阶段, 事件条件触发, 启用但本轮未跑
        brainstorm 时合法不产出报告 → 不做前置依赖, 否则启用即会误阻 pre_merge)

  Step 4: 调用 completeness gate 机械执行器
    python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/audit-engine/scripts/completeness_gate.py" \
      --repo-path "<主仓 root>" --diff-repo-path "<C.2 合并目标仓 root>" \
      --base "<diff 仓主干的远程跟踪 ref>" [--anchor-base "<主仓主干的远程跟踪 ref>"] \
      [--change-id <id> ...] [--no-spec]

    报告归属匹配规则 (§1.2, 全部机械结构事实, 无 AI 价值判断; 令 C = openspec/changes/* ∪
    openspec/archive/* 下去掉 YYYY-MM-DD- 前缀的 id 全集, 不是本轮纳入校验的作用域子集): 文件 f
    归属 (checkpoint, change_id) 当且仅当全部成立 —— f 以 "{checkpoint}-" 开头且以 ".md" 结尾;
    f 含 "-{change_id}-" 或去掉 ".md" 的主干以 "-{change_id}" 结尾 (双侧界定或末段界定, 逐字
    大小写敏感, 不归一化); 且不存在 C 中另一个 id 的匹配子串整体包含本 change_id 匹配子串的碰撞
    (有界包含排除, 对称)。不要求 "-R\d+-" 段, 不解析时间戳与 role。真 2-field 旧 schema 计入
    excluded_legacy_count; 以 "{checkpoint}-" 开头但按上述规则对 C 中任何 id 都不命中的计入
    unattributed_count (文件名进 audit trail); 两个计数不得混计; 子目录内的报告 (只扫顶层,
    scanned_dir_depth=1) 与不以任何 checkpoint 名开头的文件 (如 *-audit-trail.md 族) 三个桶
    都不收 (详见 report-storage.md §向后兼容)。

    per (checkpoint, change_id) 三态判定 (§1.3, 按序 first-match, 迭代口径 = 逐对不是叉乘):
      - present: 上述归属匹配规则命中 ≥ 1 份
      - not_applicable: (a) scope_source=no_spec (--no-spec 且核验通过); 或 (b) checkpoint=
        post_implementation 且 --diff-repo-path 与 --repo-path 的 git toplevel 相同 (同仓;
        跨仓/子模块合并形态下 (b) 通道结构上禁止触发, 一律落 present/missing —— 主仓 diff 的
        路径形态无法代表子模块内的实现工序) 且 diff 非空且全部变更路径都在
        openspec/changes/{作用域内任一 id}/** 或 .aria/audit-reports/** 之下 (Phase A-only); 或 (c)
        checkpoint=post_planning 且该 change 不存在任何 A.2 产物 (无
        tasks.md/detailed-tasks.yaml 且 proposal.md 无 ## Tasks 小节)
      - missing: 其余 (含 diff 为空的情形, 空集不放行)

    stdout 契约 (§1.4): 人读行 ([OK]/[INFO]/[WARN]/ERROR) 一律走 stderr; stdout 恰一个 JSON
    对象 (schema_version "1", gate "completeness_gate"), 顶层键集逐字 16 项 —— schema_version /
    gate / verdict / error_kind / scope_source / change_ids / checked_checkpoints /
    no_prior_checkpoints / results[] / excluded_legacy_count / unattributed_count /
    unattributed / scanned_dir_depth / scan_status / bypassed / elapsed_ms。verdict 四态:
    任一 missing → fail, exit 1; 全部 present/not_applicable → pass, exit 0; 豁免 → bypassed,
    exit 0; 输入/环境错 → error, exit 2。

  Step 5: 校验结果路由
    verdict == "pass" 或 "bypassed" → 门放行 (前置 checkpoint 证据齐全或已豁免); 放行后按上方
      入口逻辑「2. 确定模式」对 pre_merge 本身精确推导: mode 非 "off" → 进入正常 pre_merge 审计
      流程; 按该 change 的 Level 精确推导为 "off" ⇒ 不执行 pre_merge 审计, 门已判 pass (如
      §1.4 格 D / 格 E) 亦同 —— 门放行只代表前置证据齐全, 不代表 pre_merge 本身该跑
      (上句括注里的格 E 例子同样按入口逻辑「Level 取不到时不当 "off"」归约, 通常非 "off"; 调用方 phase-c-integrator 步骤 5 对精确推导为 "off" 的一支按 on_skip 继续合并, 见其 SKILL.md)
    verdict == "fail" 或 "error" → 拒绝执行 pre_merge 审计, 输出 ERROR (见下方), 中止
    消费方 fail-closed 义务: exit≠0 或 stdout 非 JSON 或 schema_version 未知 ⇒ 按 fail 处置 (拒绝执行 pre_merge 审计, 输出 ERROR), 不得按 PASS
```

**三态校验结果输出模板**:

```
ERROR: pre_merge audit 前序 checkpoint 报告缺失: {cp}@{change_id} 配置 "{mode}" 但未找到
  .aria/audit-reports/ 下含 "-{change_id}-" 或以 "-{change_id}.md" 结尾的 {cp} 报告
  (真 legacy 不计入: N; 归属不明: M, 见下方清单)
  [若多对缺失则逐对列出]

Fix 任一:
  1. 补跑缺失 checkpoint 审计 (对应 Phase Skill 重新调用)
  2. 或在 audit.checkpoints 里显式写该 checkpoint
     (adaptive 推导出的 checkpoint 其报告在产出侧调用链上不产出, 重新调用 Phase Skill 会再次早退)
  3. 把该 checkpoint 改为 "off" (若本轮确实不需要)
  4. 临时开 audit.allow_incomplete_checkpoints: true
     (不推荐, 豁免需 audit trail 记录 [WARN]; no_spec_contradicted / change_id_unanchored 不被本键豁免)

unattributed_count > 0 时另起一行 (全局一行, 不按 checkpoint 重复, 与 §1.2 计数表逐字同一句):
  [WARN] unattributed reports (checked={cp1},{cp2},…): N 份 — <按字典序前 20 个文件名>
  [, … 其余 K 份见 stdout 的 `unattributed`]
  (连接符钉死: checked= 后的 checkpoint 名之间、20 个文件名之间, 一律半角逗号 + 一个空格 ", ")

not_applicable (必须 surface, 不得折叠进「校验通过」):
  [INFO] completeness gate: {cp}@{change_id} not_applicable ({reason}); 依据 = <按 reason
  三选一机械事实: diff N 文件全部在 openspec/changes/{id}/ 或 .aria/audit-reports/ 下 (Phase
  A-only) | 无 tasks.md/detailed-tasks.yaml 且 proposal.md 无 ## Tasks 小节 | --no-spec 且
  diff 不触 openspec/changes/>
  (S3 场景 change_id 为 null 时该行渲染为 "{cp} (无 change_id)", 不渲染 "@null")

present (逐行列出, 使「通过」可核对归属):
  [OK] {cp}@{change_id}: N 份
```

**豁免设计原则**: `allow_incomplete_checkpoints` 默认 `false`, 需在 `.aria/config.json` 显式声明才能开启。豁免模式下 pre_merge 审计仍逐对评估三态并全部留痕, 只把 missing / scope_unresolved / spec_level_undetermined / no_spec_unverifiable 降为 bypassed 并短路终止求值 (no_spec_contradicted / change_id_unanchored 不被本键豁免), audit trail 必须记录 `[WARN] incomplete checkpoint gate bypassed: missing={cp}@{change_id},... ; scope_unresolved={0|1}`。

## Convergence 模式

全员讨论 → 汇总引擎 → 结论提取 → 四元组比较 → 收敛/振荡检测。

```
Round N:
  每轮入口: 竞品 spec 探针 —— python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/audit-engine/scripts/sibling_spec_probe.py" --own-spec-dir "<本轨 spec 目录名>" --repo-path "<repo root>"
  读 stdout JSON 的 verdict: sibling_found ⇒ 本轮 🔴 (含 N 份/归档标注) · no_sibling_found ⇒ 「已完整扫描, 未发现同 issue 竞品」 · not_established / exit≠0 / 非 JSON / schema_version 未知 ⇒ 「未能核实」(禁止渲染为无竞品); 不阻断本轮
  1. 调用 agent-team-audit 单轮引擎
     - spawn Agent team (convergence_agents)
     - 各 Agent 独立分析
     - 返回原始 issues 列表

  2. 汇总引擎处理
     - 合并所有 Agent 输出
     - 去重: 基于 {category, scope} (复用 agent-team-audit 算法)
     - 冲突标记: 同 scope 矛盾意见保留双方, 标记 conflicted
     - 结构化提取: 转换为结论记录 (见数据 Schema)

  3. 收敛判定 (详见收敛判定算法)
     - 四元组集合比较: Round N vs Round N-1
     - 振荡检测: Round N vs Round N-2
     - 全票 PASS 检查

  4. 路由:
     收敛 → 计算 verdict → 生成审计报告
     振荡 → 取最后轮结论 → 报告 + 振荡标记
     未收敛 + 有余量 → Round N+1
     未收敛 + max_rounds 耗尽 → 降级策略
```

## Challenge 模式

讨论组提案 → 挑战组质疑 → 全员合并 → objections resolved 判定。

```
Round N (一个完整周期):
  每轮入口: 竞品 spec 探针 —— python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/audit-engine/scripts/sibling_spec_probe.py" --own-spec-dir "<本轨 spec 目录名>" --repo-path "<repo root>"
  读 stdout JSON 的 verdict: sibling_found ⇒ 本轮 🔴 (含 N 份/归档标注) · no_sibling_found ⇒ 「已完整扫描, 未发现同 issue 竞品」 · not_established / exit≠0 / 非 JSON / schema_version 未知 ⇒ 「未能核实」(禁止渲染为无竞品); 不阻断本轮
  Step 1: 讨论组 spawn → discussion_output
     - proposal (统一提案文本)
     - decisions [{severity, category, scope, summary}]
     - rationale [string]

  Step 2: 挑战组 spawn (输入: discussion_output) → challenge_output
     - objections [{agent, target_decision, severity, point, status: "new"}]

  Step 3: 全员讨论 (输入: discussion_output + challenge_output) → 修正 proposal

  Step 4: 挑战组再审 (输入: 修正 proposal) → 更新 objections status
     - status: new → resolved | overruled

  Step 5: Drift Check (详见 challenge-mode-schema.md)
     - drift-checker 按 anchor 对 decisions ∪ objections 分类 → drift_ratio → 三档处置 (#17)

  收敛判定:
     - 提案结论四元组集合无变化 (vs Round N-1)
     - AND objections 全部 status=resolved (无 unresolved)
     - 满足 → 生成审计报告
     - 不满足 → Round N+1 或降级策略
```

**Round 计数**: 一个 Round = 讨论组提案 + 挑战组质疑的完整周期。全员合并讨论属于下一 Round 的开头。max_rounds=5 意味着最多 5 个完整周期。

详细 Schema 见 [challenge-mode-schema.md](./challenge-mode-schema.md)。

## 竞品 spec 探针 (per-round 入口)

> Spec: `openspec/changes/sibling-spec-probe/proposal.md` §3–§10 (主仓)。本节是探针 **stdout 契约 + exit code + 消费措辞的权威可执行版**; SKILL.md 「per-round 入口探针」小节只放概述与指针。上方 Convergence / Challenge 两个围栏块内各有一条同字面的两行调用串 (机械护栏 SC-17 计数恰 2), 本节**不**复用那个前缀。

**为什么每轮跑, 为什么两个模式块都改**: 探针看的是远端仓里已落盘的 proposal 语料 (`openspec/changes/*/proposal.md` + `openspec/archive/*/proposal.md`, 全部 `refs/heads/*`), 与 claim 通道没有共享失效模式 —— 对方没走认领、或已 ship 归档时, 只有语料通道还能把「这件事别人做完了」摆到台面上 (Spec §Why 第 5 次事故)。审计跨天时首轮结论会陈旧, 所以每轮入口重跑 (不复用 `remote_refresh` 缓存, P3)。`config-loader/DEFAULTS.json` 的 `adaptive_rules.level_3 = "challenge"` 让下游 Level-3 审计走 Challenge 块, 只 patch Convergence 会让那些项目静默漏掉探针。它与 Step 0 (Anchor 固化, Round 1 启动前一次性) 是两回事, 不沿用 Step 编号。

**调用** (每轮入口, Round 1 含):

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/audit-engine/scripts/sibling_spec_probe.py" \
  --own-spec-dir "<本轨 spec 目录名>" --repo-path "<repo root>"
```

- `--own-spec-dir` = 本轨 `openspec/changes/<目录名>` 的目录名 (自命中排除键); `--repo-path` = 仓库根 (探针不假定 cwd)。
- 探针自带 fetch (`--no-tags --prune`, 写进私有命名空间 `refs/aria/sibling-probe/<remote>/<branch>`, 不动 `refs/remotes/*`), 每个 git 子进程 30s, fetch 腿最多 2 次; 双远端一轮约 25s (Spec §5), 这是本探针的成本, 不称轻量。

**stdout — 恰一个 JSON 对象 (schema_version "1")**:

| 字段 | 类型 | 语义 |
|---|---|---|
| `schema_version` | str | 固定 `"1"`; 未知值 ⇒ 按「未能核实」处置 |
| `probe` | str | 固定 `"sibling_spec_probe"` |
| `status` | str | 运行面 (覆盖是否完整): `ok` \| `degraded` \| `skipped` |
| `reason` | str \| null | `status != "ok"` **或** `verdict == "not_established"` 时必非空: `no_enforced_remote` \| `remote_unresolved` \| `fetch_failed` \| `cap_applied` \| `own_token_absent` |
| `verdict` | str | 判定面 (一等字段): `sibling_found` \| `no_sibling_found` \| `not_established` |
| `own_spec_dir` | str | 本轨 spec 目录名 |
| `own_layer` | str | 本轨 proposal 走的层: `canonical` \| `none_sentinel` \| `url_fallback` \| `no_token_no_url` \| `no_field` \| `bad_token_union` |
| `own_keys` | list | 本轨比较键, 每项 `["k", <repo basename>, <n>]` 或 `["r", <原串>]` |
| `remotes` | list[obj] | 每 remote: `name` / `default_branch` (str\|null, 只认 `ls-remote --symref`, 不猜) / `resolved_by` (`ls_remote_symref`\|null) / `error_kind` (str\|null) / `scanned` / `capped` / `refs_scanned` / `stale_skipped` |
| `hits` | list[obj] | **恒为 list**; 每项 `remote` / `branch` / `corpus` (`changes`\|`archive`) / `spec_dir` / `path` / `field_line` / `key` / `layer` / `refs` (`<remote>/<branch>` 全部命中处, 字节序) |
| `caps_applied` | list[obj] | 每项 `remote` / `kind` (`proposals`\|`refs`) / `total` / `kept` / `dropped_from` |
| `elapsed_ms` | int | 探针总耗时 |

`error_kind` 封闭集合: `network` / `auth_403` / `non_ff` / `git_missing` / `other` (形态照 `phase-d-closer/scripts/fetch_gate.py::_classify_error`) + `timeout` / `no_symref` / `bad_symref_prefix`; git 原始 stderr 永不回显 (Rule #7)。

**`verdict` 取值表** (消费方**不得**从 `hits == []` 推断结论 —— 「扫完没有」与「没扫到 / 本轨无输入」在 `hits` 上取值相同):

| `verdict` | 何时 |
|---|---|
| `sibling_found` | `hits` 非空 (即使 `status == "degraded"`: 正证据不因覆盖不完整而降级, 此时 `reason` 说明缺口) |
| `no_sibling_found` | `hits` 为空 **且** 覆盖完整 (全部 enforced remote 解析出默认分支、fetch 成功、全部 `refs/heads/*` 已枚举、无任何 cap) **且** `own_keys` 非空 |
| `not_established` | 其余: `own_keys` 为空 (本轨无可比较输入, 典型: 字段值为哨兵 `none` / `无`, 或无字段) / 任一 remote 未解析或 fetch 失败 / 任一 cap / enforced 集合为空 |

**exit code**: `0` = 探针完成了一次有定义的判定 (命中与不命中都是 0; `degraded` / `skipped` 也是 0); 非 `0` = 仅探针自身失败 (参数错 / 内部异常 / 仓库不可读), 此时 stdout 不保证是 JSON。

**消费措辞 (三档, 不得合并)** —— 写进当轮 `### Round N` 记录 (模板见 [report-format.md](./report-format.md)) 并进聚合报告; N = 去重后的 `spec_dir` 数 (同一 Spec 在 origin/github 两镜像各成一条 `hits[]` 项, 计数须去重):

| `verdict` | 措辞 |
|---|---|
| `sibling_found` | 「🔴 检测到 N 份同 issue 的竞品 Spec: <spec_dir 列表>」; 命中项 `corpus == "archive"` 时标注**「已完成的 Spec」**; `status == "degraded"` 时追加「(覆盖不完整: <reason>)」 |
| `no_sibling_found` | 「本轮已完整扫描, 未发现同 issue 竞品」 |
| `not_established` | 「**未能核实** —— 本轮竞品扫描未取到完整证据 (原因: <reason>)」; **禁止**渲染为「无竞品」 |

**消费方 fail-closed 义务**: `exit != 0` **或** stdout 无法解析为 JSON **或** `schema_version` 未知 ⇒ 一律按 `not_established` 处置 (渲染「未能核实」)。

**不阻断**: 探针是 advisory 副机制 —— 不改 verdict 计算、不改收敛判定、不改轮次路由; 「同 issue」≠「重复劳动」(Spec §Why 的 `#137` 簇是有意拆分), 命中是告警不是判决, 由人一眼可辨。
