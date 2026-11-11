# Workflow 审计执行器契约

> 归属：`audit-executor-minimal-repair`，派发前容量拒绝扩展见§13（`audit-executor-pre-dispatch-recovery`）。接口宿主为 [audit_executor.py](../scripts/audit_executor.py)，本文描述其当前 build/prepare/final/check 与受限恢复的程序事实，不新增 AI 编排选择或恢复流程。
> 文档同步与离线测试不代表完整验收、真实产品调用、正式 Rule #6 AB 或 ship；这些证据分别核验，不沿用旧审计绿灯。
> 本文件不激活配置、不改历史报告，不授权取消、预算扩充或后端替换。Aria 本项目的 PR #38 继续暂停，旧报告不回填、不追加轮次；不是冻结其他项目的同号 PR。

## 1. 依据与证据等级

规范依据：已批准 [proposal.md](../../../../openspec/changes/audit-executor-minimal-repair/proposal.md) What §2–6、SC-1/5/6/7/8，以及 [detailed-tasks.yaml](../../../../openspec/changes/audit-executor-minimal-repair/detailed-tasks.yaml) `metadata.contracts`、TASK-002。

事实入口：[sources.json](../../../../.aria/notes/2026-11-01-pr38-audit-execution-diagnosis/sources.json)。按其 `files[].path` 定位真实原件，再核对 `bytes/sha256`，不能把诊断 prose 当原件。以下四份 Workflow 原件已逐字段核对；其内嵌 `/script` 分别与诊断 `sources/workflow-R{N}-script.txt` 同字节。

| 轮次 | 原生 `runId` | 原件 SHA-256 |
|---|---|---|
| R2 | `wf_2fa7b294-c83` | `0c5f426394ceeb03c1adb8a65bec385ee058bb9af48062aed6a9c953c19a47c4` |
| R3 | `wf_b21b0b9d-34d` | `aee2217f6738f450a87ed6c77408b98a9ff9a1077dcd53acb4431fc405af83b9` |
| R4 | `wf_06cc4f5a-7ab` | `70f9b5b717549a58212c5183b841502755f83c6f86c08bdc9b3ed32759971b05` |
| R5 | `wf_41648bf4-e9b` | `2e976c4f243328bdd485c4289c90d99c95463d16dfd179b8118048ea027724a4` |

真实原件有 `workflowProgress`，**没有顶层 `agents` 数组、逐席 `completedAt` 或独立 `complete=true` 标记**。顶层 `status="completed"` 不等于每席完成；这些原件仍有 `state="start"/"progress"` 的节点。不得发明缺失字段。

公开 Workflow 表面支持 `Workflow({scriptPath, args})`，回执有 runId / Transcript dir 元数据；脚本内使用 `agent(prompt, {agentType,label,phase})`、`log`、`phase`、Promise 及已实际运行的 `setTimeout/clearTimeout`。主控基础工作流 `wf_66b9c96d-5c1` 已运行，但不等于新执行器的 SC-1 探针已通过；子席检索不到 schema 不否定父会话工具。原生 JSON 字段仍以真实 workflowProgress 为准，不把回执目录元数据写成原生字段；没有单席取消、原生启动回调或时钟对齐能力的证据。

其余 SOT：

- [SKILL.md](../SKILL.md) §数据 Schema、汇总引擎、降级策略、错误处理、并发控制。
- [convergence-algorithm.md](./convergence-algorithm.md) §四元组集合比较、Refocus 轮语义、完整判定流程。
- [report-storage.md](./report-storage.md) §Verdict 计算、报告 Frontmatter。
- [challenge-mode-schema.md](./challenge-mode-schema.md) §drift-checker（仅引用已有 drift 政策，不扩充本后端为 challenge）。
- [workflow-R5-script.txt](../../../../.aria/notes/2026-11-01-pr38-audit-execution-diagnosis/sources/workflow-R5-script.txt) 第17–28行是已执行的 raw parser 文本依据；它不是新 helper。
- `sources/persist_pr38_round.py.txt` 第25–28、59–73行仅证明历史聚合方式；其中手写的 drift boolean、固定 max_rounds、旧 scope 归一化不能提升为新生产函数或可信政策输入。

## 2. 通用类型与验证顺序

下文“必需”表示键必须存在；“nullable”表示允许显式 JSON `null`，不允许用缺键、0、空数组代替未知。JSON integer 必须排除 boolean；JSON boolean 只能是 `true/false`。拒绝重复 JSON object key、非法 JSON 和非有限数字，不进行 truthy、字符串转数字或自动补别名。

| 类型 | 定义 |
|---|---|
| `Id` | 非空字符串；cycle/round id 由 VM 外宿主产生，不能用 VM 时钟或随机 API 产生 |
| `Hash` | 原文件字节的 SHA-256，64位小写 hex；不是解析后重排 JSON 的 hash |
| `FileRef` | `{path: string, sha256: Hash}`，两键必需、不 nullable；相对路径以承载该引用的文件所在目录为基准。宿主显式传入的外部证据路径可为绝对路径；portable fixture 必须改用自身相对引用，不依赖诊断机器路径 |
| `NativeRef` | `{file: FileRef, pointer: string}`；pointer 为确切 JSON Pointer，指到本次 run 的原始字段/节点 |
| `JsonlRef` | `{file: FileRef, line: integer>=1, agent_id: Id, event_uuid: Id}`；定位一条完整 JSONL 事件，必须核对该行 agentId/uuid/内容 |
| `Key` | `[type, severity, category, scope]` 四个字符串，顺序固定；比较用完整 tuple，不用8位短 hash 代替相等判断 |
| `RoleSet` | 唯一 role_id 的数组；序列化按 manifest 顺序，集合比较与顺序无关；重复 id 是错误，不静默去重坏输入 |

验证顺序：CLI/JSON schema → 固定配置与来源 hash → cycle/round/run/script 身份 → 原生记录与快照映射、时间一致性 → 六态 first-match → raw parser → 实际参与集合 → 既有结论/policy 重算 → 输出/只读比较。前层错误不降级成后层的空集合或 `false`。

内容 hash 仅证明本次使用的字节及检测漂移，不证明外部文件真实来源或阻止工具外人工伪造。不得把可手填的 `verified=true` 当成证据。

## 3. CLI 与生产路由

当前 CLI（参数对应 `main` 的 argparse 定义；路径和大写参数是可移植占位，不是要写入结果的值）。普通 capture、Workflow 调用和 stdout 解引用按 [execution-modes.md](./execution-modes.md)「受守卫的 Workflow/convergence」执行；下列新增入口不表示旧 Skill 已自动调用它：

```bash
python3 -I aria/skills/audit-engine/scripts/audit_executor.py build \
  --repo-path REPO --manifest MANIFEST --output-dir RUN_DIR

# 仅§13首次后继的新 build 必需 recovery-sources；不是普通 native preflight
python3 -I aria/skills/audit-engine/scripts/audit_executor.py build \
  --repo-path REPO --manifest SUCCESSOR_MANIFEST --output-dir SUCCESSOR_RUN_DIR \
  --recovery-sources RECOVERY_SOURCES_INDEX

python3 -I aria/skills/audit-engine/scripts/audit_executor.py recover-dispatch-rejection \
  --repo-path REPO --manifest OLD_MANIFEST --build-record OLD_BUILD_RECORD \
  --native-record NATIVE_ROOT_JSONL --tool-use-id TOOL_USE_ID \
  --operator-index OPERATOR_INDEX --evidence-acceptance-index ACCEPTANCE_INDEX \
  --check-only

python3 -I aria/skills/audit-engine/scripts/audit_executor.py collect \
  --repo-path REPO --manifest MANIFEST --build-record BUILD_RECORD \
  --workflow-run-id RUN_ID --native-record LIVE_NATIVE \
  --previous-round PREVIOUS_RESULT --output ROUND_RESULT --prepare-policy

python3 -I aria/skills/audit-engine/scripts/audit_executor.py collect \
  --repo-path REPO --manifest MANIFEST --build-record BUILD_RECORD \
  --workflow-run-id RUN_ID --native-record FROZEN_NATIVE \
  --previous-round PREVIOUS_RESULT --output ROUND_RESULT

python3 -I aria/skills/audit-engine/scripts/audit_executor.py collect \
  --repo-path REPO --manifest MANIFEST --build-record BUILD_RECORD \
  --workflow-run-id RUN_ID --native-record FROZEN_NATIVE \
  --previous-round PREVIOUS_RESULT --output ROUND_RESULT \
  --check-result ROUND_RESULT
```

- `recover-dispatch-rejection` 的上述七个取值参数均必需；`--check-only` 是可选只读 flag，省略时进入 mutation；另有可重复的 `--additional-source PATH`（默认空数组）。它不接受 `--workflow-run-id`、`--output`、caller catalog 或新预算。`build --recovery-sources PATH` 是可选参数，仅在§13.8的实际首续接状态变为必需；不是所有 build 的新前置。恢复输出与幂等边界见§13.1/13.7。
- 显式准备调用使用 `collect --prepare-policy`，在真实审计 Workflow 和 audit capture 后执行。与 `--check-result` 互斥；成功仅封存审计证据并产出同 output stem 的 `.policy-request.json`、必要时的 `policy-workflow.js` 及准备证据，不发布 round-result JSON/MD、不提交成功轮、不表示审计通过。缺独立 drift 证据的最终 collect 报 `E_POLICY_SOURCE`，不以错误回执暗藏准备协议。
- `--previous-round` 指紧邻前一**有效**轮；逻辑 round=1（含首次有效轮之前的 void 重试）省略，round>1 必传，且与 manifest.evidence.previous_round 的实际文件/hash 相符。void 尝试另由固定账本验证，不能省略历史。
- `--repo-path` 必传，不取 cwd；输入是实际文件，不猜会话目录。`--workflow-run-id` 取真实回执并等于原件 `/runId`。准备时可读取显式 live 原件；封存后最终 collect/check 的 `--native-record` 使用准备包内同字节的冻结副本；最终与 check 的所有参数一致。
- `build` 产出 `workflow.js`、`build-record.json`，并按§10维护固定 scope genesis、冻结输入和 reservation；不调用 Workflow。编排层执行 `Workflow({scriptPath: <生成文件>, args: <冻结身份>})`；VM 不读本地文件。
- 首次 final 通过 `_CaptureInputs` 优先重用 prepare 封存的 audit origins；只对新的 checker index/native/JSONL 等来源实读并核 hash，再冻结 final closure。live audit 增长不补旧 C/raw/票；新 checker 缺源或不符即停，不宣称能认证任意外部文件。
- 最终 `collect` 发布 JSON/同 stem MD 与账本 commit；后发生的真实用户处置仅按§10.5另发不可变 sidecar，不改旧报告。`check-result` 不写文件、锁、快照或账本，只重算。仅忽略纯展示生成时间与本次检查自身耗时，不忽略 policy、时间、集合、hash、身份或 boolean。
- `RUN_DIR/ROUND_RESULT` 必须是项目 `.aria/audit-reports/` 中本次明确 run-key。沿用 `{checkpoint}-R{round}-{run-key}-{change_id}-aggregated` 命名形状；run-key 包含 `client_round_id`，不能指向 Aria 本项目 PR #38 旧文件或用共享脚本路径覆盖上一轮证据。
- 验证全部成功后才原子发布单个文件；已有结果不覆盖。JSON/MD 无跨文件事务：两者齐全、对应账本 commit 已存在且 check 通过后才可消费。仅允许§10.3同 reservation、同输入、已有字节完全相同的窄恢复补齐缺文件/commit；不同字节一律冲突，不能以恢复为名重派。
- 当前退出语义：0=成功或只读完全相符；2=CLI 参数错误（`E_ARGUMENTS`）；1=执行器拒绝或文件系统错误（§11）。审计 `REVISE/FAIL`、不可比或未收敛是有效计算结果，不等于 collector 进程错误。错误至少报告 `error_code` 与输入引用，不输出 secret 或整份 prompt。

生产分支必须在任何新 `build` 前选择：

1. 固定配置严格解析，原始守卫键若存在且不是 boolean，直接配置错误。
2. 有效 `audit.require_same_admitted_roles=false`：**整个 legacy 编排、算法、报告消费路径保持原样**，不要求旧报告补字段、不强迫改走 helper。测试纯比较函数的关闭向量不等于生产接入新执行器。
3. 为 true：只接受 Workflow/convergence 和项目 checkpoint 的显式团队；必须走 `build → 真实审计 Workflow(scriptPath,args) → capture audit → collect --prepare-policy → required 时独立 checker Workflow/capture → frozen final collect → 同基础输入 check-result → 已验证 JSON/MD/commit 与合法 sidecar 消费`。人工团队覆盖、`agents_config`、动态加人、manifest model override、无法解析成 convergence 的模式或其他后端均报 unsupported，不退回 legacy。

有效模式、轮数和 drift 不能由 caller 声明一个“已经检查”的 boolean；来源约束见§4/10。插件 DEFAULTS 为 false；Aria 本仓已由 TASK-015 单独验证显式 true 采用及模板同步，见[配置采用证据](../../../../.aria/audit-reports/audit-executor-minimal-repair/config-adoption-evidence.json)。本文不激活配置，实际分流始终取当前项目原始 JSON 的严格解析值，不从文档或历史授权推定启用状态。

## 4. manifest 与固定配置

### 4.1 manifest 必需字段

除标明 nullable 外全部不 nullable。不得接受同义字段替代 canonical token。

| 字段 | 类型 | 输入来源及拒绝条件 |
|---|---|---|
| `audit_cycle_id` | `Id` | VM 外创建并跨轮/会话续用的原周期身份；不得为不可比、全失败、恢复会话或耗尽轮数换 id |
| `client_round_id` | `Id` | 本次物理执行唯一身份；不得与其他轮复用 |
| `checkpoint` | string | 已有 checkpoint 注册名；与固定配置对应 |
| `change_id` | string | 本次被审变更身份；不得从别的 change/PR 借参与证据 |
| `round` | integer>=1 | 有效逻辑轮号，等于此前非 void 已提交轮数+1；void 后重试沿用此号，不是物理尝试数 |
| `attempt_index` | integer>=1 | 固定 scope 内 reserve 次数+1，含 void 单调递增；client_round_id 每次唯一 |
| `evidence` | object | §10.2规定的运行前引用与运行后 locator；不得把未来 hash/runId 填成已冻结输入 |
| `candidate_sha` | string | 被审候选的完整 Git object id；冻结并逐层原样追溯，不以候选相等作新可比性门 |
| `roles` | 非空 array<object> | 项目原始 `audit.teams[checkpoint]` 显式数组逐项映射；顺序与长度完全一致，同轮唯一 |
| `roles[].role_id` | string | 项目显式团队项中的完整注册名，不补 `aria:`、不去前缀、不取显示别名 |
| `roles[].agentType` | string | 必须与该项 `role_id` 及显式团队字符串相等；交给公开 agentType 选项 |
| `roles[].model_alias` | 非空 string | 配置别名或 `inherit`，仅追溯；不传给 `agent(...,{model:...})`，不假称原生实际模型 |
| `roles[].prompt` | string | VM 外冻结的完整 prompt，按 JSON 编码注入；不得在 VM 中拼接外部未冻结文件、改审计范围 |
| `single_agent_ms` | integer | 必须等于120000 |
| `round_ms` | integer | 必须等于300000 |
| `max_parallel` | integer | 必须等于2，不因通用 hard_cap=3 而增大 |
| `require_same_admitted_roles` | boolean | **期望值**，逐值等于固定源解析出的有效值；不具有覆盖权 |

`roles[].model`、`agents_config` 等覆盖请求必须拒绝，不以忽略字段掩盖“用户想覆载但实际没做”。prompt 中任意字符串均作为数据编码，不拼接成可执行代码。

### 4.2 配置身份与强校验

- 项目源固定为 `REPO/.aria/config.json`；DEFAULTS 固定为**运行中的本插件** `skills/config-loader/DEFAULTS.json`，通过 executor 文件自身位置定位，不取 cwd、manifest 指定路径或另一个已安装插件版本。
- 两份源先各自校验 JSON/object 结构与原始守卫类型，再合并有效配置。键缺省时目标 DEFAULTS 为 false；若 DEFAULTS 本身类型错误或未完成键注册，不能在已宣称接入的新路径中悄悄当作成功配置。生产 legacy 缺省 false 的兼容行为独立保留。
- true 时项目配置必须有 checkpoint 的显式 string 数组；从 DEFAULTS 补出团队不满足此前提。空项、重复项、非字符串或 manifest 任一删人/加人/换序/改名均拒绝。
- `audit.enabled`、`audit.mode`、`audit.checkpoints[checkpoint]`、`audit.adaptive_rules`、`audit.max_rounds`、`audit.drift_guard` 与既有 convergence criteria 全部来自同两份文件的有效配置。adaptive 所需 spec level 若没有可核验源，则不能用 manifest 手填 mode 绕过，报 `E_POLICY_SOURCE`/unsupported。
- `build-record` 保存两份**完整文件字节 hash**及有效字段的值/JSON Pointer 来源；`collect/check-result` 重读同一路径，任一字节漂移即拒绝，不仅比较 guard 一个键。插件代码/契约来源变化亦拒绝用旧 build-record 混跑。

## 5. build-record、脚本与返回快照

本节字段为当前宿主生成/验证的 schema，不声称旧 R2–R5 原件曾具有这些记录；§13的条件扩展不要求全部旧记录补字段。

### 5.1 `build-record.json`

| 字段 | 类型/必需性 | 来源/公式 |
|---|---|---|
| `schema_version` | integer=1，必需 | 本契约版本；未知版本拒绝 |
| `manifest` | `FileRef`，必需 | build 所读 manifest 原文件 |
| `identity` | object，必需 | manifest 的 cycle/round/checkpoint/change/round/candidate 六项原样复制 |
| `sources` | object，必需 | `config/defaults/executor/contract/convergence_algorithm/report_storage` 各为 `FileRef`；固定源，不是任意 caller 指定替代品 |
| `effective_config` | object，必需 | §4所列 guard、mode、checkpoint policy、团队、max_rounds、drift/criteria 的有效值；每项带实际源 JSON Pointer，不接收 `policy_ok` |
| `budgets` | object，必需 | 三个固定 integer，与 manifest 逐项核对 |
| `roles` | array，必需 | manifest 顺序的 `index/role_id/agentType/model_alias/prompt_sha256/label`；index 为从0开始整数，prompt hash 为字符串 UTF-8 字节 hash |
| `workflow_script` | `FileRef`，必需 | 生成脚本的最终字节，先生成后计算 hash；不包含循环自 hash |
| `attempt_index/genesis/prefix_head/reservation/input_closure` | integer/FileRef/nullable FileRef/FileRef/FileRef，必需 | §10固定 scope 的真实 reservation、此前事件 head 与运行前字节闭包；无反向自 hash |
| `recovery_preflight` | `FileRef`，仅§13首次后继必需 | 指向本 run-dir 的 `recovery-preflight.json`；首后继之外键必须不存在，不补 null；由真实 prefix/reservation 判条件，不由字段自报决定 |
| `host_build_duration_ms` | integer>=0，必需 | build 宿主单调时钟的本次构建区间；非原生准入时长，不参与票判定 |
| `generated_at` | string，展示字段 | VM 外记录，允许只读比较时忽略，不能充当任何截止或身份 |

`identity` 的精确键为 `audit_cycle_id/client_round_id/checkpoint/change_id/round/candidate_sha`。记录自身 hash 在 collect 的 inputs 中计算，不把自身最终 hash 写回造成循环依赖。

### 5.2 生成 Workflow 的边界

- 文件以纯字面量 `export const meta = {...}` 开始，meta 至少有 `name/description`，若有 phases 则与 `phase()` 标题一致。
- manifest 内容为冻结 JSON 字面量；公开 `args` 只承载本轮身份和 manifest hash 的一致性检查，不允许覆写 roles/prompt/预算。collect 校验 `/args` 对应值和嵌入的冻结身份，缺失或不符拒绝。
- `label = "audit:" + client_round_id + ":" + String(index)`，index 从0开始、十进制、不补零。用预生成的完整 label 做精确映射，不按冒号拆分推断 role；client_round_id 不得跨轮复用。原生节点的 `index` 是全局 progress index，**不能**当本契约角色 index。
- 每席调用**之前**先记 `attempted=true`、role/index/label，然后才 `agent(prompt,{agentType,label,phase})`。声明 roles 本身不是 attempted；VM attempted 也不是原生已启动证明。
- 最多两个未返回 `agent()` Promise。120000ms 只能标注软超时，不能释放 worker 或另开调用；仅 await 原调用返回/抛出后该 worker 可继续。300000ms timer 回调置 stop，置 stop 后不能再调用 agent。
- 轮终点返回深拷贝快照。回调晚到不再修改已返回对象、结果数组、raw 或参与集合。timer 置 stop 并不证明原生 D 精确停派发或 OS 子进程退出。

### 5.3 新脚本 `/result` 快照

以下是生成脚本**新增**的返回格式，不得套到旧 R2–R5 原件并伪称原本存在。

| 字段 | 类型/必需性 | 定义 |
|---|---|---|
| `schema_version` | integer=1，必需 | 未知版本拒绝 |
| `identity` | object，必需 | 同 build-record 的六项身份 |
| `manifest_sha256` | `Hash`，必需 | VM 外冻结并嵌入的 manifest 原字节 hash |
| `control` | object，必需 | `round_timer_ms:300000`、`stop_observed:boolean`、`return_reason:"all_settled"|"control_timeout"`；都是脚本观察，非原生时钟证明 |
| `results` | 与 roles 等长 array，必需 | 每角色恰好一项；保持 index 顺序，不删除未派发项 |
| `results[].index/role_id/agentType/label` | integer/string，必需 | 与 build-record 的相应项完全一致 |
| `results[].attempted` | boolean，必需 | 在调用前设置；false 时该项不允许有原生节点 |
| `results[].settled` | boolean，必需 | 快照返回前是否观察到 agent Promise 返回或抛出；不是原生 completed 标记 |
| `results[].raw` | JSON value，必需、nullable | 实际返回值原样保留；正常公开无 schema 调用为 string 或 null；非字符串非null保持其类型并判 parse_error，不 stringify 成有效票。未返回/抛出为null |
| `results[].error` | string，必需、nullable | 脚本观察到的异常；不据此猜 API失败/用户skip/原生终态 |

`attempted=false` 必须 `settled=false/raw=null/error=null`；`settled=false` 必须 `raw=null/error=null`。若原生节点与快照身份、调用事实矛盾，报证据错误，不用快照覆盖原生时间。截止后 native 更新可给出更晚 C，但不能将新 raw 塞回冻结快照补票。

### 5.4 最终 JS 容量与普通 pending 边界

`MAX_WORKFLOW_SCRIPT_BYTES=524288` 固定，无配置或 CLI 覆盖。`_check_workflow_capacity` 量 renderer 返回的最终 bytes，`len(program)>524288` 报 `E_WORKFLOW_CAPACITY`，reason 恰为 `workflow_bytes=<实际整数> limit=524288`；等于 L 允许。manifest 文件大小、prompt 字符数、UTF-8 输入大小都不是判据，JSON 转义后的最终 JS 才是判据。

`build` 在读/校验 manifest、固定配置与路径形状后渲染 `program`，在进入 `_writer_lock` 之前检查容量；因此该容量拒绝不创建/改写 scope、run、锁、blob、genesis、observe、reserve 或 record。新 reservation 发布同一份已检查 bytes，不二次渲染替换；容量诊断先于锁内历史来源漂移/预算诊断，但不覆盖之前的输入/配置错误，也不提供派发许可。纯 `_workflow` renderer 不内嵌容量门，仍可重建旧字节。

普通精确 pending resume 仍限六源兼容、最终脚本合规、manifest/身份/冻结输入匹配的准备物：`_resume_build` 只返回原 script/record，必要时补同一 record，`resume_only=true`，不新建 reserve、不派发。当前 host 对超限输入仍先零写入拒绝，不承诺任意旧源码的超限 pending 可跨源码普通 resume；单独的源变化在尺寸合规时仍报 `E_SOURCE_DRIFT`，唯一受限旧→新承接见§13。

`_prepare_policy` 对 required checker 的最终 `_render_policy_workflow` bytes 使用同门，检查位于 `policy-workflow.js` 与成功 `prepare-record.json` 发布前。此前 audit closure、blobs、policy-request 可能已发布，故不是整次 prepare 零写入。超限不生成假 checker 结果；既有真实 checker `tool_error`/unknown 资源路径保留，§13不支持 checker 容量拒绝恢复。

## 6. 原生字段映射与完整性边界

`--native-record` 指真正的 Workflow JSON 文件；不接受 AI 摘要、Markdown、persist 派生聚合或换壳成“native”的 fixture。下表的 JSON Pointer 中 `i` 是真实 progress 数组位置。

| 输出/输入概念 | 真实原件位置 | 类型与约束 |
|---|---|---|
| `workflow_run_id` | `/runId` | 非空 string，等于 CLI 真实 RUN_ID |
| `workflow_script_sha256` | `/script` | 必需 string；对该字符串 UTF-8 字节 hash，与 build-record 生成脚本相等；`/scriptPath` 只追溯，不证明执行内容 |
| `native_start_time_ms` | `/startTime` | 必需非负 integer，原生零点 |
| 原生外层耗时/状态 | `/durationMs`、`/status` | duration 非负 integer；已观察完整返回为 `completed`，但它不证明所有 agent 完成 |
| 调用节点列表 | `/workflowProgress` 中 `type="workflow_agent"` | 必需 array；phase 等其他 type 不计角色；核对顶层 `/agentCount` 与调用节点数，不能用它代替准入数 |
| 节点身份 | `/workflowProgress/i/label`、`agentType`、`agentId` | string；label 与冻结角色一对一、agentType 完全匹配、agentId 不重复；额外/重复/串轮节点拒绝 |
| 原生 q | `/workflowProgress/i/queuedAt` | 有节点时必需非负 integer；不是 VM attempted 时刻 |
| 原生执行起点 | `/workflowProgress/i/startedAt` | integer 或缺失；缺失归一为null，仅未完成节点允许；有值必须 `startTime<=q<=startedAt` |
| 原生完成时长 | `/workflowProgress/i/durationMs` | integer>=0 或缺失；缺失归一为null；`state="done"` 必须具备 startedAt/durationMs |
| collect 时完成 C | `startedAt + durationMs` | 只在原生有一致完成证据时计算，不能由原件外层 duration、最后 tool 时间、结果到达时间或预设120/300秒推测 |
| 原生观察状态 | `/workflowProgress/i/state` | 已观察 `start/progress/done`；未知 schema/state 不猜终态，拒绝解析并保留原件 |
| 实际模型 | `/workflowProgress/i/model` | 有节点时需记录 string 或null；与 `model_alias` 分开，不作相等门 |
| raw | 新生成脚本 `/result/results/index/raw` | 使用冻结全量值；`resultPreview/promptPreview` 是预览，绝不能代替完整 raw/prompt |
| 完成终态引用 | 对应 done 节点的 `NativeRef` | 仍记录 C 及引用，无论准入与否 |
| 中断终态引用 | 对应 agent JSONL 的 `JsonlRef` | 经§10.4运行后 index 显式传入，不是 Workflow JSON 自带字段 |

原件应为真实工具保存的完整、可解析返回，必须有脚本、身份、完整逐角色快照与 progress 数组，节点数与 agentCount 一致。`status!=completed`、缺 result、截断、计数/映射不一致不能凭节点缺席判 not_dispatched。**没有公开独立“日志已完全 flush”证明字段**；上述交叉核验不是对外部恶意裁剪的真实性证明。

新路径的 `attempted=true` 却无原生节点、`attempted=false` 却有节点、done 缺时长、未完成节点带互相矛盾的完成字段、快照已有完整返回却原生不能提供其完成证据，均为 `E_NATIVE_EVIDENCE`。未知 C 仅适用于证据一致的未完成调用，不用来吞掉损坏记录。

原生 `state=done` 的 C 可以晚于外层 Workflow 返回时刻；collect 是证据视图，不强加 `C<=startTime+Workflow.durationMs`。原生未知完成不填0；JSON false 不得作为 integer 0混过时间检查。

### 6.1 `termination_evidence`

每角色必需字段：`termination_evidence: "completed"|"interrupted_observed"|"unknown"`，以及 nullable `termination_ref`。

- 有一致 done/C：`completed`，引用原生节点。
- 无 C，但有映射到本 run/agentId 的运行时中断原件：`interrupted_observed`，引用确切 JSONL 事件；**C仍为null**。
- 无上述证据：`unknown`、引用null；未派发席也为unknown，但它没有占用调用槽，不阻塞下一轮。

核验过的8个历史未完成调用的 JSONL 均有 `type="user"`、`message.role="user"` 的事件，正文为 `[Request interrupted by user]` 或 `[Request interrupted by user for tool use]`。逐条以 sources.json 定位的原件 hash、agentId、uuid、行号核验；不以字符串在任意 prompt/assistant/tool 输出中出现为证据。正文可在 string 或 text block 中读取，但必须是该事件的完整正文，不做子串模糊匹配。

这些是运行时观察，不是本任务获得了真人取消授权，也不是 OS 进程全部退出证明。缺显式 transcript 入口时保留unknown，不猜 `subagents` 顶层路径，不伪造中断。

仅对 guard=true：下一轮（含 void 补跑）新增派发前，必须重放同 cycle **全部既往 attempted 审计及 auxiliary 调用**并展示终态引用，不能只检查前轮。`_resource_summary` 把经核验的 `completed`、`interrupted_observed` 视为该资源视图的非 unknown；中断不产生 C、不证明 OS 全部子进程已退出。任一已派发调用仍 unknown，`next_round_dispatch_allowed=false`，禁止下一轮新增派发；未派发席不占槽。同一 reservation 内 required checker 另按 `available_slots=max(0,2-unknown_calls数量)` 检查可用槽，两槽均未知时 `E_RESOURCE_PENDING`，不是以失败释放槽。该资源约束不改本轮有效票、收敛公式或额度，也不暗中收紧 false 的旧资源策略。跨会话不能只信一个自报 allowed 字段；`resume_only=true` 仅恢复原证据链，零重派。

## 7. 双时钟、六态与迟到 raw

### 7.1 原生准入与 VM 控制分别记录

```text
T0 = native.startTime
q  = node.queuedAt
C  = node.startedAt + node.durationMs，未知时 null
D  = T0 + 300000
in_window = C 已知 AND C-q <= 120000 AND C < D
```

时间为同一原生记录的整数毫秒，需验证 `T0<=q<=startedAt<=C`，不得用 VM 相对 timer 事件混入上述算式。

VM 的 S0 是安装相对300000ms timer的事件；公开接口没有给出 S0 对应的原生 timestamp。固定记录：`control_native_alignment="unknown"`、`control_origin="timer_installation"`、`control_timer_ms=300000`；不虚构 `S0_native_ms=0` 或未知偏移=0。

每角色另算：

- 有节点时 `dispatched_at_or_after_native_deadline = (q>=D)`；无节点为null。
- 有节点时 `unfinished_at_native_deadline = (q<D AND (C is null OR C>=D))`；无节点为false。它表示原生D时的历史窗口，不表示collect当下仍在运行。
- 外层 `native.durationMs`、`host_build_duration_ms`、collect宿主单调时钟耗时独立记录，不改变D或预算。check-result 忽略本次校验自身耗时这一展示量，不能以此忽略原计算的准入时间。

软timer偏移导致 D 后派发时必须显影且拒票，不宣称“硬截止保证成立”。原生节点按 `[q,C)` 观察未终结调用重叠；未知C不能在120000处截断以制造空槽。若证据显示同轮未终结调用同时超过2，拒绝该调度实现；中断事件不能冒充一个已知C。

### 7.2 六态 first-match

先完成§6完整性/时序验证，再按下表首个命中退出。`execution_state` 是 collect 时视图，不是 VM 截止时快照。

| 优先级 | `execution_state` | 精确判据 |
|---|---|---|
| 1 | `not_dispatched` | 完整原生记录无映射节点，且 attempted=false |
| 2 | `dispatched_no_completion` | 有有效节点，但 collect 时无可验证C；C=null，不声称当前仍运行 |
| 3 | `completed_late` | C已知且 `C-q>120000 OR C>=D`；先于所有 raw 判定，真实C不得清空 |
| 4 | `completed_no_result` | C已知、窗口内、raw=null；不推断skip或API失败 |
| 5 | `completed_parse_error` | C已知、窗口内、raw非null，但§8契约失败 |
| 6 | `completed_admitted` | C已知、窗口内、raw报告有效；唯一可投票状态 |

指定边界（数值相对原生T0，生产输出保留实际整数timestamp）：

| q / C / raw | 结果 |
|---|---|
| 0 / 120000 / valid | admitted |
| 0 / 120001 / valid | late |
| 200000 / 300000 / valid | late（C=D不准入） |
| 0 / 130000 / null | late，不是 no_result |
| 200000 / 310000 / valid | late，C保留310000，unfinished=true |
| 有节点 / null / null | no_completion，C仍null |

### 7.3 隔离 raw

每角色输出 nullable `raw_ref/raw_sha256`，有真实raw则必须同时有完整内容引用与hash。原件内字符串可用 NativeRef；若另存文件，其字节与原值 UTF-8 保持一致；非字符串坏值保留其原生 JSON Pointer，不转换成有效字符串。`raw_sha256` 对字符串为其UTF-8字节hash，其他非null值为保存的隔离证据文件字节hash，不能混用两种表示却声称hash相同。

`late_raw_ref` 仅在 completed_late 且确实取得raw时非null，指向同一隔离证据；未捕获的迟到raw保持null，并记录不可取得原因，不用预览补齐。迟到、无完成证据或parse失败的内容不能进入票、参与集合或结论keys。迟到内容只能进入既有独立事实核实通道；该通道不是多一票、旧票继承或修改历史结果的入口。

## 8. raw 报告判定

无 `schema` 的公开 agent 返回值按原类型处理：

1. 必须为string，`trim()` 后直接解析整个 JSON；或整个文本匹配 `^\x60\x60\x60(?:json)?\s*([\s\S]*?)\s*\x60\x60\x60$` 后解析捕获内容。这里 `\x60` 表示反引号。只接受无语言标记或小写 `json` 的整体 fenced JSON，不从解释文字中搜花括号。
2. JSON顶层必须是object，不能为null/array；拒绝重复key、非有限数。额外说明字段可保留但不产生票或准入事实。
3. 下表字段逐项验证。格式契约失败是 `completed_parse_error`，不是坏输入给整个collector补PASS。

| 字段 | 类型/必需性 | 值域/判定 |
|---|---|---|
| `vote` | string，必需 | 仅 `PASS/REVISE`；不接受质量verdict、CONVERGED、SKIP |
| `coverage_complete` | boolean，必需 | 不做truthy转换 |
| `findings` | array<object>，必需 | 空数组合法；每项必须满足下表 |
| `pending` | array，必需 | 与历史parser一样只要求数组；非空必须投REVISE，不自行假设元素schema |
| `prior_findings` | array，必需 | 与历史parser一样只要求数组；不从其中恢复缺席席位的旧票或把open项自动加入本轮keys |

每个 finding 均需：`severity` 为 `critical/major/minor`；`type` 为 `issue/risk/decision`；`category` 为 `implementation/testing/documentation/architecture`；`scope/file/failure_scenario` 为string；`line` 为integer>=1且非boolean。保持既有parser类型判定，不顺手新增 scope 非空、summary 必需、prior_id 格式等新准入门。`summary/prior_id` 可保留作展示，不能伪造它们改变相等判定。

若 `coverage_complete=false OR pending.length>0 OR 任一finding.severity∈{critical,major}`，则 `vote` 必须为REVISE，否则报告无效。反向不成立：完整覆盖、只有Minor或零finding仍可投REVISE。REVISE是有效准入票，不是执行失败。

报告有效不代表本轮可比或收敛；只有 execution_state=completed_admitted 的有效报告才参与后续计算。

## 9. round-result 与参与集合

### 9.1 必需顶层字段

| 字段 | 类型/nullable | 来源/公式 |
|---|---|---|
| `schema_version` | integer=1 | 新宿主schema |
| `identity` | object | build/manifest/native一致的六项身份 |
| `budgets` | object | 固定120000/300000/2，不能取工具外实耗替换 |
| `inputs` | object | `manifest/build_record/config/defaults/workflow_script/native_record/genesis/reservation/input_closure/audit_index/policy_request/prepare_record/publication_record` 各FileRef；`prefix_head/previous_round/previous_attempt/drift_index` 为FileRef或null。闭包含所有代码/契约/policy原字节，按§10冻结时点校验 |
| `attempt_index` | integer>=1 | 本次 reserve 次序，不替代 identity.round |
| `workflow_run_id` | string | 原生runId且等于工具回执 |
| `workflow_script_sha256` | Hash | 原生嵌入script核验所得，不读取scriptPath作执行证明 |
| `clock` | object | 原生T0/D、control三项固定语义、native外层耗时和宿主单列耗时；整数或明确允许的null，不推算偏移 |
| `require_same_admitted_roles` | boolean | 当前固定配置有效值，非manifest覆盖 |
| `configured_roles` | RoleSet | manifest完整配置角色，不用于推断实际参与 |
| `dispatched_roles` | RoleSet | 有唯一有效原生节点的角色 |
| `admitted_roles` | RoleSet | execution_state=completed_admitted 的真实角色 |
| `roles` | array<object> | 配置顺序逐席记录，见§9.2 |
| `conclusions` | array<object> | 仅本轮准入 findings 的 canonical_v1 结果（§10.7），不借旧 persist 或 prior_id 归一化 |
| `comparison_keys` | 唯一Key数组 | 从真正的conclusions提取，按tuple字典序确定性排序 |
| `conclusion_keys_equal` | boolean | 有合法紧邻前轮且两完整Key集合严格相等；首轮为false |
| `population_comparable` | boolean或null | 开启时见§9.3；关闭时null |
| `population_reason` | enum string | `disabled/first_round/missing_participant_evidence/empty_population/population_changed/same_population` |
| `incomplete` | boolean | admitted_roles数量不等于configured_roles数量 |
| `all_failed_void` | boolean | admitted_roles为空；不得将此轮包装成空结论稳定 |
| `unanimous_pass` | boolean | 非空准入票全部PASS，并应用有来源的既有drift覆盖；不能只计算原始票后漏WARN |
| `conclusions_stable` | boolean | §9.3公式，不以incomplete直接否决 |
| `converged` | boolean | §9.3公式及既有policy，不等于质量PASS或merge clearance |
| `policy` | object | §10各政策输入/派生状态及逐项来源引用；来源缺失则不发布成功结果，不能填默认放行值 |
| `verdict` | enum | `PASS/PASS_WITH_WARNINGS/FAIL`，按既有质量规则及drift override |
| `next_round_dispatch_allowed` | boolean | 已派发调用均有已观察终态且资源约束可核验时才true；unknown必须false，独立于converged |
| `generated_at` | string | VM外纯展示时间，check可忽略 |

不新增可放行的 `merge_clearance=true`。既有merge gate仍归原消费者；JSON/MD中质量PASS不能替代converged、资源约束或合并门。

### 9.2 每席必需字段

`index/role_id/agentType/label/model_alias` 来自build-record；`native_agent_id/actual_model/native_ref` 在无节点时均null，有节点时逐字段记录；`attempted/settled` 来自冻结快照；`queued_at_ms/started_at_ms/duration_ms/completed_at_ms` 按§6归一（无节点均null，未知C仍null）。

另必需 `execution_state`、`termination_evidence/termination_ref`、`dispatched_at_or_after_native_deadline/unfinished_at_native_deadline`、`raw_ref/raw_sha256/late_raw_ref`、nullable `report`、nullable `parse_error`。`report` 仅 admitted 非null；parse_error 仅在确实执行格式检查且失败时记录原因，不把late也写成parse失败。所有非null原生事实必须有指向其原件字段的引用，不引用派生MD自证。

### 9.3 guard 的配对与公式

合法配对：同 `audit_cycle_id/checkpoint/change_id`，前一有效轮 `round=current.round-1`，不同 `client_round_id`；必须等于固定账本最新有效 head 并完成§10.6闭包重算。void 只进入 attempt 史，不替换比较对象；例如有效R1→void R2→新attempt有效R2，最后一项仍与R1比较。candidate/model只追溯，configured集合不能替代admitted集合。

开启时，按以下顺序：

1. round=1且没有previous：`false/first_round`；round>1却没有previous为`E_PREVIOUS_REQUIRED`，不是first_round。
2. 前轮可识别且同cycle/相邻，但缺真实参与证据：`false/missing_participant_evidence`。普通历史报告若连cycle身份也没有，不自动赋cycle；报告此缺证且不得参与相等/稳定计算。已声明身份但串cycle/损坏/不相邻则直接错误，不伪装旧报告缺字段。
3. 当前或前轮真实admitted集合为空：`false/empty_population`。
4. 两实际集合不等：`false/population_changed`；大小相同但角色不同也不等。
5. 非空且完全相等：`true/same_population`。

前轮证据按§10.6追到 genesis、连续尝试史及逐席原生输入；只读 frontmatter `agents`、数组长度、历史自报 boolean 或短 ID 均不满足。旧报告缺参与证据可给诊断性 missing_participant_evidence，但不能用它代替新路径要求的完整轮史后发布生产成功结果。

```text
conclusion_keys_equal = 有合法前轮 AND 完整四元组集合严格相等
population_comparable = 上述开启guard判定；关闭时null/reason=disabled
conclusions_stable = conclusion_keys_equal AND
                     (NOT require_same_admitted_roles OR population_comparable)
converged = conclusions_stable AND unanimous_pass AND NOT all_failed_void
```

任何缺少比较证据的向量都不能使 `conclusion_keys_equal=true`。关闭向量按旧算法计算，不用missing_participant_evidence额外阻断legacy。开启时同一部分角色、keys相同、准入票全部PASS且无既有policy阻断，即使incomplete=true仍可converge；不新增7/7门。

## 10. revision2 证据协议与唯一重算

本节对应当前 `audit_executor.py` 的证据协议与重算宿主；函数名可在该源码定位，不以契约存在替代真实调用验收。本节evidence/index/ledger/request/处置wrapper均为封闭schema：列出键必需、未知键拒绝，null只按明示分支；identity仍精确六项，raw额外字段继续按§8保留。所有计算宿主仍是单一 stdlib `audit_executor.py`；audit-engine 只负责真实工具调用与显式原件定位，不手写 policy boolean。`schema_version=1` 配合 `algorithm_version="canonical_v1"`；未知版本拒绝，不执行冻结的旧 Python/JS。工具外同时伪造整套源不在§2威胁模型，不新增签名或授权平台。

### 10.1 四个设计阻塞的闭合位置

| 原阻塞 | revision2 唯一生产者 → 消费者 | 实现解除所需证据 |
|---|---|---|
| `B_POLICY_TRANSPORT` | `_load_fixed_policy/_freeze_policy_inputs` → `_make_policy_request` → 真实独立 checker → `_apply_policy` | §10.2/4/5的原字节、提问关联和真实接线；缺源仍拒绝 |
| `B_TERMINATION_LOCATOR` | audit-engine capture adapter 写显式 index → `_verify_termination` | run/节点/agent/JSONL映射及损坏负控；无引用才允许unknown |
| `B_PREVIOUS_RECOMPUTE` | `_load_scope/_replay_history` → build/prepare/final/check | 固定genesis、全事件链与冻结输入递归重算，不信单previous |
| `B_CANONICAL_AGGREGATION` | `_aggregate_admitted` → request/result/check/MD | §10.7同一字符级算法、成员守恒及碰撞负控；不调用历史persist |

修订审查前暂停产品实现；审查通过后仍须代码、独立负控和真实调用才能解除生产阻塞，不能把这张表当验收回执。

### 10.2 运行前输入、来源闭包与 bootstrap

manifest 增加以下**必需**对象（所有键必需，只有标明的分支可null）：

```text
evidence = {schema_version:1, cycle_origin:FileRef|null,
  previous_round:FileRef|null, dispatch_preflight:FileRef|null,
  policy_inputs:FileRef, post_audit_index_path:string,
  post_drift_index_path:string, post_disposition_index_path:string}
```

后面三个是本 run-dir 内的未来 locator，不是 FileRef、不是原生字段，首次build时必须不存在；该不存在约束不用于collect/check或已预留身份的精确恢复。build 冻结其字符串，不预填 runId/hash，运行后不改 manifest。非null运行前引用必须已经存在；`previous_round` 精确等于账本最新有效结果（忽略void），`dispatch_preflight` 仅提供旧调用较晚终态。路径按承载文件解析，写路径 realpath 限定本 run-dir/固定 scope，拒绝逃逸与symlink替换。

`policy_inputs = {schema_version:1, context:FileRef, spec_source:FileRef|null, anchor_selection:{primary_goal:Span|null,in_scope:[Span],out_of_scope_hints:[Span]}, fallback_sources:[{kind:"proposal"|"decisions"|"issue_title"|"pr_title",locator:string,source:FileRef|null}]}`；`Span={source:FileRef,start:integer>=0,end:integer>=start}`，值为该源UTF-8字节切片解码的完整字符串，禁止切断字符。编排层选择片段，`_freeze_policy_inputs` 验证并冻结，不声称机器证明自然语言提取正确。固定源解析mode/adaptive/level，adaptive直接解析本change proposal的Level标记，支持Full/Level 3→3、Standard/Level 2→2、Skip/Level 1→1；冲突/缺失且无法依成文默认得到convergence报 `E_POLICY_SOURCE/E_UNSUPPORTED`，不采信manifest mode_ok。

Step0按SKILL的checkpoint fallback顺序逐项实际读源：proposal优先取本repo `openspec/changes/<change_id>/proposal.md`，不存在则检查archive同change_id，歧义拒绝；decisions取实际context文件。fallback_sources不能省略/替换这些适用候选，source=null仅在宿主实际读取locator得到ENOENT时成立，EACCES/无法解析不是missing。宿主产 `{schema_version:1,observations:[{kind,locator,outcome:"read"|"missing"|"no_anchor",source:FileRef|null}]}`，read/no_anchor必须留真实字节引用，missing才null。issue/PR标题以显式捕获的实际响应原件解析；标题无法获取不能伪称全缺，报 `E_POLICY_SOURCE`。只有宿主对全部适用候选实际读取/解析后均无锚才生成 `anchor_missing_observed`，记录候选、读取结果与源引用；wrapper缺失不是缺锚证据。存在的anchor值含 `checkpoint/primary_goal/in_scope/out_of_scope_hints/source_sha`，source_sha为当时Git对象id，不替代文件hash。`_freeze_policy_inputs`必须生成不可变 `AnchorRecord={schema_version:1,status:"present"|"missing",value:<上述anchor值>|null,observations:FileRef}`：present要求value非null且primary_goal非空；missing要求value=null，且observations指向宿主实际遍历全部适用fallback后生成、可重算的无锚观察记录。缺观察原件是E_POLICY_SOURCE，不得生成missing记录冒充已观察。genesis.anchor与policy-request.anchor的FileRef均引用这个真实AnchorRecord文件，不是要求不存在的裸anchor值文件；因此合法缺锚仍有可验证记录，而不伪造占位anchor。后续轮复用genesis的原记录与原始来源快照，不重新取当前source_sha或重抽片段；当前context/candidate可变，不以整个context文件相等增加新门，不允许re-anchor。

固定scope为 `REPO/.aria/audit-reports/_executor-ledgers/<scope_key>/`，`scope_key=sha256(C([checkpoint,change_id])).hexdigest()`，不含cycle/candidate/model。`C(x)=json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')`；结构比较用完整C字节，FileRef始终hash实际文件字节。**首次合法null**只在锁内确证genesis不存在、无events/reservation，且完整扫描项目报告目录未发现可归属当前(checkpoint,change_id)的既有周期后成立。checkpoint必须相同；context仅作change归属线索，不能因不同checkpoint复用同context就判为同scope。新JSON读取明确identity；legacy MD沿用completeness_gate.py::_file_belongs的checkpoint前缀、完整change_id界定及已知更长ID排除规则，context可按精确已知change_id或规范Spec路径补充归属，不把裸change_id误当文件路径。字段冲突或有当前scope线索却无法唯一归属时E_POLICY_SOURCE；其它归属不明条目保留完整路径/hash与UNKNOWN告警，不把它们伪称“已证明没有历史周期”，也不从它们迁移或恢复cycle。本宿主只保证已登记及可归属scope的谱系约束，不声称识别工具外改名伪造业务身份。扫描不进入fixtures，不用截断清单；保存归属结果及路径/hash清单至origin观察记录。旧周期存在或来源无法消歧，不新建genesis包装它；PR #38尤其不迁移。已有scope的新attempt必须传真实genesis FileRef；null/换cycle/较早head报 `E_PREVIOUS_IDENTITY`。唯一恢复例外为同一已存在reservation且manifest原字节完全相同：允许保留首次manifest的原null，不视为新attempt，也不重建genesis。本期不提供自动rollover。

**历史字段解释补充（读取 schema，不是 AI 调度指令）**：`_origin_observation` 对一种封闭的 legacy Markdown 形态调用 `_legacy_markdown_change`。这仅解释旧字节，不改变§3生产路由、convergence-only 执行限制、轮数、预算、原审计结论或 PR #38 暂停：

- 已识别形态为文件开头完整的 `---` frontmatter，内容为平面 `key: value` 行（空行和整行注释可读；值可用成对单/双引号包裹，不做完整 YAML 转义/对象解析）。`checkpoint` 值为 `convergence` 或 `challenge` 时进入此兼容验证；文件名必须有已注册 checkpoint 前缀，`audit_type` 必须与此前缀逐值一致。真实 checkpoint 取此前缀，原 `checkpoint` 仅解释为旧模式；不是任意 checkpoint 冲突的豁免，也不使新执行器支持 challenge 调度。
- 至少声明 `spec_id/context` 之一。`spec_id` 精确等于已知 change_id；`context` 精确等于已知 change_id，或已发现的 `openspec/changes/<id>/proposal.md`、`openspec/archive/<directory>/proposal.md` 的项目相对/绝对路径。已知集合来自本次 change_id 与实际 change/archive 目录；archive 目录按既有规则去除开头日期。裸 ID 不当文件路径解析，不做子串、basename、任意路径归一化或正文猜测。所有已声明的 `spec_id/context`（以及出现时的 `change_id`）均需可识别且指向同一个 change；未知或矛盾字段即 `E_POLICY_SOURCE`，不降为其它 scope 的 UNKNOWN。
- 文件名若含完整已知 change_id，仍与字段交叉核对；完整更长 ID 排除其短 ID 子串，余下的文件名归属必须唯一且等于字段归属。缩写文件名自身不提供另一归属。frontmatter 任意键重复（即便同值）、不完整/非平面 frontmatter、缺失/不匹配的 `audit_type`、缺少已注册前缀、未知模式、真实 checkpoint 冲突仍拒绝；正文不能补 frontmatter 身份。
- 解释后的 `(checkpoint,change_id)` 仍参与原 scope 检测：当前 scope 历史报 `E_PREVIOUS_IDENTITY/existing_scope_history_no_migration`，在 genesis、events/reservation 与 workflow 发布前停止；另一 checkpoint 与同一 change 不等于同 scope。现有 genesis 的 origin/head/pending 限制原样保留。
- 成功观察沿用 `files:[{file:FileRef,attribution}]`，兼容条目增加 `warnings:[{code:"LEGACY_CHECKPOINT_MODE",file:FileRef}]`（与原 UNKNOWN 告警同结构）。FileRef 仍指原路径/原字节 hash，原字节进入 input_closure；解释可由冻结 frontmatter、文件名和观察归属追溯，不写回或重命名旧报告。非此形态仍使用原读取规则，原有其它无归属条目的 UNKNOWN 观察不变；软链接、完整扫描和读取错误护栏不变。

genesis由首次build排他创建，形状为 `{schema_version:1,algorithm_version:"canonical_v1",audit_cycle_id,checkpoint,change_id,policy_inputs:FileRef,anchor:FileRef,origin_observation:FileRef,initial_sources:{config,defaults,executor,contract,convergence_algorithm,report_storage},initial_max_rounds:integer>=1}`（initial_sources值均FileRef）。它只引用已存在冻结字节，不含manifest/reservation/build-record hash；manifest初次cycle_origin=null不回写，build-record引用新genesis最终hash。故bootstrap无自hash或未来hash环。

`input_closure={schema_version:1,algorithm_version:"canonical_v1",sources:[{origin:string,sha256:Hash,blob:FileRef}]}`，按origin/hash排序且唯一；blob为实际原字节不可变副本，包含manifest、固定源、政策、历史及运行后原件，不能只存旧源路径/hash。解析嵌套引用时保留原承载文件origin作为base，按(origin,hash)找blob；无匹配拒绝，同origin不同hash只允许明确分时证据包，不混为同一次输入。当前轮仍重读固定config/defaults/code/contract等全部build.sources，任何漂移 `E_SOURCE_DRIFT`；历史回放只读冻结字节，不要求旧可变原路径仍相等。后续build核对当前固定config/defaults/executor/contract/convergence_algorithm/report_storage与已验证 active sources 的逐项SHA；未恢复scope的active sources仍为genesis.initial_sources，任何漂移均 `E_SOURCE_DRIFT`。唯一有界转换是§13经完整验证的首个dispatch_rejected导出to_sources；不改initial_sources、不通过普通build迁移或接受增大的config上限；合法+2仍只经处置事件。不执行归档代码。

### 10.3 固定账本、hash冻结顺序与恢复

账本只存genesis及连续事件，不保存可被信任的used_rounds/allowed。`events/0000000001.json`起，seq十位十进制连续；事件为 `{schema_version:1,seq:integer>=1,genesis:FileRef,previous_event:FileRef|null,kind:"reserve"|"commit"|"observe"|"disposition"|"dispatch_rejected",payload:object}`。seq1前驱null，其他恰为seq-1真实hash；缺口、重复、分叉、未知事件拒绝。不以选最新mtime恢复。write锁为固定 `writer.lock` 的stdlib `fcntl.flock(LOCK_EX|LOCK_NB)`；本后端要求可用的本地POSIX文件锁，不支持时报 `E_UNSUPPORTED`。build/prepare/final短事务持锁，锁被占用报 `E_SCOPE_BUSY`；不用PID/超时抢锁，崩溃由OS释放描述符。check不建锁，读取前后事件head不一致报 `E_SCOPE_BUSY`，不得读混合视图。

| 阶段 | 有序写入与引用（全部完整SHA-256） |
|---|---|
| build | 先按§5.4生成并检查最终bytes，再入锁冻结已有输入→必要时genesis→发布已检查workflow字节/metadata→input_closure→reserve事件→build-record；§13首后继另先冻结handoff并在reserve前复核live。reserve payload为 `{identity,attempt_index,manifest:FileRef,workflow_script:FileRef,previous_round:FileRef|null,previous_attempt:FileRef|null}`；previous_attempt是最近commit（含void）。build-record引用genesis/reserve/此前prefix_head与运行前input_closure，不被reserve反向引用 |
| audit后 | 实际capture adapter取得工具runId/Transcript入口和原件路径，稳定读取完整字节，生成§10.4 audit index；prepare验证并冻结原件/JSONL/所有叶子→审计input_closure→policy-request最终字节→必要的policy-workflow.js。request不引用该脚本，因此脚本可嵌入request hash而无环 |
| drift后 | capture adapter取得独立checker回执/原件，写drift index；最终collect验证、冻结新叶子→最终input_closure→result/MD最终字节→commit。commit payload为 `{reservation:FileRef,result:FileRef,markdown:FileRef,input_closure:FileRef}`；result只引用reservation与此前prefix，不引用未来commit或自身hash |
| 结果后 | 可选真实人类处置另冻输入→disposition sidecar→disposition事件；不修改已发布result/MD。check只重读冻结来源及当前固定源，不补文件、不重新接受hash |

prepare还写 `prepare-record.json={schema_version:1,identity:<六项>,attempt_index:integer,audit_index:FileRef,input_closure:FileRef,policy_request:FileRef,policy_script:FileRef|null,generated_at:string,host_prepare_duration_ms:integer>=0}`。最终collect在纯重算完成后、渲染前先写 `publication-record.json={schema_version:1,identity:<六项>,attempt_index:integer,generated_at:string,host_collect_duration_ms:integer>=0}`，耗时区间为该次collect入口至纯重算结束，不含后续发布I/O。再把两记录纳入最终闭包并渲染JSON/MD；记录不反引最终闭包或结果。恢复复用原publication元数据，不读新时钟；check只把这些宿主展示时间当冻结观察，不冒充原生准入时间。

所有capture对源作连续两次完整读取且字节一致才封存，变动则拒绝重试准备，不假造flush标记。封存后的live JSONL/native增长不改变旧证据视图；冻结blob自身改变按hash拒绝。后取得的终态仅作为新preflight，不能补旧raw或票。

每次build锁内重放完整prefix，校验latest有效previous及所有attempt资源。一个scope最多一个pending reserve，pending不能自动void；同reservation的精确恢复不产生新attempt、script或reserve。§13独立CLI只对已验证的首轮容量拒绝追加dispatch_rejected清除其pending，不把它当void或普通resume。build在同manifest字节/同client_round_id/同attempt_index/同输入且已有脚本与record均匹配时只返回已有路径并标 `resume_only`；缺record但reserve/脚本/闭包齐全可补record，不得重新派发；源不齐拒绝。Workflow回执缺失/调用活性unknown时暂停，不重用身份调用工具。消费方须把真实回执保存在本run-dir再恢复；没有回执不能证明从未启动。

除上述仅恢复分支外，生成任何新script或追加reserve前，必须在同一锁内用§10.5/6既有折叠重算当前prefix的政策view：`effective_limit=initial_max_rounds+已验证且一次性消费的increase_rounds事件数×2`、`remaining_rounds=max(0,effective_limit-charged_rounds)`；要求remaining_rounds>0，且不得已有CONVERGED/DRIFT_TERMINATED/OSCILLATION终局或accept_current/degrade_single处置（overridden_by_user/degraded）。MAX_ROUNDS_EXHAUSTED仅在当前prefix已有绑定该耗尽有效head的合法increase_rounds事件、重算后remaining_rounds>0且没有上述其它阻断时可重新开放；旧base的耗尽结果不回写。非终局（含REFOCUS_ROUND）的新attempt同样受额度与资源约束，void不耗额度也不豁免该检查。任一政策条件不满足报 `E_POLICY_BLOCKED`，不生成新script/reserve、不派发；不得凭轮号相邻、next_round_dispatch_allowed=true、改config或caller boolean绕过。此为既有policy折叠的build前置，不增加策略服务；最终collect/check及同reservation窄恢复不因此被当作新派发。

最终collect在同reservation、同全部冻结输入、已有JSON/MD逐字节等于重算产物时，允许仅补缺文件/commit；不同字节 `E_OUTPUT_CONFLICT`。generated_at和host_collect_duration_ms只从§10.3已冻结publication-record.json复用，host_prepare_duration_ms来自prepare-record.json，host_build_duration_ms来自build-record.json；三记录均须先验证身份/hash。恢复不采新时钟改变字节。commit已存在则仅幂等返回，不重复append。prepare同输入只复用完全相同请求，不覆盖另一证据视图；存在不同post-run原件即冲突。消费者要求完整commit和check，不能读取半发布文件。

### 10.4 运行后原件索引、独立drift与终态

以下index由TASK-012的capture adapter依据真实工具回执/显式文件路径写入，不是native schema；prepare/final由Python冻结其字节。`TerminationLink={native_pointer:string,agent_id:Id,event:JsonlRef}`。audit index精确形状：`{schema_version:1,identity:<六项>,attempt_index:integer,workflow_run_id:Id,native_record:FileRef,termination_refs:[TerminationLink]}`。identity/attempt须与build一致，runId须与CLI/原件一致；native_pointer指本run真实workflow_agent节点，agent_id同时匹配节点与事件，核对全JSONL hash/正整数行号/uuid/type=user/message.role=user和完整两种中断正文。错误引用报 `E_NATIVE_EVIDENCE`，不得吞为unknown；未提供引用才可unknown，done/C按原生优先。路径仅由回执Transcript入口或主控显式真实路径取得；可在明确目录内核对agentId，不能拼固定会话路径或扫描猜测的顶层subagents。

`dispatch_preflight={schema_version:1,observations:[{workflow_run_id:Id,native_record:FileRef,termination_refs:[TerminationLink]}]}`。build重算全部既往attempted与auxiliary_calls，只接受同run/script/startTime/agentId/label/agentType/q的较晚一致观察，身份或script变化报 `E_RUN_IDENTITY/E_NATIVE_EVIDENCE`，原生时间矛盾报 `E_NATIVE_TIME`。startedAt按§6归一后单调补全：此前已知整数不得改写或退回null；此前null可补为满足 `T0<=q<=startedAt` 的非负integer（排除boolean），有完成C时还须 `startedAt<=C`。done仍必须有一致的startedAt/durationMs/C；此前已知durationMs/C不得改变或清空，比较基准包含已经验证的observe证据，不能只比最早null快照。验证后追加observe事件（payload `{preflight:FileRef}`），仅更新资源证据view；不改旧结果的startedAt/C/raw/票/admitted及冻结快照。

仅补startedAt而无done/C或合法中断引用，termination_evidence仍unknown；合法中断也只导出interrupted_observed、C仍null，不冒充completed或OS进程退出。任何仍unknown的已派发调用阻断下一轮全部新派发；not_dispatched不占槽。drift另占调用槽，审计残留占满2槽则报 `E_RESOURCE_PENDING`，不能先造checker失败释放槽；可用槽数从真实终态重算，而非等待固定时长。终态补全只能解除资源阻断，不能覆盖§10.3的额度/终局/处置阻断。

`policy-request={schema_version:1,algorithm_version:"canonical_v1",identity:<六项>,attempt_index:integer,genesis:FileRef,anchor:FileRef,audit_index:FileRef,input_closure:FileRef,conclusions:[§10.7记录],required:boolean,reason:"all_failed_void"|"first_round"|"disabled_by_config"|"empty_conclusions"|"anchor_missing_observed"|"required",checker:{agentType:string,label:string,timeout_ms:60000}|null}`。reason按所列顺序首个命中；required仅最后分支true，其余checker=null。anchor引用§10.2的AnchorRecord，missing/value=null记录合法且必须有完整无锚观察来源；required=true强制该记录status=present且value非null，生成checker脚本时嵌入其value而非让VM读文件。first_round/configured_off等更高优先级原因可与missing记录并存，不强迫reason改为anchor_missing_observed。prepare/final/check均由源重算整个对象，不相信文件自报required。独立checker用配置团队第一项的**新实例**，不复用审计agentId或自评、不增投票角色；label=`"drift:"+client_round_id`，60000为已有30–60s独立契约内选定值，不占300000审计预算。Python唯一生成checker脚本（相同公开VM能力），args/prompt含最终request hash及完整anchor/conclusions；脚本hash产生在request之后。

drift index为 `{schema_version:1,identity:<六项>,attempt_index:integer,request:FileRef,kind:"workflow"|"tool_error",workflow_run_id:Id|null,native_record:FileRef|null,termination_refs:[TerminationLink],tool_failure:{call:SessionEventRef,response:SessionEventRef}|null}`。workflow分支必须有run/native且tool_failure=null；tool_error分支两者null、termination_refs=[]且tool_failure非null；不得用缺键代替分支。adapter在真实独立Workflow返回/实际工具错误后写入。final验证request原字节、独立runId、嵌入script等于宿主由该request重建的脚本、args/label/agentType与单一checker节点，raw取完整result不取preview。成功raw为JSON object `{classifications:[{key:Key,classification:"on_topic"|"adjacent"|"off_topic"}]}`，恰覆盖conclusions的每个完整key一次；重复/缺项/额外key是 `E_POLICY_SOURCE`，不当checker失败掩盖损坏。conclusions每type/bucket唯一，因此完整key足以定位，不使用短id。

partial-anchor严格复用challenge-mode-schema.md第291–297行：仅当冻结AnchorRecord.status=present且value.in_scope=[]、value.out_of_scope_hints=[]时成立，primary_goal仍须非空。宿主从request引用的冻结anchor重算该分支，不增caller开关；生成/重建checker脚本时在完整anchor/conclusions之前固定加入指令：“本次anchor为partial anchor；仅按每条结论与primary_goal的语义相关性分类：相关返回on_topic，否则返回adjacent；不得返回off_topic。逐个完整key恰分类一次，不返回scope-empty或confidence标注。”非partial分支保留原三类指令。final/check必须同时核对嵌入脚本的该固定指令及raw分类：partial收到任一off_topic即 `E_POLICY_SOURCE`，不得改成adjacent、伪造skipped或带入比例/refocus/终止计算；非partial的合法off_topic仍按原公式处理。

`result.policy`除§10.6所列键外增加两个必需键：`anchor_scope_empty:boolean`与`drift_classification_confidence:"low"|null`。prepare/final/check由同一冻结anchor唯一推导：上述partial分支为true/"low"，其它分支为false/null（不宣称高置信）；不接受AI手填或checker回传这两项标注。标注反映anchor分类依据，不证明checker已运行。partial不等于missing、不改变request.reason的既有first-match或required条件、不新增skip；required=true仍真实调用独立checker。成功partial分类的off_topic计数为0，ratio及action仍走原阈值公式，包括阈值恰为0的原有>=语义，不新增partial专用阈值或放行门。

真实spawn失败/自身超时才可沿用既有fail-open。kind=workflow时，生成脚本快照保存call_attempted、真实error或自身60000 timer观察以及returned raw，原生run/嵌入script必须可取得。kind=tool_error仅用于顶层Workflow工具在取得runId前直接失败；adapter必须引用主会话中实际tool_use及相联tool_result错误原件，匹配scriptPath/args和本次request；此分支workflow_run_id/native_record为显式null、termination_refs为空，仅验证tool_failure，不伪造agent/runId，也不套用workflow分支的必需字段。格式不能适配或只有审计席timeout报 `E_POLICY_SOURCE`；真实错误且無完成证据的调用仍unknown，保留auxiliary_calls阻断下一轮。`drift_check_skipped=true/ratio=null/action=NONE`只能由该失败证据导出；not_required并非checker失败。成功counts/ratio/action由Python重算，adjacent不进分子，空结论ratio=0。

数值消歧：本true路径采用Python binary64 float的JSON数值解析与 `/`、`>=` 比较，不另换Decimal/Fraction；阈值必须有限、在[0,1]且warn<=refocus。`r=off_topic/all`（all=0为0），先r>=refocus，再r>=warn，否则NONE；例如off=1/all=10与threshold=0.1同档命中，0.10000000000000002不命中；off=1/all=3与0.3333333333333333命中，与0.33333333333333337不命中。此为欠定部分的显式实现选择，不宣称旧散文已有字符级规定，不改变阈值配置。

### 10.5 原生问答处置（不是本cycle的新授权）

`post_disposition_index={schema_version:1,target_result:FileRef,question:SessionEventRef,response:SessionEventRef,options:[{label:string,action:"accept_current"|"increase_rounds"|"degrade_single"}]}`，`SessionEventRef={file:FileRef,line:integer>=1,event_uuid:Id}`，不冒充含agent_id的JsonlRef。capture adapter在真实AskUserQuestion完成后写入manifest的disposition locator；空事件集表示未消费动作，不使用approved=true。提问正文必须有且仅有一行 `audit-disposition-context=` 后接 `C({audit_cycle_id,checkpoint,change_id,target_result,used_rounds,effective_limit})` 的ASCII文本，值与当前耗尽head重算一致。options恰三项，action顺序固定为accept_current/increase_rounds/degrade_single，机器状态枚举保持英文；面向owner的label分别固定为“接受当前结论”“增加轮次”“降级为单轮”，description同样使用中文。宿主冻结模板将这三个显示字符串逐项绑定到对应action；逐项匹配原生input，不允许任意改label或交换映射冒充选择，也不从自由文本猜action。

`_parse_human_disposition`读取完整session JSONL，question为assistant中真实name=AskUserQuestion的tool_use；response为user中关联tool_result，核对tool_use_id及sourceToolAssistantUUID=提问assistant.uuid。response.toolUseResult.questions与原input.questions逐值一致，恰一题multiSelect=false；answers恰以该题question文本为唯一键，值严格等于一个option label；annotations必须为空（未适配非空布局拒绝）。再映射上述三个action，不以通知、任务正文、普通user文本或中断标记当处置。已实测的历史布局仅证明schema，不是本cycle授权；不认识的布局报 `E_POLICY_SOURCE`。

最终报告发布后可用**相同collect参数**再次提交该index：仅在目标为当前已提交耗尽有效head且尚无该head处置时，锁内重算并写不可变 `<stem>.disposition.json` 与disposition事件（payload `{target_result:FileRef,evidence:FileRef,sidecar:FileRef}`），不重跑审计、不改旧JSON/MD、不另提交轮。sidecar含action、来源闭包、target与重算后的effective_limit/overridden_by_user/degraded；其自身hash仅在后继事件保存。check同时验证已存在sidecar/事件与base结果，各自按冻结时点重算；消费者只使用当前head的已校验base+sidecar view，不能把旧结果布尔字段改成true。increase_rounds固定+2、一次性消费(question uuid,tool_use_id,response uuid)，之后同cycle新build方可使用新增额度；accept_current/degrade_single只在view标相应处置且converged仍false，阻止继续派发。无index不凭空生成sidecar。跨cycle、非耗尽head、选项不符或重放报 `E_POLICY_SOURCE`；重复完全同字节提交只幂等返回原sidecar，不再次加2。

### 10.6 历史递归、void/refocus与policy折叠

`_replay_history`从固定scope genesis/连续events遍历reserve→commit→result→input_closure及schema显式依赖边；§13新增dispatch_rejected及首次后继handoff的冻结验证，不生成audit row。不遍历raw文本中的任意path对象。仅沿schema声明的结构化依赖边遍历。结构化节点的visiting键为按承载文件上下文解析出的冻结origin字符串（沿用§10.2，键不含hash）；先检查该origin是否已在当前栈，若重入立即E_HISTORY_CYCLE，优先于该回边的hash/身份检查。非回边才读取blob、校验完整hash并解析schema，再入栈遍历；visited缓存键为(origin,sha256)，仅在完整验证后复用。结构化产物origin在本周期内不可覆写为另一hash；分时native/JSONL等不递归的opaque叶子不入visiting栈，仍逐FileRef校验hash。环fixture允许回边故意携带不匹配hash，不要求构造内容寻址自hash固定点；无栈重入的损坏叶子E_POLICY_SOURCE，跳seq/轮/串身份E_PREVIOUS_IDENTITY。遍历至seq1的null前驱及有效R1的previous=null才到起点，绝不将缺源当首轮。所有attempt_index连续、client_round_id及成功原生runId唯一；build不能选较早head。每个commit的previous_attempt为最近commit，previous_round为最近非void commit；void可重复同一逻辑round，其后首个有效attempt仍用该号。全部旧manifest/build/native/raw/policy原字节须可取得，不执行归档代码，不信历史admitted/converged/used等派生值。

三入口prepare/final/check共用 `_recompute_round`，调用同一 `_classify_native/_aggregate_admitted/_replay_history/_apply_policy`。build也用这些函数重放prefix。result.policy必含 `algorithm_version/is_refocus/consecutive_refocus_count/pending_refocus/charged_rounds/effective_limit/remaining_rounds/drift_required/drift_reason/drift_ratio/drift_check_skipped/drift_action/terminal_state/overridden_by_user/degraded`，各值来自下列折叠，不允许缺源默认false/0。原始全票PASS取非空准入票；verdict按canonical conclusions：无Critical/Major为PASS，有Major无Critical为PASS_WITH_WARNINGS，有Critical为FAIL，drift_terminated覆盖FAIL，仍不等于converged。

- genesis初态由空已验证事件序列导出：charged=0/count=0/pending_refocus=false，无已消费人工动作；initial_max_rounds来自当时固定源。有效额度=initial+已验证且未重放increase_rounds数×2，当前config改大不增加额度（同build内先E_SOURCE_DRIFT）。remaining=max(0,limit-charged)。
- manifest.round=charged_before+1；attempt_index是reserve计数+1。void照常commit为错误报告/无效票结果，charged/count/pending/stability基线/normal序列均原样保留；不得耗额度、满足refocus义务、制造空集稳定或删除attempt证据。下一次重试用新client_round_id；若资源unknown仍先暂停。
- 非void charged+=1，is_refocus取执行前pending_refocus；执行完成该义务后再按本轮drift：真实触发refocus则count+=1，>=2为TERMINATE；成功分类且未触发refocus（含WARN/空集ratio=0）count=0；真实checker skipped、first_round、configured_off、observed_missing_anchor均保留count，不把缺观察当normal已证明。pending_refocus在非void执行后按本轮实际REFOCUS_ROUND返回置位，其余非终局清除；void不清除。skipped不增加也不清零count。
- stability用紧邻有效轮，refocus有效输出照常替换基线；normal振荡序列仅含非void且is_refocus=false的有效轮。normal序列有3项时用最后三项完整keys判N=N-2且N!=N-1，当前refocus轮不作振荡触发。
- first_round只跳比较/drift，不跳额度；有效R1且limit=1必须MAX_ROUNDS_EXHAUSTED。既有终局链保持CONVERGED→DRIFT_TERMINATED→OSCILLATION→MAX_ROUNDS_EXHAUSTED，REFOCUS为独立非终局且首次触发撞额度也耗尽；WARN覆盖unanimous_pass=false。REFOCUS/TERMINATE属既有policy阻断，先令converged=false，不因population相同绕过。void不触发新终局。配置关闭路径仍完整legacy，不拿它兜底新路径错误。

### 10.7 canonical_v1 唯一规范化

仅收本轮completed_admitted报告findings，按manifest role_index/finding_index遍历，不并prior_findings/prior_id/迟到独立事实。type/category/scope用§8已解析的原字符串，不trim/casefold/Unicode/path归一化；`a.py`与`./a.py`不同。精确(category,scope)建bucket，severity固定minor<major<critical，取整个bucket最高级。每个实际出现的type各产一条conclusion，severity用bucket最高级；found_by仅含提供该type的真实角色并按manifest顺序去重，不凭跨type提升severity而添加虚假来源。

每条conclusion精确为 `{id,type,severity,category,scope,summary,found_by,variants,conflict_state}`。variants仅收该type的完整原finding（含保留的额外字段），以完整C(finding)字节相等才合并，每项 `{finding:<原object>,members:[{role_id,role_index,finding_index,raw_ref:NativeRef}]}`；variant按C字节排序，members按(role_index,finding_index)排序，所有conclusion的members总数必须等于准入findings总数。不同claim/不同type的原观点均留在variants/独立conclusion，不按scope只取一条，不用hash当相等。

整个bucket不同完整variant多于1时，该bucket各conclusion均 `conflict_state="unresolved_variants"`，否则 `"none"`；这是保守差异保留，不是机械识别语义矛盾，不新增收敛否决门。若MD显示conflicted，仅为该状态的展示投影，不宣称已证明矛盾。summary取本type最早(role_index,finding_index)的summary字符串，否则该finding.failure_scenario，以Python str.split()前50项用ASCII空格连接；只展示不参与身份。id为UTF-8的`category+":"+scope+":"+severity+":"+type`的SHA-256前8位，仅展示。conclusions按完整(type,severity,category,scope)的Unicode code-point tuple排序，comparison_keys按完整tuple去重排序；短id碰撞保留双方。drift分母为conclusions长度，quality由提升后的severity计算；这些是本修订的显式确定性选择，不声称与所有旧散文解释自动等价。

### 10.8 可构造正常链与四组指定坏态

正常链（所有名为Ref的值都在被引用前写成真实文件并算完整hash，不用本文占位值当fixture）：独立目标S无旧周期，准备固定config/defaults/源与context/Span，manifest M1取round=1、attempt_index=1、cycle_origin=null、previous=null，三个未来locator不存在。build锁内来源扫描→genesis G→script W1→reserve E1→build-record B1；实际Workflow返回A1（配置三席，前两席有效PASS零findings，第三席完成但raw=null，均有done/C且窗内）→capture index I1→prepare request Q1（first_round）→final result J1/MD→commit E2→只读check→消费。J1 incomplete=true、converged=false，charged=1；没有任何未来hash依赖。M2引用G/J1，round=2、attempt_index=2，新client id；同准入两席及相同空keys，完成真实Workflow A2→I2→prepare Q2（empty_conclusions、ratio=0，无checker）→J2→commit→check，得到population=same_population、stable=true、converged=true。非空结论分支则Q2 required=true→真实独立checker→drift index→final；不能跳过该调用。若两有效轮之间插入全失败void，attempt_index变1/2/3、round为1/2/2、previous仍J1、charged为1/1/2，最后一次仍可收敛。

| 坏态组（独立QA需另造fixture/坏实现） | 指定拒绝/断言 |
|---|---|
| bootstrap/额度：运行前要求未来hash、自引用genesis；已有scope传null/换cycle/回退head；擅改config增轮；无合法事件却在耗尽/终局/接受或降级后新build | 分别E_HISTORY_CYCLE或E_POLICY_SOURCE；E_PREVIOUS_IDENTITY；E_SOURCE_DRIFT；E_POLICY_BLOCKED，不重置额度、不先reserve后拒绝 |
| policy/终态：缺真实anchor/checker/问答源、伪skipped；JSONL串agent/损坏；完全无终态引用；partial返回off_topic；preflight改写已知startedAt | E_POLICY_SOURCE；E_NATIVE_EVIDENCE；无引用保持unknown并令next_dispatch=false/E_RESOURCE_PENDING；partial分类E_POLICY_SOURCE；时间改写E_NATIVE_TIME，不借false/legacy放行 |
| 历史：已合法载入的R3节点递归回到当前visiting origin（R3→R3或R3→R2→R3，回边hash可故意不符）、缺R2叶子/跳有效轮、篡改admitted/converged/count | 回边按§10.6先判E_HISTORY_CYCLE，不要求自hash固定点；非回边缺/损坏叶子E_POLICY_SOURCE、跳轮E_PREVIOUS_IDENTITY；派生值篡改E_RESULT_MISMATCH；void耗额度/替换基线或skipped清零的坏实现必须使折叠断言红 |
| 规范化：同scope不同claim/type含Critical与Minor、完整keys短id碰撞 | 保留全部members/variants/type，bucket最高Critical及不同完整keys；吞成员/归一化scope/按短id合并的坏实现必须使守恒、keys与verdict断言红 |

同四组坏态配套的三项成对向量（均为待实现的合成fixture要求，不是产品测试结果）：

1. **额度/终局正负对**：initial_max_rounds=1，R1有效提交且所有调用有终态，charged=1、remaining=0、terminal_state=MAX_ROUNDS_EXHAUSTED。同genesis/previous=R1、round=2、attempt_index=2的新manifest在没有合法increase_rounds事件时build必须E_POLICY_BLOCKED，事件head不新增reserve、无新script或调用；只检轮号/资源的坏实现须在此断言红。独立副本按§10.5取得绑定该head的合法increase_rounds后，limit=3、remaining=2，同类新build可通过政策前置，仍逐项检查资源/身份；重复处置不再加2。另在独立合法前史上构造CONVERGED/DRIFT_TERMINATED/OSCILLATION（即使有剩余额度）以及accept_current/degrade_single的view，均不得再reserve；不要将耗尽的加轮例外推广到这些状态。pending的原reservation重入只能resume_only、事件head不新增reserve且不派发；同轮换client也不能挤过pending。remaining>0的void重试或REFOCUS_ROUND允许新attempt，但void不完成refocus义务；既有正常链和最终collect/check/补commit恢复不受新派发闸门误拦。
2. **单调终态正负对**：旧调用T0=0、q=100、startedAt=null、C=null、raw=null、termination=unknown。真实同run/script/节点的较晚done给出startedAt=150、durationMs=20、C=170时，preflight可追加observe并解除该调用的资源unknown，旧结果仍保留原null时间/raw、no_completion及原票。另取已知startedAt=150但尚无C的旧观察，新done改为startedAt=151（即使q<=151<=C=170）必须E_NATIVE_TIME；若150来自前次observe也同样拒绝，不能只比最早null。null补成早于q、boolean或done缺duration亦拒绝。只补150但仍未完成且无中断引用则继续E_RESOURCE_PENDING；合法中断引用只能令termination=interrupted_observed且C=null。身份/q/script任一改写拒绝；以上资源解除均不绕过上一项政策闸门、不补旧raw或准入票。
3. **partial-anchor正负对**：冻结present锚的primary_goal非空、两scope数组均空，R2有非空conclusions且原request判required=true。固定脚本指令要求逐完整key只返回on_topic/adjacent；完整合法分类必须得到off_topic=0、ratio=0以及宿主推导的anchor_scope_empty=true/confidence="low"，不能因scope空而跳checker。动作仍按原阈值算（原阈值>0时NONE，阈值恰0仍依原>=），不新设阈值。仅把其中一项换为off_topic、即使keys完整也必须E_POLICY_SOURCE，不得直接进入REFOCUS/TERMINATE或改报skipped；去掉固定指令或伪造标注亦须校验失败。成对完整scope锚允许合法off_topic并照原比例分类，missing锚仍按已有reason优先级处理；first_round/空结论/配置关闭及真实checker失败各走原分支，不用partial标注替代调用或失败证据。

## 11. 精确拒绝与非通过结果表

错误码为当前 CLI 的 machine token。所有错误均非零、不覆盖成功结果；指定的非通过计算结果可exit0，但不能表示审计通过。

| 条件 | 指定结果 |
|---|---|
| 参数缺失、check/output不一致、prepare与check同时出现 | exit2 / `E_ARGUMENTS` |
| scope写锁占用或check期间head变化 | `E_SCOPE_BUSY`，不抢锁、不接受混合视图 |
| 新script/reserve前remaining_rounds=0，或终局/处置禁止继续；耗尽且无绑定该head的合法increase_rounds重开 | `E_POLICY_BLOCKED`，不生成新script/reserve、不派发；同reservation精确恢复仅resume_only |
| 新派发所需资源仍unknown/无可用槽 | `E_RESOURCE_PENDING`，不制造checker失败 |
| 历史依赖visiting再入/自引用 | `E_HISTORY_CYCLE`，不截断为first_round |
| 非法JSON、重复key、非有限数字、manifest字段类型错 | `E_INPUT_SCHEMA` |
| 原始guard为string/number/null/array/object | `E_CONFIG_TYPE`，不回落false |
| 固定源缺失、DEFAULTS未注册新键的新路径 | `E_CONFIG_SOURCE` |
| manifest guard/角色/固定预算与源不符 | `E_MANIFEST_MISMATCH` |
| true下非Workflow/非convergence、人工团队/model覆载、无显式团队 | `E_UNSUPPORTED` |
| build后config/defaults/code/contract字节改变 | `E_SOURCE_DRIFT`，包括check模式；§13只有独立验证的精确来源转换，不允许普通路径任意漂移 |
| 主build/checker发布的最终JS大于524288 bytes | `E_WORKFLOW_CAPACITY`；主build在锁/任何scope或run写入前拒绝，checker不承诺整次prepare零写入（§5.4） |
| 首轮恢复证据、authority、来源/事务或首续接handoff不合法 | §13.7的精确错误/原因；不生成审计PASS、void或新预算 |
| run_id不匹配、内嵌script hash错、args/冻结身份错 | `E_RUN_IDENTITY` |
| 原生记录缺失/截断/非完整返回/节点数或快照映射矛盾 | `E_NATIVE_EVIDENCE` |
| 不识别的原生schema/state | `E_NATIVE_SCHEMA`，不猜完成 |
| 非整数时间、负duration、q/start/C先后矛盾、done缺完成字段；preflight改写/清空此前已知startedAt/durationMs/C或改变q/startTime | `E_NATIVE_TIME` |
| 真实未终结调用并发超过2，或超时后无终态就释放槽派下一席 | `E_CONCURRENCY` |
| round>1缺前轮 | `E_PREVIOUS_REQUIRED` |
| 重复role/agent/label、串cycle/change/checkpoint、轮号不相邻、前轮损坏 | `E_PREVIOUS_IDENTITY`或当前原生对应的`E_NATIVE_EVIDENCE`；不重置基线 |
| 首轮无前轮 | population=false/first_round，keys_equal=false，stable=false，converged=false |
| 旧报告无可验证实际参与证据 | population=false/missing_participant_evidence，不能作相等或稳定证据，不倒写历史 |
| 空准入集合 | population=false/empty_population；本轮空集时all_failed_void=true/unanimous_pass=false/converged=false |
| 相同keys但不同角色集合 | 开启：population=false/population_changed，stable=false/converged=false；关闭向量按legacy |
| raw null/格式错/REVISE | 分别no_result/parse_error/有效准入REVISE；不能变成缺席PASS |
| C已知且晚到，包括C=D及raw=null | completed_late，保留C/可用raw引用，不入票 |
| attempted调用终态unknown | next_round_dispatch_allowed=false，暂停新派发；不篡改本轮已有效票 |
| policy/原轮数/历史重算缺来源或来源hash不符；partial checker返回off_topic或生成脚本缺固定分类指令 | `E_POLICY_SOURCE`；不填放行boolean，不将不合规partial分类推进为漂移动作 |
| --check-result的任一身份/hash/时间/状态/集合/keys/policy/收敛boolean不符（含两项anchor派生标注） | `E_RESULT_MISMATCH`；JSON/MD/raw均不写 |
| 写模式目标逃出允许目录，或已有文件不同于同reservation/同冻结输入的重算字节，或不满足§10.3窄恢复条件 | `E_OUTPUT_CONFLICT`；保留既有文件；§10.3严格相符时仅幂等返回或补缺文件/commit，不重派、不覆盖；check-result仍全程只读 |

## 12. fixture 与消费者边界

- 历史R2–R5只作为portable离线输入，保留源hash及原始缺字段事实。不得给历史原件伪造build-record、attempted快照、cycle身份、政策生产者或“已通过新check”的记录。fixture适配器需明确标为历史数据适配，不能成为生产强校验的宽松fallback。
- 适配器可从原件节点还原历史派发/时间、从旧result中的实际report/rawUnadmitted检查格式；不能声称旧admitted报告原始string仍存在，或把JSON重新序列化当原raw字节。R2独立事实通道不得冒充准入票。
- SC-5/6负例可直接从§6–11派生；timer偏移20ms的合成fixture应允许观察D后派发，但必须拒票；不得让fixture自行宣称原生硬截止或假造完成C。
- 消费者必须先重算校验，然后读取**同一run-key** JSON的admitted集合、stability/converged与配套MD；不是检查文件存在、grep `PASS` 或信任AI手填frontmatter。篡改参与集合/converged/policy须被重算拒绝。
- frontmatter继续用 `checkpoint/mode/rounds/context/agents/verdict` 和既有drift/override字段；`agents`仍是配置说明，参与信息只additive，不拿它作实际集合。未知policy字段不得为了渲染套模板而填false。
- `audit-executor-minimal-repair` 的 TASK-013 离线验收记录属于旧修复证据，不能充作 `audit-executor-pre-dispatch-recovery` 同号任务的验收。测试日志和固定观察下的实际 AI 决策不等于真实产品 Workflow 接线；真实调用、Rule #6 与 SC-10 仍按各变更自身证据独立核验，不因本次文档同步而完成。

## 13. 派发前容量拒绝的受限程序扩展

本节依据 `audit-executor-pre-dispatch-recovery` 的 proposal 与 design §2–§6.1，对应当前 `audit_executor.py` 的实际函数；只定义程序输入、产物、重算与拒绝条件。它不新增 AI 临场选择/恢复步骤，不表示 SKILL.md、description 或旧 Skill 已自动接入此 CLI，不是审计放行或真实恢复完成声明。以下 schema 为封闭键集；`FileRef`、完整原字节 SHA、整数排除 boolean、未知键拒绝仍按§2。示例类型是抽象占位，不是真实记录。

### 13.1 适用对象、CLI 输出与非目标

`recover_dispatch_rejection` 只接受同 scope 的原 genesis + 唯一 seq1 首 reserve（`attempt_index=1, round=1`），无 commit、observe、disposition 或其它事件；旧 manifest/build-record/script/input_closure、原六源、固定预算及 head 共同绑定。只支持 `cause="workflow_input_file_too_large"`，不是通用取消、未知活性清理、任意旧版迁移、后续轮或 checker 恢复。

§3列出实际 argparse 参数；`--native-record` 在本命令中指完整 root session JSONL，不是 collect 的 Workflow export JSON。没有 runId 参数，因为通过本入口验证的是派发前精确拒绝，不伪造 native run。返回对象恰为 `{eligible:boolean,would_append:boolean,event:FileRef|null}`：

| 调用/已验证状态 | `eligible` | `would_append` | `event` |
|---|---|---|---|
| 首次 `--check-only` | true | true | null |
| 已有同一 seq2 的 `--check-only` | true | false | null |
| 首次 mutation 成功 | true | true | 新 seq2 FileRef |
| 当前 head 仍为同一 seq2、完全同输入的 mutation 重入 | true | false | 既有 seq2 FileRef |

不符合条件抛错误，不返回 `eligible=false` 作为替代终态。check-only 使用同一证据判定，但不取得写锁、不建目录、不冻结、不生成实际 event FileRef；不能据其输出推定后来的 head 仍有效。mutation 在原 scope writer.lock 内重新执行验证并比较 TargetBinding，只有 seq2 event 的原子不覆盖发布是提交点；blobs 可先封存，未提交时旧 pending 不变。此命令本身不调用 Workflow、不创建 successor build。

### 13.2 原生容量拒绝与本机静态依据

`_parse_recovery_rejection` 独立验证原拒绝。原生 namespace 为宿主启动环境非空 `CLAUDE_CONFIG_DIR` 或 `Path.home()/".claude"` 下 `projects/<project>/<session_id>.jsonl`；CLI 无可信根覆盖。绝对规范路径、非 symlink、repo 外原件、完整且以 LF 结束的稳定 UTF-8 JSONL 都必需。选定 root assistant/user 的 cwd 必须等于 repo、sessionId 等于 filename 身份、`isSidechain is False`、`isMeta` 缺省或为 false；同名 API envelope 不是原件 authority。原行 hash 对去掉行分隔 LF 的原 bytes 计算，不重排 JSON，行内 CR 不被抹掉。

选定工具对必须唯一且 request 先于 response；UUID 唯一、`parentUuid=sourceToolAssistantUUID=request.uuid`、tool_use_id 完整相等，timestamp 有 timezone 且不倒序。工具名严格 `Workflow`，input 恰为 `{scriptPath:<旧绝对script路径>,args:{identity:<六字段>,manifest_sha256:<旧manifest SHA>}}`；script 原字节/hash及旧冻结绑定一致，实际 script 必须大于 L。response 的 `is_error is True`，content 恰为 `<tool_use_error>Workflow script file <该scriptPath> exceeds 524288 bytes</tool_use_error>`；若存在非 null `toolUseResult`，它只能等于对应 `Error: Workflow script file <该scriptPath> exceeds 524288 bytes` 字符串。timeout、network、quoted error、substring 命中都不是此分支。

选定结构里的 runId/taskId/native run/启动成功等信号、另一关联请求、重复/未配对请求或其它关联结构都拒绝。选定行的其它 blocks 仍被检查；仅移除该精确 tool block 及已验证同值的 wire 表示，不豁免整行。`wireToolInputs[tool_use_id]` 若存在必须与完整 input 逐值一致；其它行的相关 wire、未知 role 中的相关结构不能被当成普通 prose 忽略。API 请求副本不提供额外 authority，也不代替 root 对；无关结构不被误当本次运行。

当前 `_RUNTIME_REJECTION_PROFILES` 仅识别 `native_version="2.1.318"`。request/response version 同值并命中该固定 profile；其 capacity/loader 静态来源的 `kind` 分别为 `static_distribution_bytes_not_executed`、`static_only_no_private_module_execution`，binary SHA、三个固定半开窗口的 start/end/hash、实际 text 或 bytes_hex 必须匹配代码 profile。验证的是 loader 容量拒绝→resolver 传播→Tool call 创建 run 之前抛错的已取证本机静态路径，不执行私有模块。分发契约不携带原生全文、个人 locator、静态窗口原文或 ELF 内容。

这些静态字节、当前 PID/版本都**不证明历史执行映像身份相同**。历史映像未独立验证的残余不确定只能由§13.3的第二项独立、单对象政策接受；不生成 capacity_certificate、全历史不可执行证书、全平台 fencing 或未来裸 Workflow 隔离保证。无 runId、空搜索、本地超限 stat、单份 transcript 均不是全称无运行证明。

### 13.3 两项独立真人 authority 与 TargetBinding

生产入口分别为 `_parse_operator_recovery_statement`、`_parse_evidence_acceptance`，共用封闭验证核 `_parse_recovery_authority`，不调用或放宽§10.5耗尽处置 parser。两项均必需，分别派生不同语义；一个 index 或相同文字副本不能替代另一个。两项可以共享同一 root snapshot，但必须各自验证真实 question/response。

```text
AuthorityIndex = {schema_version:1, adapter:<本角色固定token>, target:FileRef,
  question:{path:string,line:integer>=1,uuid:Id,line_sha256:Hash},
  response:{path:string,line:integer>=1,uuid:Id,line_sha256:Hash}, tool_use_id:Id}
TargetBinding = {identity:<六字段>,attempt_index:1,genesis:FileRef,
  reservation:FileRef,head:FileRef,manifest:FileRef,script:FileRef}
NativeSource = {original_locator:string,runtime_config_root:string,snapshot:FileRef}
Authority = {schema_version:1,sourceData:{adapter,decision,counterevidence_policy:"veto",
  target:TargetBinding,target_locator:FileRef,source:NativeSource,
  question:{uuid:Id,line:integer>=1,line_sha256:Hash},
  response:{uuid:Id,line:integer>=1,line_sha256:Hash},tool_use_id:Id,
  <下表本角色独有的字段>}}
```

| 角色/固定 adapter | 唯一肯定输出与独有字段 |
|---|---|
| OperatorStatement / `operator_boundary_20261109_v1` | `decision="confirm_local_domain"`；`authorization_domain="root_session_and_explicit_delegations"`，`transfer_state="not_authorized_or_transferred"`，`recovery_scope="local_interactive_legacy_recovery"` |
| EvidenceAcceptance / `historical_evidence_acceptance_20261109_v1` | `decision="accept_boundary"`；`policy="accept_native_capacity_rejection_with_local_static_basis_and_prior_exclusive_operator_statement_for_this_target_only"`，`residual_uncertainty="historical_executable_identity_not_independently_verified"` |

这些输出只由宿主从原件派生。拒绝选择不输出肯定 authority：已观察三选项中的“不能确认，保持挂起”/“仍要求全自动全域证明”不变为 confirm；两选项中的“保留门槛，保持阻塞”不变为 accept。它们不映射成 `accept_current/increase_rounds/degrade_single`，不覆盖成功/未知运行反证。

输入解释的边界如下。

- canonical index 的键精确如上；adapter 按角色固定。兼容 legacy locator 时，operator 从 `exact_target/native_source/native_binding.question/native_binding.answer` 映射，原行 hash 字段为 `raw_line_sha256`；acceptance 从 `target/native_source/question/response` 映射，hash 字段为 `line_sha256`。各自 question 的 tool_use_id 映射到顶层。归一化是输入解析，不是索引声明的授权；原 index/locator 字节被冻结，重放重新做同一解析。不以 `selection/authorizes/approved/no_recovery_executed` 或嵌入摘录推定结果。
- 两个 event.path 必须相同且位于§13.2可信 root namespace；line 必须是非 boolean 正整数，原行 SHA/UUID 精确匹配，root UUID 唯一，cwd/session/isSidechain/parent/sourceToolAssistantUUID/先后与 timestamp 均逐项核验。只有真实 `AskUserQuestion` 与其 tool_result，`is_error` 缺省或为 false 才可继续；API envelope、sidechain、普通同文 user 记录不是回答。选定 question 行恰一个 AskUserQuestion；目标 tool id 的重复/错误 role/wire 关联也拒绝，不把其它无关工具 block 一律视为冲突。
- `_recovery_authority_questions` 固化两份已观察 UI 的完整 question/header、三选项或两选项 label/description/preview；仅 preview 的 change_id、checkpoint、reservation SHA、script SHA 由实际目标填充。`multiSelect=false` 必须为 boolean。`toolUseResult` 键恰为 questions/answers/annotations；questions 与 request 逐值相同，answers 恰以该题为唯一键且选中唯一肯定 option，annotations 恰为该题的 `{preview:<选中option原preview>}`。caller 不能自选模板；合法非空 annotations 不套用旧耗尽 parser 的空 annotations 条件。
- TargetBinding 从真实 manifest/genesis/reserve/script 的五个 FileRef 重新核验。首 reserve 的 seq/attempt/round 均为整数1、previous_event/previous_round/previous_attempt 均为 null，完整六项 identity 相符，`head=reservation`，scope/cycle/manifest/script 及原预算来源一致。target locator 的 identity、genesis/reservation/current_head/script、script_bytes、initial_max_rounds 与实际对象逐项相等，且其 `known_workflow_tool_call/known_request_uuid/known_response_uuid` 必须在该 authority 的 root 中形成真实、唯一、正确输入的旧 Workflow 对。locator 本身不是签字。
- 这是已观察 UI 的窄 adapter，不是任意超限对象的授权模板：operator 的固定问题明示 570716-byte 历史对象，`_validate_recovery_operator_length` 因而要求该 script 恰 570716 bytes；acceptance 没有额外固定长度断言，但仍绑定同一完整旧对象。仅大于 L 不足以通过两项 authority。

机器核验具体旧状态/已知载体，人类分别提供未另授权/转交的有界历史操作域声明、以及仅此对象的有限证据接受政策。两者不是密码学证明或全平台运行活性证明；能改写可信原生存储和执行器代码的同权限恶意主体仍在既有 TCB 之外。无人值守 AI 不能用生成的声明代替真人原件。

### 13.4 seq2 的封闭 schema、冻结叶子与计数

事件仍为§10.3外壳，`kind="dispatch_rejected",seq=2,previous_event=<seq1完整FileRef>`，genesis 不变。payload 精确如下，source_transition 不可为 null：

```text
payload = {reservation:FileRef,build_record:FileRef,evidence:FileRef,
  input_closure:FileRef,source_transition:SourceTransition}
RecoveryEvidence = {schema_version:1,cause:"workflow_input_file_too_large",
  source:NativeSource,session_id:Id,
  request:{uuid:Id,tool_use_id:Id,line_sha256:Hash,input:<原两字段工具input>},
  response:{uuid:Id,tool_use_id:Id,line_sha256:Hash,error:<精确原生错误串>},
  script:FileRef,runtime_rejection_basis:FileRef,operator_statement:FileRef,
  evidence_acceptance:FileRef,known_binding_sources:[FileRef],additional_sources:[NativeSource]}
RuntimeRejectionBasis = {schema_version:1,binary_sha256:Hash,native_version:"2.1.318",
  capacity_source:FileRef,loader_source:FileRef,
  windows:[{start:integer,end:integer,sha256:Hash}]}
SourceTransition = {compatibility_id:"pre-dispatch-rejection-v1",
  compatibility_manifest:FileRef,from_sources:<六源FileRef map>,
  to_sources:<六源FileRef map>,new_source_closure:FileRef}
```

`_recovery_publish` 冻结完整原生 snapshot、静态来源实际字节、两个实际 index/locator、target、派生 authority/basis/evidence 及所有实读叶子；NativeSource 的 snapshot 换为不可变 blob FileRef，original_locator/runtime_config_root 仍保留来源身份。`known_binding_sources` 是本次实际实读来源的完整 FileRef 排序去重列表，不是 caller 自填“已检查”；不含其后生成的观察/派生记录。`additional_sources` 仅列显式传入的其它 root 的 NativeSource，递归发现的必读载体仍进入实际闭包，不因此遗漏。

此处没有独立序列化或另给 FileRef 的归一化 `AuthorityIndex` 文件。§13.3 归一化的承重信息由冻结原 index/locator 与派生 authority 的 `sourceData` 共同保全：例如 `adapter`、`target_locator`、`question/response`、`tool_use_id`；`authority_indexes` 的角色 FileRef 指向原 index/locator，而非另一个 canonical 产物。冻结重放从这些角色引用重新归一化、重派生 authority 并比较，不只信任派生摘要。

独立观察记录的逻辑 origin 固定为 `SCOPE/recovery-read-observations.json`，其字节由 closure 冻结，不要求把该 origin 当 live 文件发布：

```text
RecoveryReadObservations = {schema_version:1,unreadable_scripts:[string],
  authority_indexes:{operator_statement:FileRef,evidence_acceptance:FileRef}}
```

`authority_indexes` 保存**实际通过验证的两个 CLI index 参数**的角色→FileRef provenance，不能按文件名、候选顺序、JSON 形状或含 adapter 字样猜角色。`unreadable_scripts` 是关联核尝试读取绝对 scriptPath 候选得到不可读时的规范化、排序唯一观察，不是 root/声明缺失的豁免，也不是“没有运行”布尔。冻结重放使用 `_RecoveryFrozenInputs` 的记录观察，不从当前磁盘猜当时可读性。

`_verify_recovery_event` 用 `new_source_closure` 的 `_TrackedFrozenInputs` 和共享读取追踪重新派生拒绝、两项 authority 与全部递归来源；两角色 index 必须分别解引用并调用正确 parser。它验证新验证包与外层 input_closure 的每一实读 origin 字节一致、原对象绑定一致，重推 `expected_known`（排除该宿主观察 origin）恰等于 known_binding_sources，并要求验证包每个输入均实际消费。删来源、加未消费来源、伪标记/错角色、错 hash、跨 capture 替换，不能凭摘要相等通过。静态来源、原生 snapshots、authority target/index 及传递叶子都须实际取得冻结字节。

| 量 | seq1 reserve后 | seq2 rejection后 | seq3 successor reserve后 |
|---|---:|---:|---:|
| reserve_count | 1 | 1 | 2 |
| committed audit attempts / charged_rounds | 0 / 0 | 0 / 0 | 0 / 0 |
| effective_limit / remaining_rounds | 原初值 / 原初值 | 不变 | 不变 |
| pending | seq1 | null | seq3 |
| latest有效round / latest committed attempt | null / null | null / null | null / null |

rejection 不产生 audit row、票、结论、PASS/FAIL、void 或资源终态，不授予取消/扩预算权。`previous_round` 仍指最近非 void 结果，`previous_attempt` 仍指最近 commit，不改指 rejection；本首续接两者均 null。下个新 manifest 使用新 client/run-dir、原 checkpoint/change_id/audit_cycle_id/cycle_origin，`attempt_index=2,round=1`；candidate 仍按普通当前候选规则，不回写旧对象。程序仍执行原资源与 `_require_dispatch_policy` 门，不以 seq2 自动发放 Workflow 许可。

### 13.5 固定兼容 catalog 与双 source generation

catalog 固定为当前插件 `references/pre-dispatch-recovery-compat.json`，由 executor 自身路径定位，无 CLI/config 覆盖。封闭 schema 为 `{schema_version:1,compatibility_id:"pre-dispatch-rejection-v1",from:{executor:Hash,contract:Hash},to:{executor:Hash,contract:Hash}}`。`_recovery_compatibility_manifest` 只计算机械期望值，不写 catalog，也没有同名 CLI 子命令。from 固定为旧发布 executor `5b9a32e23d665e494a21dc002a1a8498db445462762fba52916ce79716333777` 与 contract `27e145e159e5b828e2c60d9a743ca8a0ea59bfb11560ce4f1e8783e2ed711920`；to 必须匹配当前实际两文件原字节。未知/缺键/多键、stale、未知旧对、from 整对等于 to 都拒绝；不要求两分量各自都变化。

`_recovery_source_generations` 对两个 reader 分别验证：

- `from_sources` 恰为旧 build-record.sources 的六个**逻辑来源** FileRef：`config/defaults/executor/contract/convergence_algorithm/report_storage`，每一逻辑路径都必须等于 `_fixed_paths`，不是只比 SHA 或任意同字节副本。旧 executor/contract SHA 配 from；原 input_closure 取得每一 origin 的旧 bytes。
- genesis.initial_sources 的 FileRef 是 `SCOPE/blobs/<sha256>.blob` 存储地址，不要求它等于逻辑来源路径；逐个验证原闭包来源 bytes/hash与对应 genesis blob 完全一致。旧 build/policy/roles/budgets/graph 经私有旧代 `_FrozenInputs` 调用 `_native_build` 完整验证；不执行旧代码。
- `to_sources` 为本命令从固定路径实际读取的六源；config/defaults/convergence_algorithm/report_storage **完整 FileRef** 前后相等，executor/contract SHA 配 to，旧/新 guard 都为 true。catalog、当前六源和实际验证输入被冻结进 new_source_closure。原 genesis、初始预算、anchor、policy_inputs、旧 reserve/build/script/closure 不改。

两个闭包分时读取同一逻辑路径，允许经此精确转换有不同 SHA，不把旧/新 reader 扁平合并。`_verify_recovery_event` 先分别验证旧包和新包，再导出 active sources；后续闭包保留旧物理 blob 与新的逻辑来源，不拿当前源码读旧 initial_sources，也不跳 source gate。`_load_scope/_prefix_active_sources/build/_verify_pending_graph/_native_build/_HistoryGraph/_replay_history` 只消费已验证转换；普通未恢复 scope 仍绑定 initial_sources。v1无旧审计 commit，不支持把旧版本已投票结果跨版本混算。

### 13.6 已知来源、关联反证与有限扫描

`_recovery_validate` 的来源起点包含原拒绝 root、operator root、acceptance root、显式 additional_sources，及旧准备物/闭包、现存 post-run index/preflight 的结构化 locator。`_recovery_native_links` 继续读取其中明确引用的 native_source/original_locator、SessionEventRef、JsonlRef、native_record 及其递归载体，不把 JSON-looking prose 当结构化链接。不扫描无已知线索的全平台会话、不猜远端 API；来源集合的完整性不能由 caller 的自报布尔证明。

首次 `_recovery_validate` 在闭包扫描前经 `_recovery_native_root_bytes` 取得 primary root：先验证 namespace/非 symlink，再按 native_root 角色稳定读取。缺失或不可读的 primary 报 `native_source_unreadable`，不把另一 authority locator 中的原选定拒绝先误判为额外运行。该前检只取得原字节，不扩大精确 tool block 排除范围；完整原拒绝/静态依据验证、metadata/root fixedpoint 及晚读依据后的再次 drain 保留。

首次验证、冻结事件重算、handoff bindings 与 committed rescan 的通用载体识别共用 `_recovery_carrier_links`：按实际完整 bytes 能否解析成 JSON object/list 枚举，不由 `.json`、大小写、其它后缀或无后缀决定；carrier 保持闭包记录的逻辑 origin，不替换为物理 blob 地址，carrier-relative FileRef 基准不变。通用解析仍只在 `json.loads` 阶段保留原 `ValueError/UnicodeError` opaque 边界；JSON-looking 正文、Markdown fenced JSON、顶层 JSON string 不递归解释，后续读取/明确 native 引用/typed 校验错误不转成 opaque。committed rescan 读取完整 known sources 路径集合；实际 manifest index 与 authority 参数路径仍严格解析，普通源码/文档不因此变成严格 JSON。root Session JSONL 的 `.jsonl` namespace 约束不变。

recovery 的种子来自 `_RecoveryReadTrace` 在成功语义读取后记录的 `(view,logical_origin,bytes,role)`，不来自 `raw` 成员资格或 `known_binding_sources`。old/current/handoff 各有独立视图；原代 `_native_build` 内部的 frozen reader 与其 pending graph 共享同代 trace。默认 logical binding 经 `_recovery_carrier_links`；root/typed JSONL 保留逐行 parser 与 API-envelope 排除，storage 解包、宿主 control 与稳定性 recheck 不成为 generic 种子。角色由内部调用点限定，物理 blob 名称不决定逻辑输入资格；原 logical origin 保留相对引用基准。

`_RecoveryBindingClosure` 交替耗尽实际 binding 事件与 root 队列，复用原 native/typed 关系核及其 `seen/target_context`；静态依据和 authority role refs 读取后再次 drain。`_recovery_frozen_bindings` 由冻结事件消费者与 handoff baseline 共用，只消费已验证封存映射，不递归执行发布或读取 live 原件。baseline 的 roots、非 root 固定绑定及角色由实际重建读取导出；handoff/committed rescan 按这些角色取得当前字节并追读新链接，新增反证优先于普通输入变化。committed rescan 中已被实际 typed parser 拒绝的当前 carrier 保留原错误，不再按 generic union 重解释；其它有效 metadata/roots 仍继续扫描反证，错误未消除不能成功返回。known/精确消费比较在 fixedpoint 后执行，publish/recheck 不以复读补齐未消费 cache，seq2 仍为唯一恢复提交点。本段仅描述内部实现，不增加持久字段、外部协议或 AI 调度指令。

通用结构化归档/native carrier 的 `native_record` 为缺键或 null 时没有此链接；dict 仍是精确 `{path,sha256}` FileRef（保留 carrier-relative path 与原 expected digest）。旧式 string 的字段语义是 Workflow export locator，仅接受规范 Linux 绝对路径：单前导 `/`、无 U+0000–U+001F/U+007F，且原串等于 `str(Path(os.path.abspath(s)))`，无后缀约束。live string acquisition 拒绝本体/祖先 symlink；Frozen 只读捕获 origin 映射并追踪 `read_origins`，缺映射无 live fallback。audit index、workflow drift index、preflight observation、result inputs 等实际 typed 位置仍是 FileRef；首次恢复及 committed rescan 共用绑定 index/preflight 的类型检查，tool_error 的显式 null 分支不变。

string 与 FileRef acquisition 后共用严格 JSON/object、非空 `runId:string`、`args:object`、`script:string`、外层 runId 一致性、关联反证、termination 和递归验证。宿主稳定实读的 string export/递归叶子进入现有 known sources 与闭包；该 hash 是本次内容绑定，不是历史真实性签名。首次后继 handoff 从 seq2 冻结实读重建非 root export digest 并接入 live/Frozen reader，保持既有 bytes 精确绑定；root 仍保留 snapshot 前缀及完整当前载体扫描，不固定其整体旧 hash。最终 reserve 前复读覆盖所有实际捕获叶子；pending resume 仍只消费冻结视图。

`_recovery_associated` 对完整载体检查选定 tool id（含 wire map、toolUseID 等结构字段）、旧 script 逻辑路径、可读候选/内嵌 script 的完整 SHA、manifest SHA、旧完整 identity 或同 audit_cycle_id。关联不要求另一次调用具有合法 build 资格；不同脚本但同 cycle 的成功/未知调用同样否决。只有原选定精确拒绝 tool block 可排除，不能排除整条 assistant 行；其它相关 system/progress/未知 role 结构也不能被静默略过。API replay envelopes 不作真人 authority 或额外运行反证；无关消息/无关运行不导致恒红。

必读 root/引用缺失、截断、不可读、不能归属、native runId矛盾、locator 环、typed interruption 的行/agent/uuid/时间错误都拒绝，不能从清单剔除。带 agent_id 的 JsonlRef 经 `_recovery_typed_event/_interruption_body` 验证完整载体，native 的 termination_refs 经既有 `_verify_termination`；SessionEventRef 不被错误套用 agent namespace。关联 native run/已存在审计 index 是反证或结构拒绝，不以“尚无新 runId”“没有完成”解锁。已有 authority 不能 override 这些条件。

### 13.7 事务、幂等、stale 与精确拒绝

首 mutation 在锁内复核唯一当前首 reserve/head，再冻结输入；`_recovery_publish` 在 seq2 发布前调用同一 `_verify_recovery_event` 离线证明消费者，证明失败最多留 blobs，不提交无法重放的 event。原 genesis/reserve/manifest/script/build-record/blobs不覆写。writer.lock 是本 scope 合作写事务锁，不是全平台派发锁或锁住原生 journal 的 fence。

`_recovery_idempotency_key` 是完整 TargetBinding + 原拒绝 request/response UUID、tool_use_id、原行 SHA + 两项 authority 各自 question/response UUID、行号、原行 SHA、tool_use_id 和 target 的 canonical bytes；不是 journal 整体 hash、日期或活跃 mtime。`_recovery_submission` 在任何已提交重入早返回前，先按旧已证明身份调用 `_recovery_rescan_committed` 重新稳定读取当前已知输入和新 locator，优先检查新增反证，再比较实际角色 index 参数路径、additional 来源集合、key、known origins 及 bytes。

两项 authority/拒绝所在已知 root 可仅追加无关消息，但必须保留旧冻结 snapshot 为当前同 locator 的完整字节前缀且原选定行不变；其它输入必须逐字节不变，已知来源集合也须相同。新增无关来源是 input_changed，不冒充同一输入；新增相关成功/未知调用先反证拒绝，不由“输入已变”掩盖。截断、前缀改写、同字节换 index locator、换签字工具对都不是精确重入。check-only 不替 mutation 预留有效性；输入未变时复用既有签字，不因日期/无关追加要求重签。

只有 head 恰为原同 key seq2 时可幂等确认。head 已到合法 seq3 successor或更后事件，恢复 CLI 报 `E_RECOVERY_EVIDENCE/target_head_changed`，不返回旧 eligible/成功；合法后继历史仍可冻结重放，不能把它倒判成非法重复派发。event 前崩溃可能留孤立 blobs，原 pending 仍在，同输入可复用同内容后提交；event 后丢回执须先完成上述 live 检查才返回既有 event。竞争者只可幂等或拒绝，不追加第二个 rejection。

以下为真实实现 token；不是所有错误都统一包装成 E_RECOVERY_EVIDENCE，原因由实际失败层决定：

| 失败分支 | code / reason（列出已实现的精确 token 或明确前缀） |
|---|---|
| 首前缀/目标 head 已变、锁内目标不一致、合法后继后重用恢复 | `E_RECOVERY_EVIDENCE / target_head_changed`；更早非法事件链也可先 `E_PREVIOUS_IDENTITY` |
| 原生不是容量拒绝、配对/namespace/静态来源不符 | `E_RECOVERY_EVIDENCE`；`native_error/native_pair_binding/native_namespace/native_associated_evidence` 或 `runtime_` 原因前缀 |
| 两项 authority 的来源/对象/UI/选择不符 | `E_RECOVERY_EVIDENCE`；`native_`、`target_`、`operator_`、`evidence_acceptance_` 原因前缀；含 `target_operator_script_bytes` |
| 关联成功/未知/结构化运行反证 | `E_RECOVERY_EVIDENCE / counterevidence_native`，或 `counterevidence_index/counterevidence_typed_event/counterevidence_target_native_record/counterevidence_native_record` |
| catalog/来源不配 | `E_SOURCE_DRIFT / recovery_compat_catalog/recovery_compat_same_generation/recovery_compat_stale/recovery_source_path/recovery_source_changed` 等实际来源分支 |
| 幂等参数、key、根或来源改变 | `E_RECOVERY_EVIDENCE / input_changed_recovery_arguments/input_changed_recovery_key/input_changed_known_roots/input_changed_known_sources/input_changed_source_prefix_or_bytes`；缺损来源可先原 `native_` 等错误 |
| 冻结验证来源集合/角色/capture不符 | `E_POLICY_SOURCE / history_recovery_known_sources_membership/history_recovery_unconsumed_verification_input/history_recovery_authority_roles/history_recovery_cross_capture_binding`，角色 parser 也可直接抛其证据错误 |
| 显式 native/typed引用结构损坏 | 既有 `E_NATIVE_EVIDENCE`（如 `jsonl_line_bounds`）或对应 source/hash错误，不降成空证据 |
| 首续接缺来源输入/发现反证/最终观察变化 | `E_RECOVERY_EVIDENCE / recovery_sources_required/recovery_handoff_counterevidence`；正常live reader发现变化为 `recovery_handoff_source_changed_during_capture`，不稳定/不可读分别为 `recovery_handoff_source_unstable/recovery_handoff_source_unreadable`，已观察不可读脚本变可读为 `recovery_handoff_script_availability_changed` |
| 后继handoff路径/对象/snapshot错配 | `E_RECOVERY_EVIDENCE / recovery_handoff_path/recovery_handoff_binding/recovery_handoff_fixed_prefix_binding/recovery_handoff_snapshot_mapping/recovery_handoff_sources_recomputed`；条件 build 键错由实际消费者报 `build_record_keys` |
| 锁占用、不可覆盖产物冲突、CLI参数不齐 | 既有 `E_SCOPE_BUSY`、`E_OUTPUT_CONFLICT`、exit2/`E_ARGUMENTS` |

错误沿§3输出 stderr JSON `{error_code,reason,input_ref}`，stdout不伪造成功对象；不输出原生正文、prompt 或 secret。反证不撤销/改写已提交 seq2，也不产生“恢复失败已取消”记录，当前重入/首续接保持拒绝。

### 13.8 首次后继 build 的 live handoff

`_first_recovery_successor` 仅在实际前缀恰 `reserve,dispatch_rejected`、pending=null、reserve_count=1，且新 manifest attempt=2/round=1 时成立。此时 `build(...,recovery_sources=PATH)` 必需；普通 `evidence.dispatch_preflight` 必须为 null，不把原 native 终态 preflight 复用成恢复来源索引、不追加 observe。其它 scope不增加该前置。

```text
RecoverySourcesIndex = {schema_version:1,recovery_event:FileRef,
  additional_sources:[string]}
RecoveryHandoff = {schema_version:1,recovery_event:FileRef,prefix_head:FileRef,
  rejected_reservation:FileRef,
  successor:{identity:<六字段>,attempt_index:2,manifest:FileRef,workflow_script:FileRef},
  sources_index:{original_locator:string,snapshot:FileRef},
  sources:[{original_locator:string,runtime_config_root:string,
    baseline_snapshot:FileRef|null,snapshot:FileRef}]}
RecoveryHandoffObservations = {schema_version:1,unreadable_scripts:[string],
  sources:[{original_locator:string,snapshot:FileRef}]}
```

index.additional_sources 为规范化绝对 root locator、排序唯一；只能增加已知来源，不替换 seq2来源，不含 approved/no_conflict/token/timestamp。handoff.prefix_head 与 recovery_event 都必须是本 scope 固定 `events/0000000002.json` 的**完整 FileRef**，rejected_reservation 为固定 seq1，genesis 也须该 scope 固定路径，不能拿同字节另一路径冒充 head。successor 恰绑定这次实际 manifest 原字节、六项identity、attempt2及容量检查过的唯一最终 script bytes，不接受只比较 SHA 或部分身份。

真实生产顺序如下（程序调用链说明，不是新 AI 调度指令）。

1. `build` 容量前检→锁内 `_load_scope/_replay_history` 冻结历史→active source/identity/预算/资源门。相同 pending 的精确 resume 在此独立返回，不进入首续接 live 门。
2. 首续接在新 handoff/script/metadata/closure/reserve 发布前，调用 `_capture_recovery_handoff`。它先用冻结 seq2 重推 baseline，再创建独立、未灌入 view.frozen_raw 的 `_HandoffCaptureInputs` 读取当前 index 与完整已知 root/传递载体；两项 authority root 均纳入，已知来源不得少。旧 root 必须仍有冻结前缀；新相关成功/未知调用报 `recovery_handoff_counterevidence`。不依赖先再次运行 recover，也不重新签字。
3. `_publish_recovery_handoff` 在第一个 freeze/publish 之前再次运行下述独立 live rescan，通过后才把独立 live reader 的所有实际字节冻成 `SCOPE/blobs/<sha256>.blob`，仅按物理 snapshot 路径加入新 build reader，保留 seq2逻辑原路径的旧时间视图。run-dir 不可变发布 `recovery-handoff-observations.json`（全实际输入含 index/脚本候选等）及 `recovery-preflight.json`（上面 RecoveryHandoff）；后者由条件 build-record.recovery_preflight 引用，两者及其叶子进入 attempt2 input_closure。
4. sources按original_locator排序唯一；既有root的baseline_snapshot恰等于seq2冻结snapshot，新发现root才为null。`_verify_recovery_handoff` 从闭包解引用index snapshot与observations全部snapshot，用 `_HandoffFrozenInputs/_handoff_scan` 重推集合/关联、expected sources及实际消费/不可读观察。index和observations的snapshot必须是该scope内容寻址blob的完整FileRef；root snapshot由重推值逐项相等，baseline不能任意清空。**同字节另一路径snapshot也拒绝**（`recovery_handoff_snapshot_mapping`），缺叶子、少来源、多来源、错successor/head不能靠重算hash洗白。
5. 发布已检查script/metadata、冻结input_closure后，`_reserve_build` 对此首续接要求内部 `recovery_preflight/inputs/live` 三项齐全，重算冻结handoff与实际state/manifest/script，再执行既有政策及round/attempt序列门。在reserve排他发布的紧前调用 `_handoff_recheck`，仅接受真实 `_HandoffCaptureInputs`。该复核及capture端复核均绑定已验证的旧root前缀/native hashes，以raw初始为空的新reader重跑同一 `_handoff_scan`，先验证关系，再比较实际消费域、全部bytes与不可读脚本集合；不把新读入内容补进旧proof。清单、任一root/实读来源发生变化即零新reserve；不是仅重读旧snapshot。

共同扫描从已验证旧manifest取得 `post_audit_index_path/post_drift_index_path/post_disposition_index_path` 三个 `(role,path)`，相对路径基于旧record.manifest carrier，每个role独立保留。live每次用 `_recovery_index_present` 实际探测，只有真正缺失的optional index可略过；存在即实际读取并严格复用 `_recovery_index_links`，typed必需叶子不可缺省或generic降级。Frozen只以此handoff已验证origin映射的membership重建存在性，不探现场、不补读。新增反证仍报 `recovery_handoff_counterevidence`，`E_NATIVE_EVIDENCE` typed错误原样传播，不重复handoff前缀。最终复核以瞬态reader记录的错误来源区分新typed index缺陷与捕获漂移：只有非bound-index typed消费器发出的原生hash错，且实际成功重读的origin属于原捕获、字节确已变化，才报既有 `E_RECOVERY_EVIDENCE/recovery_handoff_source_changed_during_capture`；不提前复读expected绕过共同扫描，也不重包新index的坏hash/缺叶子/schema错。无新持久schema或负观察状态。

capture或首发布前复核失败不发布handoff/script/reserve，但不承诺此次普通build没有锁文件。已发布handoff后最终复核失败或reserve前崩溃可留无reservation的不可变准备物/blobs；旧seq1/seq2不改，原 `unreserved_existing_output` 冲突仍成立，不覆盖旧run。首次成功只追加普通seq3 reserve，不捆绑新恢复事件、不改变预算。最终复核是本机有限观察，不锁住原生日志，不承诺观察之后全平台裸调用已被阻止。

### 13.9 条件 record、冻结消费者与 pending resume

`_record` 只给seq2之后的首次后继记录增加 `recovery_preflight:FileRef`；其它记录继续原BUILD_RECORD_KEYS，夹带字段（含null）不合法。`_recovery_build_schema` 从真实prefix内容决定条件，不按该键是否存在决定。`_native_build` 先验证原build闭包，再调用 `_verify_recovery_handoff`，核该handoff在输入reader与冻结包中的同字节关系。恢复闭合的旧首build不成为真实审计运行，live消费它时拒绝 `E_PREVIOUS_IDENTITY/rejected_dispatch_not_a_run`。

`_HistoryGraph` 的 build分支增加recovery_handoff结构边，handoff的event/prefix/reservation/successor/index及baseline/current snapshots均按明确schema走结构边或opaque叶子；`_replay_history` 对seq3调用 `_replay_recovery_reserve`，校验实际reservation、冻结run包与条件record对应，record缺失的崩溃缺口也不放弃handoff验证。prepare/final collect/check通过 `_native_build`、同一graph/history及共享纯重算消费这些字节，不把 live 旧root增长灌回历史，不要求重签或重新读取个人原生存储/静态取证原路径。当前固定源与既有source gate仍保留，缺/坏冻结叶子不是可忽略缺源。

已发布seq3、尚未commit的相同manifest走 `_resume_build`：从固定run-dir的input_closure与recovery-preflight冻结包重算，只返回 `build_record/workflow_script/resume_only:true`，必要时按冻结metadata补同一record；不要求再传recovery-sources、不重做live capture、不新建reserve、不重派。合法attempt2 Workflow本身可以已出现在当前root，不倒灌成seq2时的反证；live原件或来源index移除也不破坏已经冻结的精确resume。不同manifest仍按原pending/source/identity规则拒绝；后续commit/新attempt继续原policy/resource门，不反复触发首续接门。

本节描述代码与字段，不构成真实恢复、产品调用、发版或正式审计终态证据。分发契约不发布私人原件/ledger内容；各项目启用闸门、Rule #6正式逐hunk判定及真实调用证据仍独立验证。
