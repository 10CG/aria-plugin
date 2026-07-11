# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- NOTE: block-flip (warn→block) was DEFERRED at D+14 (2026-06-07) — Trigger C (0 gate
     executions) + tripwire 5/5 dispatch failure → gate ecosystem had no live operational
     evidence. Unblock prerequisite = aria-submodule-gate-operationalize (R-fix-1 shipped
     v1.40.0 below; R-fix-2 tripwire infra pending). See .aria/decisions/2026-06-07-v1.40.0-block-flip.md. -->

## [1.55.4] - 2026-07-11

### Fixed: secret-guard 部件 B 命令位覆盖扩展 + FP 回归修复 (dev-claude spec 部件 B 落地)

采纳 dev-claude L3 spec 部件 B。实现前用 spike 重建正/反例矩阵 (双子星 spike 在其容器, 本机无) + 对抗 FP 扫。

- **FP 回归修复 (v1.55.2 引入的 over-block)**: v1.55.2 的 defect-B fix 把命令位前缀写成 (^|[;&|]|[[:space:]]) — 普通空格被当命令分隔符, 任何以 env 结尾的常见命令被误拦: echo env / kubectl get env / cat env 全部 exit 2。这是我方 v1.55.2/v1.55.3 shipped 的真回归, dev-claude spike 的 FP 矩阵会抓到、我方 ad-hoc 漏掉。修复: 前缀改真命令分隔符 (区分命令位 vs 参数位; 普通空格不再触发)。
- **部件 B 覆盖扩展**: (a) 命令替换 $(env)/反引号; (b) 组合 { env; }; (c) 单层包装器 sudo/nice/timeout/xargs/nohup/stdbuf/doas/env launcher; (d) command env 直接形式 (窄 pattern, 排除 command -v env FP); (e) printenv 始终拦 (printenv KEY 也 dump); (f) env 重定向预存 gap (env > /tmp/leak / nohup env > file, 后缀补 <> 终结符)。
- **env 双重身份保留**: 裸 env / env|grep 拦; env python / /usr/bin/env python3 启动器放行。
- **对抗 FP 扫全放行**: command -v env / python -m venv env / conda activate / git commit -m fix-env-bug / sudo -u env-user / envsubst / printenv_helper / docker run。

> **残留 (fail-safe, 非泄漏)**: 未列包装器 (flock/watch/proxychains 等) + 深层 shell 关键字位仍可能漏拦 —— 按 hook 威胁模型 (防意外泄漏, 非对抗证明) + dev-claude spec AD-3 (包装器残留 fail-safe) 接受, 不声称穷尽。

### 验证
- spike 正/反例矩阵 51/51 (含 code-review R1 的 6 FP + 7 FN 锚点) + 对真 hook 端到端 FP 扫。测试 297->347 (+50)。源码无真 NUL。副本字节同步。

## [1.55.3] - 2026-07-11

### Fixed: secret-guard 加固 — NUL-in-field 绕过 + log_ack 多行 (v1.55.2 follow-up)

v1.55.2 ship 后, owner 发现并发的 dev-claude 容器起了一份更周全的 L3 spec (`secret-guard-bash3-multiline-hardening`), 其 post_spec 审计抓到 v1.55.2 实现的真实缺陷。采纳其发现:

- **NUL-in-field 绕过 (安全 Critical, dev-claude spec Critical-2)**: v1.55.2 用 NUL 分隔字段, 注释断言 "JSON 值不能含 NUL" —— 但那只对**字面** NUL 成立, JSON 的 `\u0000` **转义**可以, jq 会把它解码成真 NUL, 与字段分隔符同形。攻击: command 值含 `\u0000` → 分裂使 `command` 截断成良性前缀 (放行), 真正的 dumper (env/printenv) 溢出到 `file_path` —— Bash 分支从不扫描 file_path → **secret-dump 绕过**。实测 v1.55.2: `ls\u0000printenv` / `echo hi\u0000env | grep TOKEN` 均 exit 0 放行。**修复**: 字段数守卫 —— well-formed 输入恒 4 个 NUL 分隔段, 任何其他数量 (嵌入 NUL / 畸形 JSON) → fail-closed exit 2。
- **log_ack 多行日志 (dev-claude spec qa M-3)**: #157 修复后 `command` 可多行; `log_ack` 把它写进 `guard-bypass.log` (TSV) 会破坏 "一行一条目" 不变量 (裸换行拆成多行 / 嵌入 tab 移列)。净化 payload 的 CR/LF/TAB → 空格。
- **#152 归因订正**: v1.55.2 changelog 称 `^` 锚定由 `e9dc0f7`/v1.26.0 引入 —— 错。git 史 (`git log -S`) 证由 **`e8e847c`** (2026-05-23 从 SilkNode cherry-pick, **先于 v1.26.0**) 引入; `e9dc0f7` diff 零触及 env/printenv 锚定行。dev-claude spec 独立核实在先。

### 未纳入本 hotfix (随 dev-claude L3 spec 落地)
- **命令替换/包装器全覆盖** (dev-claude spec 部件 B): `$(env)` / 反引号 / `{ env; }` / `sudo env` / `nice env` 等命令位识别扩展。该 spec 做了 spike (36/37) + 误报矩阵, 缺此覆盖是 fail-safe 漏拦 (非活可利用洞), 应按其 L3 设计实现, 不在本 hotfix 临时拍。dev-claude spec 转为权威设计 (标注 v1.55.2/v1.55.3 已实现部件 A + re-exec + NUL 守卫 + log_ack; 部件 B 待实现)。

### 验证
- 测试 292→297 (+5 NUL 绕过锁测: ls/echo/nomad 溢出 + Read file_path NUL + 良性对照); NUL 绕过实测修复前 exit 0 → 修复后 exit 2。
- 源码卫生: jq 程序 + 注释用可见 `\u0000` escape, 无真 NUL 字节。
- 副本 `.claude/scripts/` 字节同步。

## [1.55.2] - 2026-07-11

### Fixed: secret-guard 四票并案修复 (#154/#156/#157/#152) — macOS 崩溃 + 多行截断 + 中段逃逸

`hooks/secret-guard.sh` (Rule #7 载体, 默认启用 PreToolUse hook) 两个独立缺陷, 均 `e9dc0f7` (v1.26.0) 引入, v1.26.0–v1.55.1 受影响。`/issue-triage` 四票核对确认:

- **缺陷 A — `readarray` 逐行读** (`:118`, #154/#156 崩溃 + #157 截断):
  - `readarray` 是 bash-4.0+ builtin, macOS 系统 bash 3.2 / zsh 无 → hook 崩溃 fail-closed 阻断**全部工具** (#154/#156)。
  - 逐行读在字段值第一个换行处截断 → 多行 `tool_input.command` 只有第一行进拦截正则 (Rule #7 静默失效, #157)。
  - **修复**: `jq -j` 输出 NUL 分隔 (JSON 值不含 NUL 故为无歧义分隔符) + `while IFS= read -r -d ''` 读入 — newline-safe + bash 3.2 兼容 (无 readarray/mapfile)。源码用可见 `\u0000` escape (jq 运行时产 NUL, 不嵌真 NUL 字节)。
- **re-exec-to-bash guard (zsh 端到端实测揭示的 #154 更深根因)**:
  - 只做 NUL 修复后, zsh **直接执行仍对所有输入 fail-closed** (合法 `ls` 也 exit 2) — Claude Code hook runner 用 `$SHELL` (macOS=zsh) 忽略 shebang, 整个 bash-specific 脚本体 (`read -d ''` / `[[ =~ ]]` / 数组下标 / 进程替换) 在 zsh 下错乱。
  - **修复**: 脚本顶部 POSIX-sh `if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi` — 脚本体永远在 bash (3.2+) 执行, 与 hook runner shell 无关。
- **缺陷 B — `^` 锚定正则** (`:463` 等 7 处, #152 中段逃逸):
  - `^[[:space:]]*env(...)` 只匹配命令开头; `;`/`&&`/`||`/`|` 后的 env/printenv 逃逸。
  - **修复**: 前缀改 `(^|[;&|]|[[:space:]])[[:space:]]*` (含换行 — 缺陷 A 修好后多行第 2 行 env 前是 `\n`, issue 建议前缀漏此仍逃逸); bare dump 后缀重构 `([[:blank:]]*($|[;&|]|[[:cntrl:]]))` (pre-merge review Important#1: 原后缀漏 env 后跟 `;`/`&`/无空格 `|` 如 `echo hi; env; x` / `env|grep`; 新后缀 = dump 命令后可选水平空白然后 EOL/分隔符/换行 → BLOCK, 后跟空格+参数 `printenv VAR` → ALLOW; tab 分隔参数保守 over-block 为 fail-safe)。7 处锚定 + 4 处 dump 后缀对称加固。
- **dual-install 漂移根治**: 主仓 dogfood 挂的 `.claude/scripts/secret-guard.sh` 是 2026-05-20 落后副本 (逐字段 jq 完整捕获多行, 掩盖了 #157 回归) — 字节同步为分发版 (`diff -q` IDENTICAL)。

### 验证 (Rule #6 structural substitute + RED-first)
- 回归测试 260 → 286: 16 缺陷 case (7 中段 + 5 多行 + 4 不误拦, RED-first 修复前 11 FAIL) + 4 静态断言 (无 readarray/mapfile + re-exec guard) + 6 zsh 端到端 (条件跑, secret BLOCK / 合法 ALLOW 与 bash 等价)。
- zsh 实测: re-exec guard 前 zsh 全 fail-closed, 后与 bash 等价。
- pre-merge code-review (安全修复)。

## [1.55.1] - 2026-07-09

### Fixed: agent-router 基线层 5 处文本模糊补明 (#99)

v1.55.0 structural fixture 的 48-run ambiguity_notes 收纳的 5 处 pre-existing (v1.0.0 起) 基线层语义空白, 逐处成文 (纯 prose, 0 代码; 不改既有意图行为):

- **关键词匹配语义** (ROUTING_RULES §关键词匹配规则 preamble): 词边界全词匹配 (与 §CAP-1 L1 同准绳, SQL 不匹配 SQLAlchemy) + 大小写不敏感 + 匹配对象 = task 文本 (`files` 路径不参与, 路径信号 FP 专责防双重计分) + 同行多词任一命中每行至多计一次、异行可叠加。
- **task_type 自动推断程序** (ROUTING_RULES §任务类型规则 preamble + SKILL §输入参数): 未传时以 TT 表「触发关键词」为唯一依据, task 文本词边界逐字命中 (非语义联想); 多行命中各自产出候选, 零命中 = TT 类不产出。
- **SKILL 摘要表 frontend 行对齐 canonical**: `frontend/**/*` 行 `general-purpose 0.70` → `frontend-developer 0.85` (FP-022); ROUTING_RULES FP-022~025 补注 1 — frontend-developer 非插件内置 roster, 胜出时按「Agent 不存在」回退 general-purpose, 项目级 `.aria/agents/frontend-developer.md` 存在则正常路由。
- **recommend 兜底条文化** (ROUTING_RULES §Fallback 规则新小节): 候选不足 max_candidates 以 general-purpose 补足末位 (0.50 = 约定填充值非规则得分; 已入池不重复; 至多补 1 条)。
- **threshold 比较语义** (ROUTING_RULES §置信度计算新小节 + SKILL §输入参数): 一律 `>=` 恰等合格, 与 recommend 触发 `< threshold` 及 §CAP-4 R-b 既有 `>=` 互补一致。

SKILL 1.2.0→1.2.1 / ROUTING_RULES 1.1.0→1.1.1; 随手修 ROUTING_RULES footer 陈旧日期 (2026-01-22→2026-07-09)。

### 验证 (Rule #6 smoke+defer, doc-dominant 0 代码)
- 5 处补明逐条对照 #99 原文自查 + 每处 grep 落地验证; 与 §CAP-1/CAP-4/优先级处理/推荐模式触发条件一致性人工核对。
- 全量 fixture 重跑 defer 至下次触碰 router 逻辑的 cycle (v1.55.0 48-run 基线已建立)。

## [1.55.0] - 2026-07-09

### Added: agent-router 项目级 capability 匹配接入 auto 主链 (#153 发现 B)

cesura 实测: `agent-creator` 生成的项目级 Agent (`.aria/agents/database-specialist.md`, capabilities 3 标签) 在 auto 路由**从不进候选池** —— v1.1.0「项目级 Agent 发现」是贴在 SKILL.md 文末的孤儿段 (从未接进 §执行流程主链), step 5 `top_confidence >= threshold` 短路 return 使 FP/TT 命中插件级即收工, 且 ROUTING_RULES 无 capability 评分规则。gap→create→route 闭环在自动路径断裂 (Aria #153 发现 B; 发现 A 原生列表可见性归 M7 agent-lifecycle #128)。本版接线修复:

- **主链接入 (agent-router v1.1.0 → v1.2.0)**: §执行流程 step 3 新增 **3e 项目级 capability 匹配** (主链默认步, 受 `.aria/config.json` `agent_router.scan_project_agents`/`plugin_only` 门控 — 门控最先判定, 跳过支输出 shape 逐字节等同 v1.1.x); step 5 auto 改**两段式**: Stage 1 基线裁决 (基线四类规则 + <0.1 近分降级, 与既有行为一致) → Stage 2 项目级 CAP 挑战 (R-a 序数决定性直派: match_rate==1.0 ∧ |required_caps|≥2 ∧ precision≥0.5 [拦宽标签 generalist]; R-b 有序分支 (0)-(4) 含单标签禁令/基线池空分支/±0.1 护栏)。
- **§CAP 评分规则成文 (ROUTING_RULES v1.0.0 → v1.1.0)**: CAP-1 required_caps 三级确定 (显式传参 [新可选输入参数, 推断-裁决解耦] > L1 词边界机械命中 > L2 闭集受约束语义补充 [negation 恒时/addition 净值<2 启用+上界 3]); CAP-2 off-taxonomy 惰性 (零分且不计 precision 分母, 不错杀带遗留标签真 specialist); CAP-3 公式 (match_rate 覆盖率 + precision 精度); CAP-6 同名保护得分归属 (吸收插件级按名命中 confidence 走基线侧, 防 0.95 FP 静默蒸发; decision_path=baseline + agent_source=project = 同名接管); CAP-7 recommend Top-3 混排。
- **输出契约 additive**: auto_match/recommend 增 `agent_source` / `decision_path` (decision 级单值) / `required_caps_trace` (l1/l2+evidence/negated, 可审计) / `off_taxonomy_tags` / warnings 断言载体 — 仅 3e 实际执行时输出; manual/fallback 与门控跳过支不含 (零回归)。subagent-driver handoff-contract 预留字段 `agent_source` 供给侧接线。
- **缓存 per-file 语义**: 目录 mtime 对原地编辑不敏感的 latent gap (3e 承重后成路由错误源) → `last_full_scan` + per-file (path, mtime[ns], size) stat 集合比对 + `cache_ttl_seconds` 重定义为强制重扫上限 (更严) + 原子写/失败降级直读。
- **周边**: `.aria/config.template.json` 补 `agent_router` 块; taxonomy 头注补 agent-router 消费者; US-011 AC-4/D4/Scope 三锚点 errata + DEC-20260621-001 L13/L21/L90 勘误 (「已实现/那条路正常」对 auto 失实); SKILL L17 header 既有 1.0.0/1.1.0 版本漂移一并修复。

### 验证 (Rule #6 structural substitute)
- structural fixture 16 AC × 双跑 (48 runner 执行, 显式传参 pin 推断-裁决解耦): 正召/不误召/零回归三支 (新旧文本对照 @93b7406)/堵短路/同名接管/宽标签拦截/off-tax 惰性/缓存端到端/推断层 L1+negation/纯插件 =0.1 边界防再犯。R1 21/24 → 回炉 (真歧义: 基线池空分支缺失, 双跑分叉实锤) → 修文本重跑全批。
- 审计: post_spec R1→R4 (152 findings 全处置, 3C 全灭, owner 接受 Rev4); post_planning R1→R4 CONVERGED (unanimous PASS 5/5)。

## [1.54.0] - 2026-07-08

### Added: runtime-probe 泛化 → 归档门声明式可选动态子检查 (#95 follow-up A)
- **通用探针库** `state-scanner/scripts/lib/runtime_probe.py`: coordination_probe (DEC-002 单一用途硬编码件) 泛化 —
  descriptor 值层校验 (五无效形态: 缺必填/类型错/max_age_days≤0/partition 绝对路径或逃逸 repo [含 pathlib 拼接陷阱 +
  NUL ValueError 防御]/enabled_when 中间段非 dict) + `probe(descriptor, repo, now)` 四态判定 (pass / warn 四形态 /
  skipped [config 缺失与 unparseable 分型 reason] / invalid)。
- **声明面**: spec 作者活跃期在 proposal.md frontmatter 自写 `runtime_probe:` (partition/symbol 必填, max_age_days/
  enabled_when 可选); `lib/frontmatter_block.py` 新叶子 (自 collectors/openspec.py 物理 move `_FRONTMATTER_RE`/
  `_frontmatter_block`, 单一 SOT) + 受限 YAML 子集 stdlib 手写解析 (2-space scalar 子键 + 行尾注释剥离 + 文本层
  五拒绝形态 [深嵌套/flow-style/锚点/多行值/tab 缩进]); 声明作者手册 `references/runtime-probe-declaration.md`
  (含 L3 前置条件: L2/proposal-only spec 声明不评估零痕迹, designed + 测试锁定)。
- **归档门折入** `lib/spec_complete.py::gate_result`: 有声明才评估, **fail-toward-warn 单调** (pass 不变+note / warn
  抬升**绝不 block** / 已 block 不降不升 / skipped 低调 note / 声明无效→warn 无法核验); probe-warn **双写**
  warnings[] + unverified_claims[] (`{claim: "runtime_probe:<symbol>"}` 复用 #95 双下游: warn_overlay 持久化 +
  d_payload/D auto-issue 兜底); 条件性字段 `gate_result.runtime_probe` {outcome,count,reason,symbol,ts} (无声明键
  整体缺席, 禁 null 占位); 全异常兜底 (崩溃→warn 照常产出完整裁决; known-limitation: crash 不入 D tracker — gate
  自身故障归错 owner 论证, SOT 明文)。**无声明 spec 零动作逐字节不变** (SC-1: 118 归档 + 6 活跃全语料 v1.53.0 vs
  新代码同树双跑 diff=0)。
- **归档写入契约** (openspec-archive SKILL.md Step 1 schema 补注 + Step 2 warn_overlay): runtime_probe 结果
  {outcome,count,ts,symbol} 仅探针自身 outcome∈{warn,invalid} 时与 unverified_claims **同批落盘** (R3 内容归属,
  与门级 verdict 来源正交); **同名键 merge-append 规则** (SC-10 E2E 首次连续流程行使实证契约缺口后裁决: 结果字段
  追加进作者声明 mapping, 不删改作者字段、不产生 YAML 重复键; 作者值非块 mapping 走降级路径结果不落盘, 信号由
  claims 承载) + dry_run 回显扩展 + `runtime_probe_written` additive flag; phase-d-closer SKILL.md additive 提及。
- **coordination_probe.py 薄壳化**: 委托通用库; 四种既有可达状态输出+exit **逐字节不变** (`coordination-gate-invocation`
  check 零改动); 唯一有意行为变化 = read-failure 假绿修复 (旧 `OK (-1 ...)` exit 0 → STALE 类消息 exit 1)。

### Tests
- test_runtime_probe.py **57** (三态×形态矩阵 + fencepost ts==cutoff 含语义 + CRLF + 恒-pass 可证伪 harness [SC-8]) /
  test_spec_complete.py **77** (折入全路径 + IO 边界 soft_errors + block 组合 + fault-injection + L2 蒸发行为锁) /
  test_coordination_probe_cli.sh **10** (v1.53.0 实测 golden 四态逐字节 + read-failure unreadable 判别) /
  test_archive_gate_integration.sh **67** (SC-10 正控 merge-append + 负控矩阵 [pass 不落盘/混合场景/skipped/invalid/
  裸 scalar 降级] + `_staleness_days` 3 天判别式) / resweep_zero_regression.sh (SC-1 + required-corpus 守卫)。
  python 全套 968。
- dogfood (SC-7): TASK-018 phase1_gate CLI 真调 (production telemetry 记录 + `coordination-gate-invocation` 转绿) +
  TASK-019 真分区 probe=pass 一次性观测。

### 审计
- Phase A: post_spec R1→R4 + post_planning R1→R3 CONVERGED。pre-merge 4 视角 (code-reviewer / silent-failure-hunter /
  qa / tech-lead): R1 (1C/7I/13M) → R1-fix (4 代码修 + 测试锁 + SOT 三处回传) → R2 (3 PASS + 1 窄幅 REVISE) →
  R2-fix → R3 **零新 finding CONVERGED**。R1 Critical (L2 声明蒸发) 裁决为行为 per spec (R3 裁决) + 三面补课
  (SOT 披露/作者文档前置/测试锁), owner 可在 merge 签字时复议。
- Rule #6: 确定性探针/折入逻辑以 unit+integration+E2E+一次性真分区 dogfood 替代 AB benchmark (#95 同款 disposition)。

## [1.53.0] - 2026-07-05

### Added
- **#95 归档 gate 硬化 (C 分级证据闸 + D auto-issue)**: openspec-archive/phase-d-closer 归档时新增
  tri-state 完成声称真实性证据闸 —— **C-block** 高置信死代码 (集成声称点名符号有 Python 定义但生产零语义引用,
  如 Layer L `phase1_gate` 有测试却无生产接线); **C-warn** 模糊声称写 `unverified_claims` frontmatter + ack;
  **fail-toward-warn** 默认 (未分类/无定义/搜索降级恒偏假阴, 不误 block 合法归档)。**D auto-issue** 归档不吞
  未完成 (deferred/unverified → 单一 owner 幂等 Forgejo tracker, headless 默认, 非-Forgejo 降级草稿, API 失败可见)。
  延伸 #134 archive-completeness-gate (complete 字段正交)。`lib/spec_complete.py` 新增 `gate_result()` + `--gate` CLI。
- 测试: test_spec_complete.py 60 (golden 负例 + 5 类正控 + N≥8 语料 + fail-soft 注入 + C1 authoritativeness);
  新增 test_archive_gate_integration.sh 端到端 (paper-fix guard); 全 116 归档 sweep 仅 golden 1 block (SC 零影响)。

### 审计
- post_spec R1→R5 CONVERGED (R1 否证初版 Gate B checkbox 交叉核对 → owner B→C); post_planning R1→R4 CONVERGED;
  pre-merge code-review (code-reviewer PASS + silent-failure-hunter 1C/2I 全修: 搜索 authoritativeness / CLI fail-toward-warn / claim surfacing)。
- Rule #6: 确定性 gate 以测试+dogfood 替代 AB (disposition 待 owner sign-off)。

## [1.52.0] - 2026-07-05

### Added: 交互 session 防重复 — Layer L advisory 接活 + 结构化 carry-id + 运行时探针 (DEC-20260704-002)

双子星 (两个并行交互 session) 各自独立做同一 Spec 后 push 才发现重复。排查暴露双层病理: (1) carry-forward 是无主、无稳定 id 的自由文本待办队列; (2) Aria 早为此造过 Layer L 防护 (`multi-terminal-coordination` v1.22.0, 2,934 行有测试引擎) 但 `run_gate()` **零生产调用点** —— 母 spec `tasks.md` 2.5/P3 勾 `[x]` 却 `layer-l-integration.md` 自陈 TASK-024 集成 deferred, 是 aria-plugin #95「勾选完成 ≠ 运行现实」的活样本。本版**不退役、不重建**, 把 Layer L 从死代码接活成 advisory 认领 (完成 TASK-024)。

- **接线 + advisory (P1)**: `phase1_gate.run_gate` 新增 `mode` 参 (默认 advisory) + 新 CLI 入口 (AI 编排层经 subprocess 调, 对齐 `layer-l-integration.md:15` Design A —— Phase B 启动前调, 非 scan.py)。advisory 下 7b clock_skew / 7c occupied / step9 push-fail / 7a self-resume 四路径**放行 = 跳过 abort/yield, 无条件写+推自己 claim + 返回分化 surface** (advisory-over-hardlock, DEC-20260519-001 #1); **复合路径 augment 不覆写** (保留 max_clock_skew_seconds/winner, R2-Major-B 最危险路径不静默); block 模式保留原语义。`state_scanner.coordination.mode: advisory|block` (config-loader 默认 advisory, ⊥ 既有 `.enabled`)。
- **结构化 carry-id + 稳定身份 (P2)**: `standards/conventions/session-handoff.md §2.3` + `templates/session-handoff.md §6` 加 `{id, desc}` carry-id schema (kebab `carry-<slug>`, 禁冒号 —— `derive_track_id` 不译 `:`; 留 §6 prose 不进 frontmatter 向后兼容)。handoff-write 改用机械 `handoff_autofill.py --owner-container` (复用 `identity.get_identity().owner_container`) 填 frontmatter, 根除手填漂移 (实测 6 种不一致值破坏 collision 分类)。
- **遥测 + 运行时探针 + AB (P3)**: append-only `.aria/coordination-telemetry.jsonl` **结构性分区防伪** (生产分区仅私有 `_gated(_source="production")` 可达, 唯一调用点 = CLI `_main`; public `run_gate` 无 source 参 / `run_gate_synthetic` 强制 harness → 无法虚增)。`coordination_probe.py` custom-check 断言生产分区有 **14 天内**记录 (防再退化死代码, #95 修法示范)。合成双-session `dedup_harness.py`: 可证伪 (control 臂复现 #94 漏检) + 预注册决策规则 (检出≥90%/假阳性≤5%/摩擦≤500tok)。
- **文档 + dogfood (P4)**: 母 spec archive `ERRATA.md` (归档后回溯纠错) + CLAUDE.md/layer-l-integration.md doc-sync + Rule #6 structural substitute。Aria 主仓 dogfood: `coordination.enabled=true` + 真调 run_gate (claim 推 shared `refs/aria/coordination`, 探针 PASS)。
- **质量**: run_gate **首个直测** (此前零测试死代码) + 31 dedicated tests (advisory 13 / telemetry 13 / backcompat 6, 全绿, 0 回归)。双轮 code-grounded 多-agent 对抗审计: R1 抓 2 Critical + 8 Important 真实假绿洞 (advisory 复合覆盖 / 探针无新鲜度 / source 可伪造 / harness 死分支) 全修 + 新锁测 → R2 CONVERGED (0 Critical)。关 aria-plugin [#94](https://forgejo.10cg.pub/10CG/aria-plugin/issues/94) / 部分回应 [#95](https://forgejo.10cg.pub/10CG/aria-plugin/issues/95)。

## [1.51.0] - 2026-07-03

### Changed: secret-scan 诚实降级 — PostToolUse redaction 撤宣称, 转 warn-only 检测器 (aria-plugin #91 A)

`secret-scan.sh` (PostToolUse) 长期宣称"redact secret-shaped output before reaching LLM"。经 claude-code-guide 查官方 hooks-guide 坐实: PostToolUse **架构性无法** 改写已产生的 tool_response (line 891 "PostToolUse hooks can't undo actions since the tool has already executed"; 无 `updatedToolOutput`; `suppressOutput` 不影响 model 所见)。redaction 是空操作, 且多处文档/运行时输出的"REDACT"宣称会致 operator **过度信任**。

- **`secret-scan.sh`**: 保留完整检测机器 (patterns + PEM 预扫 + 计数); 删死的 redact-reemit emit 路径; 命中改发 `hookSpecificOutput.additionalContext` (告知 Claude 按已泄露处理、勿复述) + `systemMessage` (提醒 operator 轮换) —— 二者为 CC 官方支持渠道; **不改写 tool_response**。运行时串 REDACTED→DETECTED, log tag `SCAN-REDACT`→`SCAN-DETECT`; 内部计数 sentinel 中性化 (`<secret-scan-counted:tag>`); scope-based 清全文 redact-design 残迹 (intensional, 排除 L124 input-parsing)。
- **cross-repo 文档诚实化**: `aria/README.md` + `README.zh.md` (L33/L153/L154) + `standards/conventions/secret-hygiene.md` (§5.1 表格 + §5.2 exit semantics 撤"tool_response 已被改写"字面假声明 + 44→49 cases) + `shell-jq-crlf-hygiene.md` L14 —— 全撤"REDACT/output 兜底"宣称, 明确 secret-scan = detect+warn, **唯一可靠层 = PreToolUse `secret-guard`**。
- **测试**: `secret-scan.test.sh` 47→**49 PASS** (断言 redacted-output→warning-emitted; content-fidelity 测试重构非空转 [结构性缺席 tool_response + CR 检测]; 新增 exit-0-on-match + jq-missing)。secret-guard.sh (part①) 零改动, 260 回归绿。
- **防御反馈闭环** (检测→记录→反哺 PreToolUse) 拆独立 cycle [aria-plugin #92]。
- Rule #6: hook (非 Skill) 用 deterministic 回归 substitute。post_spec **R4 3/3 PASS CONVERGED** (轨迹 R1→R2→R3→R4 = 3→2→1→0 REVISE)。DEC-20260703-001。

## [1.50.2] - 2026-07-01

### Fixed: secret-guard 拦截 shell rc / login-env 文件读 (grep 缺口) — token 泄露事件根治

2026-07-01 Aether 凭据轮换中,AI 为诊断执行 `grep FORGEJO_TOKEN ~/.bashrc`,把刚轮换出的新 token 明文打进 tool output → 当场泄露、被迫二次轮换。双重缺口:(1) `grep` 不在任何 reader alternation 里(只有 cat/head/tail/...);(2) `.bashrc`/`.profile`/`.zshrc`/`/etc/environment` 等 login-env 文件不在 secret-bearing 文件列表(常存 `export SECRET=` 行)。

- **PreToolUse `secret-guard.sh`**: 新增 pattern,`(cat|grep|egrep|fgrep|rg|head|tail|less|more|strings|awk|sed)` 读 `.bashrc`/`.bash_profile`/`.zshrc`/`.zprofile`/`.profile`/`.bash_aliases`/`/etc/environment`//`/etc/profile` → BLOCK(`SECRET_GUARD_ACK_PATH` 可覆盖)+ ssh-wrapped 变体。`grep` 首次进 reader 集(此前完全缺失)。
- **回归**: 254 → **260 PASS**(6 新用例);benign 非-rc 读不误伤(`about-bashrc.md` 无点不匹配)。
- **已知待办**: PostToolUse `secret-scan.sh` 的 output redaction 在当前 Claude Code 版本**不生效**(实测 `sk-ant-fake` 假密钥原样透出;CC 不认 PostToolUse stdout content-mutation)→ 分层防御第二层塌,PreToolUse 是唯一可靠防线。跟踪 [aria-plugin #91](https://forgejo.10cg.pub/10CG/aria-plugin/issues/91)。

## [1.50.1] - 2026-06-26

### Changed: session-closer 触发消歧矩阵内联自包含 (第三方无需 standards 子模块)

session-closer SKILL.md「我应该用这个 Skill 吗？」加**触发消歧速查表** (易混词 对话收尾/写交接/收尾阶段 → 期望命中 skill) inline, 让第三方项目 (不 vendor aria-standards) 也有自包含的路由消歧依据。standards §1.3 保留为完整方法论 SOT (周期 vs 会话单元论证 + 5 层 enforcement); SKILL.md 速查为操作快查, 非完整复制 (避免大块 drift)。纯 doc 自包含改进, 无逻辑/测试变更。Skill 1.0.0→1.0.1。

## [1.50.0] - 2026-06-26

### Added: session-closer skill (会话维度收尾仪式, 正交于十步循环 Phase D)

新 user-facing **leaf skill** `session-closer` —— 把"对话收尾"做成与开发周期收尾 (phase-d-closer) 正交平级的会话仪式:

- **AI 对话内省优先** (一等公民): step1 未完成线程/待办 + step2 待固化经验 (结构标记 `[候选 memory]`/`[未写下经验]`)。
- **机械 autofill 兜底** (backstop): handoff_autofill 交叉核验补漏 (snapshot 有但 AI 没提 → flag) + consistency_check 四维 advisory + closeout_trigger context 压力 nudge。3 脚本 + 49 单测 + 真 snapshot 集成测试。
- **共享 handoff-write SOT**: 复用既有 `phase-d-closer/references/handoff-mechanics.md` (引用不复制, 无第二份 ref)。
- **trigger 消歧根治**: phase-d-closer description 中度 rebind (删「写 session handoff」+裸「收尾」, rebind cycle-explicit + 负向消歧); session-closer 强绑会话词; standards §1.3 周期vs会话收尾消歧节 + 矩阵 (第三方 load-bearing)。
- **leaf 终结**: 写完 handoff 即止, 检出未归档 cycle 仅 advisory 提议, 不调 phase-a/b/c/d (advisory-over-hardlock)。
- phase-b/c context-monitor step 接 closeout_trigger (喂 token_telemetry 输出)。

Source: session-closer-synthesis Spec (DEC-20260625-001, supersedes 搁浅的 session-closeout-internalization, 复用 ~70-80% 实现)。post_spec R1 REVISE×3 [既有 ref 复用 + collector 字段漂移修正] → Rev1 → R2 PASS×3 unanimous; code-review I-1/I-2 真形态假绿修复; Rule #6 capability AB +13.3pp owner sign-off。

**Skills: 34 → 35 user-facing + 7 internal = 42 total**。standards 1.1.0→1.2.0。

## [1.49.0] - 2026-06-21

### submodule pointer regression gate: warn → block flip (#124 Two-phase rollout 执行单元)

Flips C.2.4.5 submodule pointer regression gate default `mode` from `warn` to **`block`**, per parent Spec `aria-submodule-pointer-regression-gate` (v1.28.0) Two-phase rollout 承诺。

**Flip 依据 (Trigger B + owner risk-accept)**: hard-date Trigger B + minimum-observation guard ≥3 gate executions (实测 **5**, all mode=warn / verdict=PASS) + tripwire green (**4 clean host-cron runs**, independent backstop) + FP rate **0%** (0 WOULD-BLOCK events)。owner risk-accept sign-off 2026-06-21 (executions 聚集 2 ship 事件 + index.lock 重试虚增, 字面阈值满足但严格独立观察=2 — owner 接受)。决策记录 `.aria/decisions/2026-06-21-v1.49.0-block-flip.md` (主仓)。

**§A 3 处 default flip**:
- `scripts/submodule_gate.sh:33`: `MODE="${ARIA_SUBMODULE_GATE_MODE:-warn}"` → `:-block}` (runtime SOT)
- `phase-c-integrator/SKILL.md:450`: inline doc-Bash 同步
- SKILL.md config 表 / Two-phase rollout / verdict 三态 / mode 参数表 全部 warn-default → block-default 现在时 (保留 v1.28.0 历史叙述行)

**新测试 T-flip-12**: unset `ARIA_SUBMODULE_GATE_MODE` → 默认 block (regression exit 1)。锁定 flip。15 PASS / 0 FAIL (was 14)。

**Backward-compat**: `mode="warn"` legacy opt-out / `mode="off"` emergency bypass / env-var override 优先级 > config — 全部保留。

**§B 作废**: 原 `.forgejo/workflows` schedule cron 追加已被 host-cron 迁移取代 (v1.41.0 R-fix-2); tripwire 经 host-cron `0 4 * * 0` 运行。

Skills 数不变 (34+7=41)。Spec `aria-submodule-gate-block-flip` 归档。

## [1.48.0] - 2026-06-21

### agent-team-audit 项目级 audit agent 增补 (#145)

**问题**: `agent-team-audit` 选择 step 3 写死静态 matrix (3 触发点 → 固定 4 内置 agent 子集), 从不消费 `.aria/agents/` 项目专属 audit agent。`agent-gap-analyzer → agent-creator → .aria/agents/` 生成链已建成 (含 capabilities tags), 但 audit 消费方永不选入项目 agent。reporter 实证: 项目 security-auditor (shell-safety/ssh-egress) 抓到 tech-lead/code-reviewer 视角抓不到的 Critical, 当前 audit 架构用不上。

**修复**: step 3 拆 **3a 固定基线 + 3b 项目级 capabilities 增补**:
- `.aria/agents/` 中 capabilities 命中检查点"增补白名单"的项目 agent 加入审计批次 (复用 agent-router `.aria/agents/` 发现范式, 不另造; 冷路径直读 frontmatter, `.aria/cache/project-agents.json` 仅可选加速)。
- matrix 新增"增补 capabilities 白名单"列 (pre_merge/post_implementation: `security-audit`, `performance-optimization`; post_spec 空), 锚定 `capabilities-taxonomy.yaml`。
- **判据 = 专有标签阈值 (非 baseline 减法)**: code-reviewer 已带 `security-audit` → 减法会盖住项目 security-auditor, 故用显式白名单, 命中即加入 (基线通用维度 + 项目专家纵深互补非冗余)。
- **augment-only** (非 override): 基线永远跑, 项目 agent 纯加法。
- 增补 agent 受 `max_parallel_agents` 节流但不丢弃 (分批串行)。
- 降级零回归: `.aria/agents/` 空 / 无命中 / 字段缺失skip / 空list合法 → 纯基线 (逐字节相同)。

**文档同步**: SKILL.md (step 3a/3b + 触发点表 Agents 列 + 输出格式分母=基线+增补) + agent-selection-matrix.md (白名单列 + step 3b 算法 + 并发调度) + audit-points.md (各 `agents:` 字段注记; mid_post_spec 标注不在增补范围)。

**边界**: 与 M7 agent-lifecycle **正交** (M7=项目 agent 物化到 `.claude/agents/` 原生加载侧; 本=audit 消费侧)。OOS: agent-creator 写 `.claude/agents/` (让给 M7) / override 语义 / 扩 taxonomy 细粒度标签 / 改 agent-router / experiment 转正。`agent-team-audit` = experimental (默认关), 能力随 experiment 转正才可用。

**Rule #6** (prose/process skill): structural fixture (5 文件: 4 fixture agent [security-auditor 命中 / doc-helper 通用不命中 / malformed 缺失skip / empty-caps 空list合法] + 1 算法 trace) + AC-5 dogfood (Aria 无 `.aria/agents/` → 纯基线零回归确认)。post_spec R1 REVISE → Rev1 7 项全落地 → R2 CONVERGED (unanimous PASS 2/2); code-review Phase 1 PASS + Phase 2 I-1/I-2/M-1/M-2 全收。

**Skill 版本**: agent-team-audit 1.0.0 → 1.1.0。Skills 数不变 (34+7=41)。

## [1.47.0] - 2026-06-19

### Issue-sweep release train — 4 cycles / 6 issues (#69 #54 #95 #79 #32)

一次性执行 "纯 AI 可独立完成 + 现在值得做" 的 open issue 批 (M6/M7 等待期填空)。4 个 cycle 各走完整十步循环 (Rule #1 OpenSpec + Phase A + 独立 agent-team 对抗 review), 共享 release 分支增量实现, 一次 Phase D 打包发版。Rule #6 = deterministic structural + dogfood-by-construction (无自动化多-agent 审计 AB harness)。

- **Cycle A — secret-guard 扩 exfil 覆盖 (#69)**: Aether v1.28.0 14 天 dogfood 报 5 个 FN; **实测 triage 确认 v1.46.5 仍全漏 + 6 额外探针**。RED-first: 16 BLOCK 探针 + 4 FP guard → 加 regex (base64 reader / 非标准 ssh key 名 `\.ssh/id_[A-Za-z0-9_]+` / `.docker/config.json` / Vault HTTP `-H X-Vault-Token:` + `hvs.{24,}` / kubectl `-- sh -c` 包裹 / scp·rsync·cp·tar|ssh·wget exfil-to-destination)。254/254 测试零回归。agent-team 2-lens (code-reviewer + 对抗 hunter) 修真 FP (scp `/private/` macOS / X-Vault-Token 文档提及 / hvs. 短 id / tar `.sshconfig`) + bypass (dd `bs=` 位置 / cp key-as-EOL-dest)。

- **Cycle B — audit runtime-reality 检查项 (#54 + #95)**: agent-team-audit/audit-points.md 加 **数据可用性** (#54: 断言引用历史 git/外部/环境数据时机械核实存在, **verdict-load-bearing** 缺失→REVISE/FAIL 非观察性) + **框架约定** (#95: package.json 探测 framework 验证 route export/routing/directive 约束) 检查项 (post_spec + post_implementation) + 横切检查原则节。phase-b-developer 加可选 B.2.5 framework build 验证 (config-gated, advisory, **tri-state** `not_configured`≠pass)。spec-drafter Framework Constraints 提取。config-loader `phase_b_developer.framework_build_check` (3-way parity, 默认 no-op)。

- **Cycle C — mid_post_spec 条件触发检查点 (#79)**: Phase B SMOKE/集成测试暴露 spec 漂移 → 暂停 → single-round (max_rounds=1) scope-limited mini-audit → append-only spec amendment (含 neutralize 要求防 amended-and-ignored) → resume。新检查点贯穿 config (checkpoints+teams+trigger, 默认 off) + audit-engine (列表+single-round 约束+proposal-class anchor) + audit-points (新节+material-vs-incidental trigger 判别) + phase-b-developer (B.drift flow)。agent-team review 补齐 4 处 engine-internal 契约 (pre-merge 完整性 gate **排除** mid_post_spec — 事件条件触发可合法不产报告; max_rounds clamp; anchor 分类; blocking 表)。

- **Cycle D — tdd-enforcer 安全代码 commit 分离 (#32)**: `security_commit_separation` (= issue 的 `level_3_strict`, 改名避开 "Level 3: Superpowers" strictness 歧义), strict/superpowers 下强制安全代码 (auth/credential/secret/acl/check) RED commit 与 GREEN commit 分离 (Aether #42: bundled commit 致 test-first 不可验)。schema (默认 enabled=false) + SKILL 检测节 (2 档升级路径 strict block+[skip-tdd] / superpowers no-bypass) + 参考 **commit-msg hook** (项目 opt-in, 不接入 Aria hooks.json) + strict.json 示例。agent-team review 修参考 hook 真 bug (pre-commit 读错 commit→commit-msg / `test_*.py` 前缀 + top-level `tests/` 锚 / 安全 grep word-boundary 防 authority/oauth/healthcheck 误命中 / advisory 行 self-negating 删除)。

Skills 不变 (34 user-facing + 7 internal = 41). 4 OpenSpec 归档。

## [1.46.5] - 2026-06-14

### submodule-gate telemetry — gate completes + records execution under the hook timeout (R-fix-1 follow-up)

block-flip 重启诊断 (owner Path A)。**Level 1** telemetry bug 修复 (R-fix-1 follow-up, 无独立 issue)。

- **根因**: R-fix-1 (v1.40.0) 加的 `submodule-gate-telemetry.sh` PostToolUse hook 以 WARN 模式跑 `submodule_gate.sh` 记录执行, 但 gate 的 `log_execution` 在 per-submodule `git fetch origin` **之后**。Aria 有 3 个 submodule, aria/aria-orchestrator 的 origin 是 forgejo (Cloudflare Access 后, ssh 慢/hang)。fetch hang 超过 hook 的 `timeout 15` → gate 被杀于 log_execution 前 → **0 executions 记录** (block-flip D+14 Trigger C 根因持续)。2026-06-14 复现 exit 124。
- **修复**:
  - `submodule_gate.sh`: WARN/telemetry 模式 **跳过** per-submodule fetch (O(N)→O(1); 用本地 refs, WARN 仅 advisory); superproject + (block 模式的) per-sub fetch 用 `bounded_fetch` (timeout 包裹防无限 hang, Windows 无 timeout 时 fall back bare git)。block/merge-flow 路径 fetch 行为不变 (authoritative)。
  - `submodule-gate-telemetry.sh`: gate-wrap `timeout 15` → `25`。
  - `hooks.json`: telemetry hook `timeout 20` → `30`。
- **验证**: WARN 完成 9s + 记录真实 PASS 执行; block 32s 不变 + 记录; gate 14 PASS (新增 scenario_11: WARN origin 不可达仍完成+记录) / hook 7 PASS / state-scanner 821 OK。
- **意义**: telemetry 修复后 future ships 的 gitlink bump 真实累积 executions → 满足 block-flip Trigger B 的 ≥3 minimum-observation guard (tripwire 已绿 2 clean host-cron runs) → 后续真数据 flip。见 `.aria/decisions/2026-06-07-v1.40.0-block-flip.md` + `openspec/changes/aria-submodule-gate-block-flip/proposal.md`。

## [1.46.4] - 2026-06-13

### coordination-ref lib `_run` timeout ceiling (F2-minimal) — never hang on stalled git op

F2 收口 (minimal slice; #141 follow-up, 无独立 issue)。**Level 1**。

- **问题**: `lib/coordination_ref.py::_run` 无 timeout → phase1_gate 里 coordination git op (fetch/push to remote) 网络卡住会**无限挂起** (collector `_run` 有 timeout, lib 的没有 — F1 时标为 F2-class)。
- **修复**: 加 `timeout: int = 30` (对 tiny coordination ref + 亚秒级本地 plumbing op 极宽松, 不误失败合法 op) + `except subprocess.TimeoutExpired → (124, "", "git command timed out after 30s")` (stderr 含 "timed out" → `fetch_coordination_ref` 分类为 network) + #131 None-guard `(result.stdout or "").strip()`。
- **故意跳过 rc 对齐**: FileNotFoundError 保 `-1` (非 collector 的 `127`) —— lib callers (`_ref_exists_local` 等) 判 `rc < 0` 检 not-found, 对齐到 127 会破坏 (F1 code-review 已 flag)。这是两 `_run` 唯一刻意分歧。
- **deferred** (低价值 + 风险 refactor, opt-in phase1_gate 默认关): 两 `_run` impl 的 full consolidation (dedup) + coordination_fetch 分支头载重耦合解耦 → backlog。
- **测试**: `TestRunTimeout` (3): default-timeout 传参 (mock kwargs) + TimeoutExpired→124 (不传播/不挂起) + fetch timeout→network 分类 (与 benign-absent gate `rc==128` 隔离)。**88 coordination 测试全过** + 全套件 821 绿。code-review **PASS** (全 11 个 lib `_run` callers 核验优雅处理 rc=124 + rc-对齐跳过正确)。Skills 不变 (41)。

## [1.46.3] - 2026-06-13

### coordination-ref-lib-run-parity (F1) — lib `_run` #61+#143 parity + benign-absent

收口 F1 (#141 code-review silent-failure-hunter M2 派生的 out-of-scope follow-up; 未开 issue)。**Level 2**。

- **根因**: `lib/coordination_ref.py` 有**自己的 `_run`** (独立于 `collectors/_common._run`)。#61 (UTF-8 crash-safe) + #143 (LC_ALL=C locale) 两次 `_run` 加固只改了 collector 那个 → 本地 _run ① 非英文 git locale 下 auth/network 英文 stderr 匹配失灵; ② C-locale + 非 ASCII 协调内容 (claim YAML owner/notes, 经 `git show refs/aria/coordination:<path>` 读) → `text=True` 严格解码 **UnicodeDecodeError 崩溃** (try 只 catch FileNotFoundError/OSError; #61 当初要防的崩溃在此仍在)。`fetch_coordination_ref` 错误分类无 benign-absent → coordination ref 不存在误判 `fetch_failed`。
- **TG-A**: 本地 `_run` 加 `encoding="utf-8", errors="replace"` (#61) + `env={**os.environ, **(extra_env or {}), "LC_ALL": "C"}` (#143; LC_ALL=C 末位非覆盖, extra_env=GIT_INDEX_FILE 正交仍生效)。**只加 #61/#143**; collector _run 额外有的 timeout / TimeoutExpired→124 / None-guard 留 **F2-class** (不声称完全 parity)。不 import collectors (layering: lib 低于 collectors)。
- **TG-B**: `fetch_coordination_ref` auth/network/else 分类**之前**加 benign-absent 三重 AND 闸 (`rc==128 AND "couldn't find remote ref" in err_lower AND REF_NAME.lower() in err_lower`, 镜像 collector `_is_benign_coordination_absent`, 用 lib 自己的 REF_NAME 复制非 import) → absent ref = `success=True, ref_updated=False` → `health_check_fetch` 不再误标 `partial_fetch`。`ref_updated=False` 双义 docstring 注明 (无 caller 在 success=True 时 branch)。
- **可达性低** (调用链 phase1_gate **opt-in 默认关** → health_check_fetch → fetch_coordination_ref; health_check 在 acquire_claim 写完 ref 后跑 → benign-absent 罕见) 但是**真实潜在崩溃/locale 隐患**, 消除两个分叉 `_run` 的加固缺口。
- **TG-C 测试** (强制 lib-直测, 非 mock wholesale 绕过): `test_coordination_ref_lib.py` 7 测试 — env 断言 (patch `lib.coordination_ref.subprocess.run` 捕 env, **host-locale-agnostic** 可证伪) + extra_env 共存 (GIT_INDEX_FILE + LC_ALL 仍 C) + benign/converse-非benign/wrong-ref/auth 分类 (真打 fetch_coordination_ref 仅 mock 内部 _run) + crash-safe (真 subprocess 喂坏字节)。**97 coordination 测试全过 under LC_ALL=C** + 全套件 818 绿 (modulo 已知 timing flake)。
- **流程**: post_spec **CONVERGED** (R1 2/3 REVISE 3 major 全为"测试落点太松允许 mock 绕过真 code path" → Rev1 强制 TG-C lib-直测 → R2 3/3 PASS)。code-review **PASS** (env merge / benign 闸 / health_check trace / layering 全经源码+实地 git 复现验证)。Skills 不变 (41)。

## [1.46.2] - 2026-06-13

### track-board-coordination-stale-bar (#144, F5) — coordination-ref fetch-failure yellow advisory

Fixes Forgejo Aria [#144](https://forgejo.10cg.pub/10CG/Aria/issues/144) (F5, 源自 #141 code-review silent-failure-hunter #5)。**Level 1** (render-only, 无 OpenSpec)。

- **half-silent failure**: Fetch 1 (分支头) ok + Fetch 2 (coordination ref) **非 benign 失败** 时, `coordination_fetch` 返回 `success=True` / `degraded=False` + emit `coordination_ref_fetch_failed` soft_error (进 snapshot `errors[]` + exit 10)。但 `render_track_board` 原只读 `degraded`/`cached` → 多终端协调看板**全绿无提示**, 用户无视觉感知协调数据已陈旧。
- **fix**: `render_track_board` 加非阻塞**黄条** `⚠ 协调 ref 未取到 (网络/超时), 队友协调数据可能陈旧 (分支视图仍新鲜)`, gate 在 `errors[]` 的 `coordination_ref_fetch_failed` —— **唯一无误报判别器** (该 error kind 仅 Fetch-2-非 benign 路径 emit; code-review 验证: 备选 `coordination_ref_present is None` 单独会误报 Fetch-1-fail-no-cache 路径)。`degraded` 时红条 (`⚠ 离线`) 优先, 黄条 yield。
- **测试**: `test_p1_layer_h.py` TestCaseF (6): 触发 / 与 track 行共存 / degraded 红条优先 / clean 无黄条 / 无关 error 不触发 / errors[] 缺 key fail-soft。全套件 **810 绿** via canonical runner (modulo 已知 timing flake `test_two_consecutive_runs_diff_zero`, render-side 不碰 normalize)。code-review **PASS** (errors[] 耦合决策经验证优于备选; M-1 fail-soft 断言加固)。
- docs: `track_board.py` 模块 docstring offline/cache 指示符表补黄条。无 schema/collector 改动。Skills 不变 (41)。

## [1.46.1] - 2026-06-13

### state-scanner-git-stderr-locale-hardening (#143 fixed + #142 wont-fix) — _run 强制 LC_ALL=C

Fixes Forgejo Aria [#143](https://forgejo.10cg.pub/10CG/Aria/issues/143) (F4) + closes [#142](https://forgejo.10cg.pub/10CG/Aria/issues/142) (F3, wont-fix); 均源自 #141 code-review silent-failure-hunter。

- **#143 fix**: `collectors/_common.py::_run` 继承进程 locale → 多个 collector (coordination_fetch benign 闸 + `_classify_error` / multi_remote / issue_scan) 匹配**英文** git/网络 stderr 文本, 非英文 git locale 下失灵 (benign 闸 false-negative spurious soft_error + 错误误分类)。`_run` 注入 `env={**os.environ, "LC_ALL": "C"}` 强制 git 英文诊断, 全 git-collector 受益。与 #61 `encoding="utf-8"` **正交** (LC_ALL 管 git 诊断文本; encoding 管字节解码 — commit/ref/path 字节直通在 LC_ALL=C 下 md5 一致, 实测)。`LANG=C` 冗余 (LC_ALL 折叠所有 LC_*) 故省。
- **#142 wont-fix**: ls-remote `--exit-code` 实测对 absent 与 ACL-hidden ref **同 rc=2** → git 协议层**无法区分** absent-vs-hidden (#142 标题目标不可达)。ls-remote decline (LC_ALL=C 落地后 benign 文本匹配已可靠, ls-remote 仅剩边际 race-catch 不值 +1 网络往返)。auth-masked silent 隐患保持 **documented-limitation** (#141 已 log.info + docstring/schema 注记缓解; Aria repo 级 ACL 下不可达)。
- **测试**: env 断言测试 (`mock.patch` `subprocess.run` 捕获 env kwarg, **host-locale-agnostic** 可证伪 — 闭合 "C-locale CI 下 803 绿循环论证" gap) + CJK 直通真测 (实际 `git log --oneline` 路径, 含 CJK+emoji+箭头全 subject 断言)。全套件 **805 绿** via canonical runner (modulo 已知 timing flake `test_two_consecutive_runs_diff_zero`, 非本变更); **138 git-解析 collector 测试全过 under LC_ALL=C** (零回归)。
- **流程**: post_spec **CONVERGED** (R1 2/4 REVISE 3 major [#142 收口语义 / 803 循环论证 / CJK 命令 --format=%s→--oneline] → Rev1 → R2 4/4 PASS unanimous)。code-review **PASS** (M-1 CJK 全 subject 断言已加固)。docs: `_run` + coordination_fetch benign 闸 docstring + schema 注记 (英文假设 → 已由 LC_ALL=C 强制保证)。schema_version 保持 `1.0`。Skills 不变 (41)。

## [1.46.0] - 2026-06-12

### state-scanner-coordination-fetch-resilience (#141 软错误① + aria-plugin #75) — coordination_fetch 拆两条 fetch

Fixes Forgejo Aria [#141](https://forgejo.10cg.pub/10CG/Aria/issues/141) 软错误① + aria-plugin [#75](https://forgejo.10cg.pub/10CG/aria-plugin/issues/75) (同一 bug 两处跟踪; triage `partial-repro`/`major`/`next-cycle`, [comment-12658](https://forgejo.10cg.pub/10CG/Aria/issues/141#issuecomment-12658))。`collectors/coordination_fetch.py` 把 `+refs/heads/*` 与 `refs/aria/coordination` 合成单条原子 `git fetch`。远端从未发布 coordination ref 的项目 (即多数**未用多终端协调**的项目, 如 SilkNode) → 整条 fetch **每次 rc=128 失败** + `+refs/heads/*` 分支头连带不刷新 + 每次扫描发 spurious `coordination_fetch_failed` soft_error (exit 10)。

- **拆两条独立 fetch**: Fetch 1 (`+refs/heads/*:refs/remotes/<remote>/*`, 分支头, 载重, 先跑) + Fetch 2 (`refs/aria/coordination`, 仅 Fetch 1 成功后)。Fetch 1 失败 → **短路**不跑 Fetch 2 (远端不可达时协调状态不可知)。
- **benign 三重 AND 闸**: coordination ref 缺失 (`rc==128 AND "couldn't find remote ref" AND "refs/aria/coordination"`, 求值**先于** `_classify_error`) = 良性"未发布" → 不发 soft_error, `success` 保持 True。真 network/auth/timeout 失败 (rc=124/127 或异措辞 rc=128) 仍 surface。
- **新增 additive `coordination_ref_present`** (True/False/None): 写入 cache payload, cache-hit/stale-serve 读回保稳定, **不进** normalize DROP_KEYS (None 由 null-drop 处理仍稳定)。`success`/`degraded` 重锚定 Fetch 1。legacy cache (无 key) 读回 None 兼容。
- **测试** (Rule #6 deterministic substitute): 新建 `tests/test_coordination_fetch.py` **12 测试** (benign 闸 4 + 7 场景 a-g + legacy cache); 全套件 **803 全绿** (除 1 已知预存 timing flake `test_two_consecutive_runs_diff_zero` — live-repo age 字段, 与本变更无关)。dogfood: no-coord sandbox (真 git remote) → success+present=False+无 error (旧代码此处 fail); Aria 自身 (有 coord ref) → present=True 零回归。
- **docs**: `references/state-snapshot-schema.md` **新建** coordination_fetch SOT section (此前 undocumented) + `phase-1-collectors.md` L41 重写 + 模块 docstring + DROP_KEYS 裁定注释。
- **流程**: post_spec **CONVERGED** (R1 4/5 REVISE 8 major → Rev1 → R2 5/5 PASS unanimous)。code-review: aria:code-reviewer **PASS** + silent-failure-hunter findings → 已知限制文档化 (git absent-vs-hidden ref 歧义 / English-locale 假设, Aria 部署不可达) + **3 follow-up** (F3 `ls-remote --exit-code` 硬化 / F4 `LC_ALL=C` / F5 track_board 黄条)。`lib/coordination_ref.py::fetch_coordination_ref` 同有 benign 缺口但属 distinct Layer L 路径 → out-of-scope follow-up。schema_version 保持 `1.0` (additive)。Skills 不变 (41)。

## [1.45.0] - 2026-06-11

### cross-worktree-handoff-discovery (#139) — 跨 worktree 交接断链修复 (Phase 1.15b)

Fixes Forgejo [#139](https://forgejo.10cg.pub/10CG/Aria/issues/139) (triage `confirmed` 4/4, [comment-12467](https://forgejo.10cg.pub/10CG/Aria/issues/139#issuecomment-12467)): 单人多 worktree 并行时, 上 session 把 handoff 写在 feature worktree (分支未合 main), 新 session 默认在主 worktree 启动 → `scan.py` 按 cwd 采集**读不到**他树最新 handoff, 新 session 被引导进错误状态 (2026-06-04 SilkNode cut2-batch1 实地事故)。设计 SOT: Aria 主仓 `docs/decisions/DEC-20260611-002-cross-worktree-handoff-discovery.md` (brainstorm 3 决策 [纯机械发现 / 两级语义+epoch 仲裁 / advisory 引导] + post_spec R1 FAIL 5M+7m → R2 PWW N-1..N-9 → R3 PASS)。

- **新 collector `handoff_worktrees.py`** (Phase 1.15b, 紧随 1.15): `git worktree list --porcelain` 枚举, 复用 `handoff.py` 抽出的 `_resolve_latest` helper (单份 H5 pointer→mtime 逻辑, `collect_handoff` 逐字段零回归) 解析各树最新 handoff, epoch 域按 frontmatter `updated-at` 仲裁全局最新 (`Z`/offset 兼容无 py3.11 floor; tie → current-tree-wins / other-vs-other path 字典序)。全局最新落他树时输出 additive 顶层字段 `handoff_worktrees.global_latest_elsewhere`。纯机械发现**零 frontmatter schema 变更** (DEC Q1: 事故根因是"发现不了"非"声明不够"; 加字段会破 #137 E1 head-8 窗口)。
- **阶段 2 advisory 引导**: `global_latest_elsewhere != null && status=="active"` → 提示 `EnterWorktree` 切过去续 track (编号选项 [1]切/[2]留/[3]先看, advisory-over-hardlock 非自动切; 非 Claude Code 环境降级 `cd` 指引)。`done`/`abandoned`/`legacy` 仅列表展示不触发 (仲裁字段诚实, Phase 2 gate on status)。
- **配置** `state_scanner.worktree_scan.{enabled (默认 true), max_worktrees (默认 8)}` + env `ARIA_WORKTREE_MAX_SCANNED` (新 resolver `resolve_max_worktrees_scanned`, 三层镜像 #71)。软错 `worktree_enumeration_failed` / `worktree_unreachable` (含 prunable) / `worktree_scan_cap` (warn-only) / 树内失败带 worktree path 前缀; 他树**不发** #137 `handoff_frontmatter_missing` (防 errors[] 污染 E2)。`enabled` vs `enumerated` 机读可分 (config-disabled 无 enumeration 软错; R2 N-1)。
- **附带覆盖**: Step 1.17 `handoff_multibranch` 仅扫 `refs/remotes/origin/*`, worktree 分支未 push 时多 track 看板失明 — 本 collector 在本机维度覆盖此盲区 (triage 增量情报)。
- **测试** (Rule #6 substitute, deterministic collector): 20 collector + 27 resolver = **47 新测** (739→786 全绿, `collect_handoff` 零回归); dogfood = Aria 真树 no-op (`others=[]`) + sandbox e2e 跨树发现 (triage case-4 事故场景修复)。8 文档同位更新 (SKILL collector 计数 14→15 + state-snapshot-schema + recommendation-stages + output-formats + phase-1-collectors + RECOMMENDATION_RULES + layer-l-integration 互引 + json-diff-normalizer Rule 2 留白)。**不含 standards 变更** (零 schema 改动红利)。Skills 不变 (41)。

## [1.44.0] - 2026-06-11

### audit-drift-guard (#17) — audit-engine 多轮审计原始目的锚定 (Drift Guard)

Fixes aria-plugin [#17](https://forgejo.10cg.pub/10CG/aria-plugin/issues/17) (triage `confirmed`, [comment-12282](https://forgejo.10cg.pub/10CG/aria-plugin/issues/17#issuecomment-12282)): challenge 多轮审计的收敛判定只测四元组集合稳定性, **不测"是否还在讨论最初那个问题"** — 集合稳定 ≠ 命中原始目的, 对抗式讨论可从 anchor 漂走且被"全员合并"放大。设计 SOT: Aria 主仓 `docs/decisions/DEC-20260611-001-audit-drift-guard.md` (brainstorm 4 决策 + post_brainstorm 19-agent/3 轮 23 修订 + post_spec R3 PASS)。

- **Step 0 Anchor 固化** (audit-engine SKILL.md): Round 1 前一次性 `{checkpoint, primary_goal, in_scope[], out_of_scope_hints[], source_sha}`, 审计周期内不可变; 5 级 per-checkpoint fallback 链 (proposal Why/Goal → change_id 解析 → brainstorm_decisions [post_brainstorm 调用契约三点, brainstorm/SKILL.md caller 侧同步] → issue/PR 标题 degraded → 全缺 fail-soft 不阻塞)。
- **Step 5 Drift Check** (challenge-mode-schema): 独立轻量 drift-checker (内部调用非审计 agent, 30-60s 独立超时不占轮预算, **fail-open** 瞬断按 <warn 处理) 逐条分类 on-topic/adjacent/off-topic → `drift_ratio = off_topic / all`; per-mode 分母显式 (challenge = decisions ∪ objections, obj- 低置信分类); 联合判空除零; partial anchor (`anchor_scope_empty`) 降维不跳过。
- **三档处置** (可配 `audit.drift_guard {warn_threshold: 0.2, refocus_threshold: 0.5, convergence_mode: false}`): `<warn` 正常 / `[warn,refocus)` Warning + 强制 `unanimous_pass=false` 延迟一轮 (仅 convergence; challenge 仅标注) / `>=refocus` → **REFOCUS_ROUND** (消耗 max_rounds 配额防活锁, `is_refocus` 标签, 输出替换 stability 基线, 剔出 oscillation keys_N_2 序列) + `consecutive_refocus_count>=2` → **DRIFT_TERMINATED** 独立终局态 → verdict=FAIL (drift override, 走既有 FAIL owner 决策流程, **不发明硬中止**)。四终局优先级: CONVERGED → DRIFT_TERMINATED → OSCILLATION → MAX_ROUNDS_EXHAUSTED。
- **报告 schema** (additive, 防 #125/#126): frontmatter `drift_terminated/drift_check_skipped/is_refocus` 无条件默认 false (oscillation 同构) + `drift_metrics` 章节 (per_round 三类计数 + converged_on_anchor); verdict 恒裸枚举, 计算规则单 SOT (report-storage §Verdict); 旧报告缺字段 = drift_ratio 0 不告警。
- **scope**: challenge 默认开 / convergence opt-in / post_closure 屏蔽。dispatch 契约 Drift Guard 字段小节 + drift-checker 8-field 排除。
- 纯 prose + schema (9 文件, 无 Python); AC-1~7 grep 模式串机械验收全过; Rule #6 doc-existence substitute; dogfood = 本 Spec post_implementation audit 须产出非空 drift_metrics。Skills 不变 (41)。

## [1.43.0] - 2026-06-10

### handoff-frontmatter-enforcement (#137) — frontmatter content enforcement 两层

Fixes Aria [#137](https://forgejo.10cg.pub/10CG/Aria/issues/137) (triage `partial-repro`, [comment-12236](https://forgejo.10cg.pub/10CG/Aria/issues/137#issuecomment-12236)): multi-terminal frontmatter **注入机制已存在** (模板 v1.22.x+ 5 字段 + 派生规则), 但三层零 enforcement — ad-hoc handoff 静默落 legacy, 多 track 看板 owner=unknown 且无人知道 (SilkNode 2026-05-31 实地)。修复 = **enforcement 而非注入**:

- **E1 D.3 写后自校验** (`phase-d-closer` execution-steps.md 子步 2b + handoff-mechanics.md 前置节): `head -8 <doc> | grep -cE '^(track-id|owner-container|phase|status|updated-at):'` 须 ==5, 不足按模板派生规则补齐重验 (warn-then-fix 非硬 abort, advisory-over-hardlock per DEC-20260519-001); 不得带缺字段 handoff 进 latest.md pointer 更新。
- **E2 scanner soft warning** (`collectors/handoff.py`): Phase 1.15 对 **resolved latest doc** (`latest_path`, pointer **与 mtime fallback 双路径** — mtime 正是 ad-hoc 事故主场景) 缺 §2.3.1 frontmatter 时发 `handoff_frontmatter_missing` soft warning + additive 字段 `handoff.latest_frontmatter_missing: bool` (exists=False / stat-failed 恒 False; read_text OSError 完全静默 fail-soft; 不 bump `snapshot_schema_version`)。仅 latest 目标 — 历史 legacy 不刷屏。
- **standards**: session-handoff.md 新 **§2.3.7 content enforcement** 独立小节 (与既有 location enforcement 5 层明确区分)。
- **Tests**: 8 新测 (731→739) — pointer/mtime 对称用例对 (防 pointer-only 误实施漏网) + 历史 legacy 静默 + exists=False/stat-failed/OSError 三边界; 既有 3 测随 additive 字段/happy-path 语义同步更新; 真树 dogfood 零误报。Level 2 Spec, post_spec R1/R2→落地→R3 PASS 收敛。Skills 不变 (41)。

## [1.42.0] - 2026-06-10

### archive-completeness-gate (#134) — 禁止归档"仅 Phase A 收敛、实施未做"的 spec

Fixes Aria [#134](https://forgejo.10cg.pub/10CG/Aria/issues/134) (triage `partial-repro`, [comment-11974](https://forgejo.10cg.pub/10CG/Aria/issues/134#issuecomment-11974)): 归档闸门四漏洞 — (a) Level 2 无 tasks.md 即无 gate; (b) checkbox 全勾 ≠ 实施完成; (c) `skip_verification`/`--force` 无痕绕过; (d) state-scanner 无 converged-but-unimplemented 区分, 活体案例 block-flip (`Status=DEFERRED`→`unknown`) 端到端静默逃逸。设计 SOT: `docs/decisions/DEC-20260609-001-archive-completeness-gate.md` (brainstorm 4 决策 + post_brainstorm 19-agent/3 轮 + post_spec 25-agent/4 轮 + verification 2 轮 PASS)。

- **`state-scanner/scripts/lib/`** (new package, 契约 A 单一可执行 complete SOT):
  - `spec_complete.py`: `is_spec_complete(spec_dir) -> {complete, reason}` 纯函数 + thin CLI (JSON + exit 0/1/2)。`complete := (tasks.md 存在 AND 全[x] AND 无 carry-forward 注释) OR (normalized Status == 'done')`; tasks.md absent → 仅 Status 决定 (堵 gap-a vacuous truth); **archive-ready={done} only** — `implemented` (=awaiting verify) 不放行, 防 gap-b 等价重开。三入口同 verdict: scan.py import + openspec-archive Step1 / phase-d-closer D.2 经 Bash 调同一脚本。
  - `carry_forward.py`: `_CARRY_FORWARD_RE` + `_extract_carry_forward_annotations` 从 `collectors/openspec.py` 物理上移 (regex 单一来源, 消除 spec_complete↔openspec 循环引用; openspec.py 双上下文 re-export 向后兼容)。
- **`collectors/openspec.py`** (契约 B 消费侧 + D3 surface):
  - archive 循环读 proposal.md frontmatter `archive_type` → `archive_items[].archive_type: str|null` (additive; stdlib-only fail-soft, soft_error key=`archive_type_unreadable`)。
  - 新增 `design_deferred[]` surface 字段: 谓词 `¬complete ∩ (unknown ∪ (approved ∧ staleness≥30d) ∪ {reviewed,active,implemented})`; staleness = frontmatter `updated-at` 优先 / mtime 回落, N=30 hardcode。fresh-approved (<30d) = 合法在飞态不卷入; `{in_progress,ready,pending}` 由 priority_items 别处 surface。complement-invariant 4 合法桶无第三态 (verification r1 抓出 fresh-approved 黑洞 → r2 数学封闭 11 态 + 真树绿跑)。
  - `pending_archive` 保持 `st=='done'` + 注释锚定 `_normalize_status` 唯一 SOT。
- **`openspec-archive/SKILL.md`** (D1 写入侧 gate): Step1 = already-archived 前置 abort → Bash 调 `spec_complete.py` 完成 gate (不再 AI 解释 prose) → 默认 BLOCK; `--archive-design-only` + `reason` (≥10 非空白) 逃生舱; Step2 三路径 (正常更新 Status / design-only 仅 frontmatter 追加 `archive_type: implementation-deferred` + `archived_reason` / dry_run 不写); dry_run 三路输出 (示例 3a-3d); `--force` DEPRECATED; `skip_verification` 收口 (仅跳 checkbox 校验不绕 Status gate; 旧用法 WARN+abort 不静默降级)。
- **`phase-d-closer`** (堵 gap-a Level 2 旁路): D.2 `skip_evaluation` 三路 (无活跃→skip / `spec_complete.py` exit≠0→skip 不归档 / complete→进归档), SKILL.md + references/execution-steps.md 同步, 删旧裸 `has uncompleted tasks` 判定。
- **standards** (D4 惯例显式废弃): phase-d-closure.md Step10 五处 (完成判定移入 Execution 第 1 步 + §2 checklist 改 L2/L3 分支条件句 + `--no-validate` DEPRECATED) + README.md D.2 加 "(requires implementation verified, not Approved-only)" + project.md 生命周期图改图 (archive 前置条件 + Approved→[design-only]→archive 支线 + 废弃直接 Approved→archive)。新规: **归档 = 功能完成; 设计定稿是 in_progress milestone 非归档理由**。
- **Schema**: `state-snapshot-schema.md` 两 additive 字段 (`archive_type` + `design_deferred`) 注释 + backward-compat 子表; **不** bump `snapshot_schema_version`。`operations.md` 漂移修正 (values 枚举按 `_normalize_status` 真实 codomain; condition `status == done`)。
- **Tests**: 32 新测 (697→729) — spec_complete 真值表 19 + design_deferred/round-trip/invariant 13; 真树 dogfood: block-flip 落 `design_deferred` ✅, 3 个 fresh-approved spec 不卷入 ✅, 100 历史 archive 零误报 ✅。Rule #6 deterministic substitute。Skills 不变 (41)。

## [1.41.0] - 2026-06-08

### aria-submodule-gate-operationalize TG-2 (R-fix-2) — tripwire host-cron migration

**Completes the Spec** (TG-1 shipped v1.40.0). The post-merge tripwire workflow failed 5/5 dispatches (runs #7–#11): the Forgejo Actions runner cannot clone the `ssh://forgejo@...` submodules (no forgejo credentials; forgejo behind Cloudflare Access); `actions/checkout@v4 submodules:true` fails ~6s. Per-run logs unreachable via API (404) + web (CF) → root cause tentative-confirmed via evidence chain (Spec task 2.0 degraded path). **OQ2=(c): migrate to host-cron.**

- **`scripts/submodule-tripwire-audit.sh`** (new standalone): faithfully ports the workflow's inline audit — HEAD~1-vs-HEAD per-submodule gitlink ancestry (`ls-tree` SHAs + `merge-base --is-ancestor`; first-time/removed/no-change skip; `cat-file -e` guard avoids false MISS on incomplete fetch). Writes `submodule-gate-misses.jsonl` heartbeat (`tripwire_run`) + miss (`tripwire_miss`, additive superset — no strict-schema consumer). Optional dry-run / Forgejo issue-filing. `set -u` empty-array guard (portable to old Bash on uncontrolled host). Runs via host cron where forgejo IS reachable (§Install), sidestepping the runner→forgejo wall.
- **`.forgejo/workflows/submodule-gate-tripwire.yml`** (Aria main repo): marked DEPRECATED-for-execution with migration banner → host-cron script. v1.29.0 `schedule:` cron NOT added (block-flip deferred; host-cron supersedes).
- **Dogfood**: ran on the real Aria repo → exit 0 clean + wrote the FIRST successful tripwire telemetry record (vs the Actions runner's 5/5 failures).
- **Tests**: 10 new (`test_submodule_tripwire_audit.sh`: forward-clean / backward-MISS / divergent / dry-run / no-.gitmodules / no-change / multi-submodule) = Rule #6 substitute. Zero regression: gate replay 13/13.
- **Code-review**: Phase B.2 PASS — I-2 (empty-array guard) + M-2 (real newlines in issue body) + M-4 (cat-file -e false-MISS guard) + M-3 (multi-submodule test) applied; I-1 (misses.jsonl additive superset, no consumer) confirmed.

**TG-1 + TG-2 complete → Spec `aria-submodule-gate-operationalize` archived.** block-flip mechanism-level unblocked (gate records executions [TG-1] + tripwire runnable [TG-2]); restart needs ≥3 real executions accumulated + tripwire green (owner). Skills unchanged (41; adds a standalone script, not a skill).

## [1.40.0] - 2026-06-07

### aria-submodule-gate-operationalize TG-1 (R-fix-1) — gate telemetry in git-direct ship

**Trigger**: block-flip D+14 defer — submodule pointer regression gate recorded 0 executions over the 14-day window (10 PRs merged, but git-direct gitlink bumps bypass the phase-c-integrator flow that runs the gate). This ships TG-1 (R-fix-1) so git-direct ship accumulates gate telemetry. TG-2 (R-fix-2 tripwire runner failure) remains infra-gated.

- **`submodule_gate.sh`**: new `submodule-gate-executions.jsonl` — every gate invocation appends one record (incl. PASS / forward-bump / no-change), so `total_gate_executions` is a DIRECT count rather than inferred from warns+blocks+overrides+PR-merge推算. `log_execution` at Summary derives overall verdict (PASS/ALLOWED/BLOCK/ERROR). Additive; existing 4 telemetry files + 13-scenario replay test unchanged.
- **`hooks/submodule-gate-telemetry.sh`** (new PostToolUse Bash hook, OQ1=(a′)): on a `git commit` whose HEAD touches a submodule gitlink (awk-anchored on raw mode columns `:160000`/`160000` — not a substring grep, so paths/SHAs merely containing "160000" can't false-trigger), runs the gate in forced WARN mode (`timeout 15` wrapper) → records the execution. PostToolUse → structurally cannot block (zero lockout risk); three no-op guards (non-commit / no `.gitmodules` / non-gitlink commit) prevent telemetry noise. CRLF-safe (`jq | tr -d '\r'`).
- **`hooks.json`**: registered PostToolUse Bash entry (timeout 20).
- **Constraint honored**: does NOT reroute git-direct ship through phase-c-integrator (agent-team over-engineering guard).
- **Tests**: 7 new (`hooks/tests/submodule-gate-telemetry.test.sh`: gate PASS execution recorded + hook trigger + 4 no-op cases incl. path-containing-160000) = Rule #6 deterministic substitute. Zero regression: gate replay 13/13, secret-guard 225, secret-scan 47, crlf-shim 8, jq-crlf-guard 7.
- **Audit**: post_spec 2-round CONVERGED (R1 qa REVISE [AC path-specific→drift] → Rev1 AC path-agnostic → R2 unanimous PASS 3/3). Phase B.2 code-review PASS (0 Critical/0 Important; Minor #1 anchoring + #2 timeout fixed).
- Spec `aria-submodule-gate-operationalize` stays in `openspec/changes/` until TG-2 ships. Skills unchanged (41; this adds a hook, not a skill).

## [1.39.0] - 2026-06-05

### state-scanner-git-operation-awareness (#135) — interrupt collector 检测 git rebase/merge-in-progress

**Cycle**: state-scanner-git-operation-awareness (#135) — triage `confirmed`/`major`/`next-cycle` → Phase A (post_spec 2-round CONVERGED) → Phase B full cycle (TG-A/B/C + 21 测 + dogfood + code-review)

**问题**: `/state-scanner` 的 interrupt collector (`collectors/interrupt.py`) 只读 `.aria/workflow-state.json`，**检测不到 git 层 in-progress 操作** (rebase/merge/cherry-pick/revert/bisect)。dogfood 实证 (#133 ship 遗留的暂停 rebase)：仓库实际处于暂停 rebase (`.git/rebase-merge/` 存在)，但 snapshot 报 `interrupt.status=none` 且 `detached_head=False` (rebase 暂停态 `git branch --show-current` 仍返回 master) → 阶段 2 可能给出 checkout/分支推荐破坏中间态。

**TG-A — `git.py` 采集 `git_operation_in_progress`**:
- 新增 `_detect_git_operation` (+`_resolve_git_dir`/`_rebase_detail`/`_has_unmerged`)。经 `git rev-parse --git-dir` 取 git dir (superproject 返回相对 `.git` → 显式 `is_absolute()` 后 join project_root，不依赖 CWD；worktree/submodule gitfile 间接返回绝对路径)，检测 `$GIT_DIR/` 标记：`rebase-merge`/`rebase-apply`→rebase, `MERGE_HEAD`→merge, `CHERRY_PICK_HEAD`→cherry_pick, `REVERT_HEAD`→revert, `BISECT_LOG`→bisect；优先级 rebase>merge>cherry_pick>revert>bisect。
- additive 字段 `git.git_operation_in_progress {operation, has_conflicts, detail}`。`has_conflicts` **条件求值** (仅 `operation != none` 才跑 `git diff --diff-filter=U`，省 clean 仓库常态开销)。fail-soft 双 soft_error kind (`git_dir_unresolved` / `git_operation_probe_failed` / `unmerged_probe_failed`)，不阻断其余 git 采集。

**TG-B — 阶段 2 消费 (与 `interrupt.status` 正交，不篡改)**:
- `RECOMMENDATION_RULES.md` 新增 `git_operation_in_progress` 规则 (**priority 0.5 最高**) + `references/rules/advanced-rules.md` 详细 YAML block：`operation != none` → 降级/阻止含 checkout·分支操作的常规推荐，引导先 `git <op> --continue`/`--abort`，`has_conflicts=true` 措辞升级。
- `SKILL.md` 阶段 0 + `references/recommendation-stages.md` prose 描述 git 操作安全闸。

**TG-C — schema + 6 文档同步 (Rule #3)**:
- `references/state-snapshot-schema.md` 记录新字段 + 明确 `snapshot_schema_version` 保持 **"1.0" 不 bump** (nested optional additive)。
- `references/phase-1-collectors.md` git 行注新子字段；`references/interrupt-recovery.md` 决策树补 git 层并行感知分支 + "两路信号正交、互不篡改" 边界。

**测试 + 质量**:
- **21 新测** (16 `test_git_operation_detection.py`: 6 单标记 + 2 多标记优先级 + worktree git-dir + 真冲突/合成无冲突 + fail-soft + wiring AC-1/AC-3; 5 `test_git_operation_rule.py`: 规则结构性存在 + 字段引用 + has_conflicts 升级 + 正交)。**712 全绿零回归** (唯一 `test_normalize_snapshot` 失败为 time-ago 跨分钟 timing flake，本 cycle 未触碰，隔离复跑 PASS)。
- **dogfood**: 真 rebase 中间态跑 `scan.py` → `operation=rebase` + `detail="refs/heads/master; onto a9665fb"`，复算 triage case-1 (由报 none 变为报 rebase)。
- Rule #6: deterministic/structural skill substitute = collector 单测 + 规则结构性测试 + dogfood (per `feedback_deterministic_structural_skill_rule6_substitute`)；description 未改 → 无需 /skill-creator AB。
- **post_spec 2-round CONVERGED** (R1 REVISE/PWW 5-agent → Rev1 关全部 4 OQ + 锁 TG-B 三落点 + 写实 AC-2/AC-3/AC-5 → R2 全票 PASS 5/5，全部 R1 findings 撤回)。Phase B.2 code-review PASS (0 Critical/0 Important，Minor #1 `_has_unmerged` rc!=0 soft_error 已补)。

**向后兼容**: ✅ 纯 additive；clean 仓库 `operation:"none"` 行为与 v1.38.0 完全一致。Closes Forgejo Aria #135。

## [1.38.0] - 2026-06-03

### state-scanner-output-cap-hardening (#71 + #72) — 输出字段骨架 + 分支扫描上限可配置

**Cycle**: state-scanner-output-cap-hardening (#71+#72) — Phase A (Approved 2026-06-01 R2 unanimous) → Phase B full cycle (OQ3 owner warn-only / OQ4 reconcile 10 核心块)

**TG-B (#71) — `MAX_BRANCHES_SCANNED` 三层可配置**:
- `collectors/_common.py` 新增 `resolve_max_branches_scanned(project_root) -> int`，结构镜像 `resolve_forgejo_hosts` 的 env > config > default 优先级链，但显式处理 int 域 footgun：env `ARIA_HANDOFF_MAX_BRANCHES` (try/except 非数字) / config `state_scanner.handoff_multibranch.max_branches` (`isinstance int and not bool` 拒 bool 子类陷阱 + 拒 float/str) / 每层独立 `≤0 → 回退下一层` (env="0" 落到 config 非 default) / default 20 (向后兼容)。
- **上界 warn-only** (OQ3 owner 决策 2026-06-03)：超推荐上界 500 仅 `log.warning` 并**返回用户原值**，绝不静默 clamp / 改写用户意图。
- `collectors/handoff_multibranch.py` 移除硬编码 module 常量 `MAX_BRANCHES_SCANNED` (无外部引用)，改 per-run resolver；cap soft_error 文案 / docstring / 注释全同步动态值。
- `.aria/config.template.json` 文档化 `state_scanner.handoff_multibranch.max_branches` (3 层优先级 + 上界 warn-only 说明)。大仓 (远程分支 > 20，实证第三方仓 440) 调高此值根除 `handoff_multibranch_branch_cap` 软警告 + multi-terminal 看板静默失效 (覆盖 20/440 < 5%)。

**TG-A (#72) — 输出字段层骨架 + 防再漂移**:
- `SKILL.md` 输出格式 L146 从「区块名清单」扩为 **10 条带 ` — 关键字段` 的编号骨架** + 条件子块注 (README同步/Forgejo配置/插件依赖/Skill-AB)。根因：v1.32.0 progressive-disclosure 把字段级骨架移到 `references/output-formats.md`，AI 不读 reference 就只能凭记忆补字段 → 字段层漂移。降级原则保留。
- **OQ4 reconcile (TG-A.0 锁定)**：canonical = 10 核心块不 collapse；README/Forgejo/插件依赖/Skill-AB 为条件子块。10 块在 output-formats.md 全部已存在 → `references/output-formats.md` **不动** (符合 out-of-scope，它没坏)。
- **自动 sync-check 测试** `tests/test_output_format_sync.py` (6 测)：断言 10 canonical header 在 SKILL.md 骨架与 output-formats.md **双向一致出现** + 块数=10 + 每块有字段分隔符 → 把「格式完整性」变成确定性断言，补上 v1.32.0 AB 漏测的根因 (progressive-disclosure 再漂移防护)。

**测试 (Rule #6 deterministic/structural substitute)**: `tests/test_max_branches_resolver.py` 39 测 (35 resolver: env/config/default/int 域 fail-soft/边界/上界 warn-only/直接层解析器 + 4 cap-application monkeypatch: default/env override/config override 不触发/<cap 不触发) + `tests/test_output_format_sync.py` 6 测。全量 **676 测 green**，零回归 (一过性 `issue-cache-freshness` timing flake 已诊断排除，与改动无关)。Skills 不变 (34 user-facing + 7 internal = 41)。Closes Forgejo aria-plugin #71 + #72。

## [1.37.0] - 2026-05-31

### concurrent-session-upm-safety (#133) — 并发多 session UPM/handoff 安全

**Cycle**: concurrent-session-upm-safety (#133) — Phase A (合并双 Spec + (a)/(c) re-audit CONVERGED) → Phase B full cycle

**主解药 (convention, standards)**:
- 新建 `standards/conventions/concurrent-session-write-safety.md` — 并发安全写法约定 (Problem-1: 共享区 append-friendly / per-session 隔离 / followup sub-row / bare-pointer 单写) + AI 记录外部状态硬证据自律 (Problem-2: 禁 updated_at 软代理, 引 RETURNING/exit-code/显式 timestamp)
- 因果定位 (audit C1): PR merge thrash 是 write-time git 冲突, advisory 检测拦不住, convention 结构改写才是 forcing function

**辅助早发现 (advisory, advisory-over-hardlock)**:
- `tracks_multibranch.collision` 持久化字段 (additive): 新建 `lib/collision.py` 单一真理源 `classify(tracks)->{kind,groups}` (cross_owner/self_multi_container/none), collector 持久化, renderer 改读 (消除 phantom-field 分叉)
- 切口2: state-scanner 推荐规则 1.54 `concurrent_churn_detected` — collision.kind!=none 且 coordination.enabled==false → advisory (与 phase1_gate 按 enabled 严格互斥)
- 切口1: phase-d-closer D.1 `fetch_gate.py` — 写 UPM 前 fail-soft fetch + behind-check (触及 UPM→强提示), credential 不泄漏 + null-guard

**测试 (Rule #6 substitute)**: collision 16 tests (含真实-collector fixture) + fetch_gate 11 tests; convention dogfood AC-D1~D4 翻转对照。

## [1.36.0] - 2026-05-30

### Added / Fixed — `shell-jq-crlf-hardening` (#132 follow-up): systematic Windows-CRLF hardening of jq consumption

**Why**: #132 (secret-guard fail-closed on Windows) was one instance of a class — Windows native jq emits CRLF, and bash consumers strip only `\n`, leaving `\r` on every captured value. This Spec hardens all plugin shell scripts + builds a regression moat.

**CR-handling decision table** (gate/comparison value → strip; data body / jq -n constructor → leave):
- `secret-scan.sh`: type-check (:116) + tool (:118) strip trailing CR — under CRLF the type gate tripped and silently SKIPPED redaction (secret leak). `content` (:123) is the data body reinjected to the LLM → **NOT stripped** (blanket strip would corrupt user content; Spec C2, caught by post_spec audit pre-implementation).
- `setup_relay.sh`: injected statusLine `__aria_cwd` (cwd gate → cache write), `used`/`model` bar values, and install-detection `cmd` → strip CR. The jq→file writer needs no change.
- `check_context_relay.sh:53` `cmd`: defensive strip (detection empirically robust to trailing CR).
- `check_secret_guard_install.sh:74-76`: display strings (cosmetic).
- check_parity boolean captures + JSON accumulators: verified `jq --argjson` tolerates `true\r` (RFC 8259 whitespace) → no change.

**Regression moat**:
- `hooks/tests/lib/crlf-shim.sh` — reusable cross-platform CRLF test framework (awk re-appends `\r\n` per line to simulate Windows native jq; covers readarray-pipe + command-subst shapes; bidirectional self-check; silent-bypass two-state assertion). Self-test 8/8.
- `hooks/tests/jq-crlf-guard.sh` — scans production scripts for unguarded jq read-consumption; allowlist (`jq -n` / `# crlf-ok` / verified-safe T3); test-phase landing (not pre-commit). Self-test 7/7, clean on 14 files.
- `standards/conventions/shell-jq-crlf-hygiene.md` — decision table + positive patterns + exceptions + #61/#131/#132 same-family list.

**post_spec audit**: challenge mode, 3-round CONVERGED (R1 2 REVISE / 2 Critical → Rev1 → R2 code-reviewer PASS + qa REVISE / 1 NEW Major → Rev2 → R3 PASS). Caught 2 load-bearing Critical pre-implementation (C1 non-vacuous bidirectional assertion for silent-bypass; C2 content-body corruption).

311 shell assertions PASS (secret-guard 225 + secret-scan 47 + crlf-shim 8 + guard 7 + setup_relay 13 + check_context_relay 3 + check_secret_guard_install 8); Linux LF zero regression. Closes Forgejo Aria #132 follow-up. Skills unchanged (34 user-facing + 7 internal).

## [1.35.0] - 2026-05-30

### Added — `emergency-hotfix-and-audit-file-scope` (#58): prod hotfix lane + audit file-scope filter

**Why** (SilkNode hotfix PR #268, prod cron 5-day silent failure): prod 紧急修复必须 lighter weight, 且 audit 应按 file scope 而非仅复杂度 Level 调节严格度。**triage** (filed v1.16.0, 现 v1.34.x, 18 minor drift): sub-item #3 (推荐 adaptive_rules) **已是 v1.34.0 默认 → 关闭**; 本 release 做剩 2 gap。

**#1 emergency hotfix lane (advisory)**:
- **state-scanner** 新 `emergency_hotfix` 规则 (priority 1.85 < quick_fix 2; **主触发 `hotfix/*` 分支**, commit `hotfix(` prefix corroborating; confidence 85% / auto_execute No) — 双写 basic-rules.md + RECOMMENDATION_RULES.md。
- **phase-a-planner**: lane 概览 + 跳 Phase A.1-A.3。
- **phase-b-developer**: **Prod-Validated commit trailer 机检 gate** — hotfix 分支跳单测 (B.2) 时机械 grep `^Prod-Validated:` 存在性; 有 → 允许 manual prod validation 替代单测; **无 → block, 回标准 lane**。存在性机检 (防"忘记留证"); 内容真实性靠 owner PR review + audit trail。
- **audit-engine / phase-c-integrator**: emergency hotfix pre_merge audit (仅 `audit.enabled` + checkpoint != off) 降级 **convergence** (不 challenge)。C.2.4 CI gate **不豁免**。
- **standards/conventions/git-commit.md §6.4**: `Prod-Validated:` 单行 trailer schema (evidence 换行用分号) + hotfix commit 格式。

**#2 audit file-scope 二次过滤**:
- **audit-engine**: mode (checkpoints/adaptive_rules) 解析**后**, 当本次变更**全部** ⊆ `audit.scope_skip_paths` 时 → `min(resolved_mode, convergence)` (challenge → convergence; off/convergence 不变)。**降级而非 skip** (issue 实证 deploy script challenge 能找到 wget HTTP 4xx 退出 0 真退化 → deploy 不能全 skip)。变更文件 audit-engine **自取** `git diff --name-only $(git merge-base HEAD <base>)` (base 可配/`symbolic-ref`, fallback 全失 → skip+warn; **merge-base 而非 `HEAD`** —— pre_merge 时 hotfix 已 commit, `diff HEAD` 会漏已提交变更); `len==0` pass-through (防 vacuous-true)。仅 audit-on 项目生效。
- **config-loader**: `audit.scope_skip_paths` 默认 `["deploy/","docs/",".forgejo/workflows/",".github/workflows/","*.md"]` (目录 startswith / 后缀 endswith)。

**post_spec audit (3-round CONVERGED)**: R1 (3/3 REVISE, 3 Critical: file-scope 数据源错配 + Prod-Validated gate 无 enforcer + DEC-6 时机) → Rev1 → R2 (2 PWW + 1 NEW Critical: `git diff HEAD` pre_merge 漏已提交变更) → Rev2 (merge-base diff) → R3 (0 new Critical)。**连续 2 轮拦截 git 数据源/ref load-bearing 缺陷**。Phase B.2 code-review PASS (0 Critical; 1 Important "B.3→B.2 单测步骤" cross-skill drift 已修)。

**测试**: Rule #6 doc-existence structural fixture 10/10 PASS (behavior-conformance advisory/prose 标 dogfood-only)。

Source Aria [#58](https://forgejo.10cg.pub/10CG/Aria/issues/58)。DEC-20260530-002。Skills 不变 (34 user-facing + 7 internal = 41)。

## [1.34.1] - 2026-05-30

### Fixed — `secret-guard` CRLF fail-closed 阻断 Windows 全部工具 (#132, P0)

**Why**: v1.33.0 新增的 `hooks/secret-guard.sh` (PreToolUse `*` matcher) 在 Windows 上 100% fail-closed，锁死整个 session。Windows native jq builds 输出 CRLF，而 `readarray -t _sg_fields < <(jq -r '...' )` 只 strip `\n` 不 strip `\r` → 4 个字段 (`tool_type`/`tool`/`command`/`file_path`) 全染尾部 CR，`tool_type` 变 `"string\r"` 通不过 `[[ "$tool_type" != "string" ]]` type 校验 → exit 2 阻断**所有**工具 (Bash/Read/Edit/Write，仅 Grep/Glob 幸免)，且 `/plugin update` + `/reload-plugins` 无法恢复。误导性报错 `tool_name is type=string (expected string)` 自相矛盾，正是 CR 污染症状。

**Fix**: `secret-guard.sh:118` jq 管道尾部加 `| tr -d '\r'`，一处剥除全部 4 字段的 CR (embedded CR 对 secret-pattern 匹配无意义)。

**Test**: `hooks/tests/secret-guard.test.sh` +6 case — 1 shim sanity (确认注入 CR 非空洞) + 3 benign 工具放行 + 2 secret 仍拦截 (确认修复不削弱拦截)。用 CRLF shim (awk 每行补 `\r\n`) 在 Linux 忠实模拟 Windows native jq；非空洞验证 nofix→exit2 (bug 复现) / fix→exit0。**225/225 PASS**。

**同源**: 与 #61 (v1.21 GBK locale) / #131 (v1.30.3 None guard) 同属 aria-plugin Windows CRLF/编码边界 bug 家族。同类低severity 站点 (`aria-doctor/check_context_relay.sh`、`aria-context-monitor/setup_relay.sh` 的 `cmd=$(jq -r ...)` 单值模式 — `$()` 同样残留尾部 CR) 留 **L2 follow-up Spec** 系统性扫描 + cross-platform CRLF 回归框架。

Closes Forgejo Aria #132。

## [1.34.0] - 2026-05-30

### Added — `ai-native-estimator` (#18): Token 轴 cycle 工作量估算 (v1 薄切片)

**Why**: aria 传统估算建立在 4-8h 人工时假设上, 在 1 Human + Claude Code 模式下失效 (同一小时 AI 可产出 1 行或 1000 行)。v1 用 **Token (AI 侧 runtime-truth)** 替代, 先做能自动测的 Token 轴, 积累 variance 数据。

**新增 skill**:
- **`ai-native-estimator`** (user-facing) — 查询 API: `forecast(spec_level)` (N≥`min_samples`(3) → median(work_metric); N<3 → uncalibrated bootstrap; cross-level 隔离) / `history()` / `velocity(window=10)`。
- **`aria-token-telemetry`** (internal) 新增 `iter_transcript_usage(path) → list[{uuid, timestamp, session_id, usage}]` (additive per-turn 迭代器; 现有 `parse_transcript_usage` 不动)。

**采集机制 — phase-d-closer D.4** (v1.1.0 → v1.2.0): 收尾末位子步自动 capture 本 cycle token 消耗到 `.aria/estimator/variance.jsonl` (advisory, 非阻塞)。cycle 粒度 watermark `{last_uuid, last_timestamp, session_id, transcript_path}`; **幂等主机制 = 空区间** (重跑无新 turn → range 空 → skip); `cycle_id = {spec_slug}-{end_uuid[:8]}` (range 末 uuid 锚, cycle 内稳定)。

**数据模型**: `work_metric = output_tokens + cache_creation_input_tokens` (cache_read 排除, 是上下文重载非"工作"); variance.jsonl 存全部四 raw 分量 (work_metric 可重算)。`wall_clock_seconds` = 被动元数据 (**calendar-elapsed ≠ effort/workload**; 不进 forecast/work_metric; null-safe)。聚类键 = `spec_level`。

**config-loader**: 注册 `ai_native_estimator.{enabled:true, min_samples:3, window:10, bootstrap_seed:{L1:30000,L2:150000,L3:500000}}`。

**测试 (Rule #6 deterministic structural substitute)**: 40 tests (21 estimator covering all 11 Success Criteria + 19 token-telemetry incl 15 零回归)。

**post_spec audit (3-round CONVERGED)**: R1 (3/3 REVISE, 3 convergent Critical: `parse_transcript_usage` 复用错配 + transcript 字段未验 + cycle_meta 来源) → Rev1 (spike-verified transcript schema: uuid/timestamp/sessionId, 无数字 turn_index) → R2 (2 PWW + 1 NEW Critical: cycle_id 幂等自相矛盾, backend 发现 + qa corroborate) → Rev2 (幂等改 watermark 空区间) → R3 (2/2 PWW, 0 new Critical, CONVERGED)。**实施前拦截 2 个 load-bearing 缺陷**。Phase B.2 code-review PASS (0 Critical/0 Important, 3 Minor 全吸收)。

**v1 defer (DEC-20260530-001)**: Attention 轴 / L1+L2 预估 / task-planner 等 5 集成 / S/M/L/XL 替代 / per-task 粒度 / usd_cost / multi-terminal 并发写。

Source aria-plugin [#18](https://forgejo.10cg.pub/10CG/aria-plugin/issues/18) (依赖 #104 `aria-token-telemetry`)。Skills 33→34 user-facing + 7 internal = 41 total。

## [1.33.0] - 2026-05-29

### Added — `aria-context-monitor` (#104): 让 AI 机读 runtime-truth context 占用

**Why**: aria 十步循环 Phase B/C 实施期, AI 频繁需"继续推进 vs 暂停"决策, 最优依据是剩余 context 容量。此前靠"感觉"判断常失准 (实证 #104: 估剩 ~23% 实际 45%, +22% 偏差 → 不必要暂停)。

**新增 2 skill**:
- **`aria-context-monitor`** (user-facing) — 消费 telemetry, 返回结构化 occupancy (used%/remaining%/window + confidence + staleness)。决策阈值建议: <70% 继续 / 70-85% 找 commit boundary / >85% 建议暂停。**只提供数据, 不自动中断**。
- **`aria-token-telemetry`** (internal, `user-invocable: false`) — 共享数据层 (复用 git-remote-helper US-012 Layer 3 先例)。`scripts/token_telemetry.py` (stdlib-only): relay cache 读 (schema_version 校验 + JSONDecodeError/OSError→unavailable 防御) + transcript JSONL usage 解析 + window 4 档 resolve。raw counts 接口独立于 window% (#18 estimator 复用基础)。

**核心机制 — statusLine relay**: Claude Code runtime 渲染 statusLine 时 pipe 含 `context_window_size`/`used_percentage`/`model.id[1m]` 的 JSON 到 stdin。`scripts/setup_relay.sh` 幂等注入 relay 行 (marker 锚点检测 + 复用 `$input` + 注入在 `input=$(cat)` 后 + atomic `$$` tmp→rename) → 写 `.aria/cache/context-window.json` → telemetry 读。无 statusLine 时建最小 reference。

**3 档 fallback**: relay_cache (high, runtime-truth) > transcript_fallback (estimate) > unavailable。**口径分离**: relay 路径填 `used_percentage` (runtime total_input/window), transcript 路径填 `used_percentage_proxy` ((input+cache_read+cache_creation)/window) — 两者不混用 (根因修复 #104 22% drift)。**window 4 档**: cached_size_reuse > config > empirical_peak > default(200K)。staleness 默认 300s (config 可覆盖)。

**集成**:
- **aria-doctor v1.1.0 → v1.2.0**: 新增 `check_context_relay()` (`scripts/check_context_relay.sh`) — relay 3 态检测 (relay-installed / statusline-no-relay / no-statusline) + jq 可用性 + advisory。read-only。
- **config-loader**: 注册 `context_monitor.{staleness_threshold_seconds: 300, window_tokens: null}` namespace (DEFAULTS.json + config-example.md 文档)。
- **phase-b/c-developer SKILL.md**: 加 "Context 占用感知 (暂停 vs 继续)" 调用点 + 阈值建议 (advisory)。

**测试 (Rule #6 deterministic structural substitute)**: internal data-layer skill 不适用 LLM AB (per `feedback_deterministic_structural_skill_rule6_substitute`)。25 deterministic tests: `test_token_telemetry.py` 15 (relay fresh/stale/corrupt/schema-mismatch/missing-used% + transcript fallback/no-usage/raw-counts + window 4 档 + staleness) + `setup_relay.test.sh` 10 (inject/custom-bar-preserve/position/run-twice-idempotent/pre-existing-marker/minimal-reference/dry-run) + 6 fixtures at `aria-plugin-benchmarks/context-monitor/`。

**Phase A/B 闭环**: TASK-001 BLOCKING pre-Phase-B gate live-verified `context_window_size` 存在 (runtime 2.1.156) → 回退条款未触发。post_spec R2 PASS_WITH_WARNINGS converged (qa+tech-lead PWW + code-reviewer PASS)。Phase B.2 code-review PASS (0 Critical / 0 Important; 4 Minor 全吸收: `_from_relay` used_percentage 一致性校验 + schema.md total_input_tokens/exceeds_200k 口径注 + setup 退出码表)。

Closes Forgejo Aria [#104](https://forgejo.10cg.pub/10CG/Aria/issues/104)。关联 aria-plugin #18 (ai-native-estimator, 复用 aria-token-telemetry, 后续 cycle)。Skills 32→33 user-facing + 6→7 internal = 40 total。

## [1.32.0] - 2026-05-28

### Changed — `aria-skills-progressive-disclosure-restructure` 4 SKILL.md restructured per Anthropic /skill-creator guidance

应 owner 请求 + 按 Anthropic 官方 `/skill-creator` skill guidance (SKILL.md <500 lines, progressive disclosure pattern), 重构 4 个 user-facing SKILL.md + 1 个 RECOMMENDATION_RULES.md。3-iteration restructure (iter-1 → iter-2 → iter-3), AB benchmark 36 runs (24+12) 验证 progressive disclosure 工作如预期。

**Final SKILL.md sizes** (original → restructured):

- `audit-engine/SKILL.md`: 627 → **341** lines (-46%)
- `phase-d-closer/SKILL.md`: 502 → **199** lines (-60%)
- `aria-dashboard/SKILL.md`: 594 → **150** lines (-75%) 🏆
- `state-scanner/SKILL.md`: 670 → **317** lines (-53%)
- `state-scanner/RECOMMENDATION_RULES.md`: 1523 → **126** lines (split to 3 sub-files)

**全部 4 SKILL.md 现 well under Anthropic 500-line guidance**, 平均缩减 58%。

**15 new references/ sub-files**:

- `audit-engine/references/`: agent-dispatch-contract.md (Forgejo #126 contract, iter-1) + pre-write-validation.md (Issue #27 change_id check, iter-1) + execution-modes.md (4-stage execution + pre_merge gate, iter-2) + report-storage.md (5-field uniqueness schema + verdict 计算, iter-2)
- `phase-d-closer/references/`: handoff-mechanics.md (§D.3 4-level trigger + multi-track latest.md, iter-1) + execution-steps.md (D.1/D.post/D.2/D.3 step-by-step, iter-3) + usage-examples.md (3 scenarios, iter-3) + progress-update-details.md (single-pass vs milestone-driven, iter-3)
- `aria-dashboard/references/`: parse-rules.md (5 parser detailed rules, iter-1) + execution-flow.md (4-step generation flow, iter-2) + html-templates.md (7 HTML fragment templates + CSS class mappings, iter-2)
- `state-scanner/references/`: layer-l-integration.md (multi-terminal design intent, iter-1) + status-field-guide.md (11 lifecycle tokens + 首段截断, iter-2) + phase-1-collectors.md (16 collector sub-stages, iter-2) + recommendation-stages.md (阶段 2/3/4 推荐决策, iter-2)
- `state-scanner/references/rules/`: basic-rules.md + advanced-rules.md + operations.md (RECOMMENDATION_RULES.md split by category, iter-1)

**Content preservation**: ~99.8% byte-identical (Δ +50 lines across ~10K = new reference file frontmatter + 1-2 line SKILL.md cross-link summaries). 内容**原文搬迁**, 不删不改, 仅文件位置变更。

**AB Benchmark verified** (36 runs total):

- **Iter-1 (24 runs vs v1.31.0 baseline)**: tokens -0.4% (parity), time +0.3% (parity), output lines -11.9% (more concise)
- **Iter-2 (12 runs vs iter-1)**: tokens -3.9% (improved!), time -0.4% (parity), output lines -12.6% (more concise)
- **Cumulative vs v1.31.0**: tokens **-4.3%**, time parity, output **-23.0%**

Per-skill iter-2 results:
- aria-dashboard (-75% SKILL.md): -6.4% tokens, -7.8% time, **-33.6% lines** 🏆 (biggest reduction = biggest gain)
- state-scanner (-53% SKILL.md): -4.5% tokens, +2.5% time, -4.5% lines
- audit-engine (-46% SKILL.md): -0.9% tokens, +3.3% time, -1.9% lines

**Pattern**: Bigger SKILL.md reduction correlates with bigger AI improvement — progressive disclosure works as Anthropic guidance predicts.

**Verification**:

- Link integrity: 0 broken `references/` links across all 4 SKILL.md
- Tests: **631/631 PASS** (incidental fix: `normalize_snapshot.py` add `age_hours` to DROP_KEYS for stability test)
- Workspace artifacts: `.aria/skill-restructure-workspace/` contains iter-1/2 snapshots + 24+12 subagent outputs + benchmark.json + review.html (gitignored, dev-local)

**Rollback boundary**: iter-1 was committed separately at aria-plugin `80b8470` (this commit's predecessor). To revert iter-2+3 alone: `git revert HEAD~..HEAD`. To revert all restructure: `git revert <80b8470 commit> + this commit`.

**Rule #6 substitute** (per `feedback_deterministic_structural_skill_rule6_substitute` precedent — deterministic structural Skill restructure, no LLM AB needed as primary verification): byte-identical content extraction + 0 broken links + 631/631 tests + AB benchmark (used as supplementary verification per owner's `/skill-creator` 官方指引 request, exceeded expected positive outcome).

**Tests**: 0 new code tests (doc-only restructure). 631/631 PASS via normalize_snapshot.py incidental fix.

## [1.31.0] - 2026-05-28

### Added — `aria-ci-backend-abstraction` CI backend 抽象层 (Sprint 2 boundary audit P0 C5+C6)

Closes boundary audit P0 items C5+C6 (`.aria/notes/2026-05-27-boundary-audit-10cg-hardcode.md`). Ships Spec [`aria-ci-backend-abstraction`](../openspec/changes/aria-ci-backend-abstraction/proposal.md) (Approved 2026-05-28 via R1 REVISE × 2 + PASS_WITH_WARNINGS × 1 → Rev1 → R2 PASS_WITH_WARNINGS × 3 unanimous CONVERGED + Rev1.1 polish, L3 baseline per `feedback_audit_convergence_patterns`).

**Source**: 2026-05-27 aria-fleet strategic memo (`.aria/notes/2026-05-27-aria-fleet-three-layer-architecture.md` §4 边界切割规则) + 2026-05-27 boundary audit memo §修复 2 — 通用层禁止 hardcode 10CG-specific 假设 (Aether 唯一 CI 平台).

**Mechanism — new `ci_backends/` package** (`aria/skills/phase-c-integrator/scripts/ci_backends/`):

- **`base.py`**: `CIBackend` ABC (4 members: `name` ClassVar + 3 abstract `probe` / `query_pr_ci` / `query_branch_in_flight` + 1 optional `precheck`) + `CIStatus` dataclass + `InFlightStatus` dataclass (with `has_runs` property)
- **`aether.py`**: `AetherBackend` full migration from pre_merge_gate.py — `probe()` + `precheck()` + query methods. Behavior byte-for-byte preserved (Hard Constraint #1). Plus `AetherQueryError` exception.
- **`github_actions.py`**: `GitHubActionsBackend` stub — `probe()` real (`gh auth status`), `query_*()` raise `NotImplementedError`. Real impl deferred to v1.32.0+ next cycle.
- **`__init__.py`**: static `BACKENDS = [AetherBackend, GitHubActionsBackend]` (Aether-first precedence locked, Hard Constraint #8) + `cached_probe` + `reset_probe_cache` helper (Option B per Hard Constraint #11).

**`pre_merge_gate.py` refactor**:

- New `DEFAULT_CONFIG`: `ci_backends: null` (auto-detect) + `no_ci_fallback: "skip_with_warning"` (renamed)
- New `_normalize_config()` + `_translate_value()` — soft alias for legacy keys (`primitive_preference` / `no_aether_fallback`) with `DeprecationWarning`. Alias normalization runs BEFORE merge with DEFAULT_CONFIG (Hard Constraint #9 sequencing).
- New `resolve_ci_backend(config)`: `ci_backends: []` = explicit disable (AC-4.5); missing/null = auto-detect; non-empty list = user-specified order.
- `compute_verdict()` signature extended (Hard Constraint #10): now returns dict with `backend_name` param.
- `gate_check()` refactored: dispatch via `backend.precheck()` + `backend.query_branch_in_flight()` + `backend.query_pr_ci()`. Query order: main in-flight FIRST then PR CI SECOND (Rev1.1 per R2 ba N-1 — matches ground truth L309-329). NIE propagation (Hard Constraint #7): stub backend `NotImplementedError` MUST propagate (abort, NOT route to `no_ci_fallback`).
- Renamed `_no_aether_output()` → `_no_ci_output()`.

**Test suite (62 total, AC-7.2 ≥27 well-exceeded)**:

- `test_pre_merge_gate.py` — 37 tests: 21 rewritten (mock collapse) + 16 new (TestGHAStubAbortNotSkip + TestAliasKeyPath + TestBothKeysPresentNewWins + TestBackendRegistry + TestNormalizeConfigSequencing + TestProbeCacheIsolation)
- `test_ci_backends.py` — 25 new tests (TestCIStatus + TestInFlightStatus + TestCIBackendABC + TestAetherBackendProbe/Query/Precheck + TestGitHubActionsBackendStub + TestRegistry)
- **62/62 PASS** + state-scanner 631/631 zero regression verified

**Documentation updates**:

- `CLAUDE.md` Rule #8 L432-444 rewritten to backend-agnostic phrasing + Hard Constraint #7 NIE-propagation explicit + backward-compat alias note
- `aria/skills/phase-c-integrator/SKILL.md` ~14 references updated + new §C.2.4.X CI Backends section (~80 lines)
- `aria/skills/config-loader/SKILL.md` config schema entries updated with alias deprecation notes
- `standards/` zero touch verified

**Rule #6 substitute** (deterministic Skill per `feedback_deterministic_structural_skill_rule6_substitute`):

`aria-plugin-benchmarks/aria-ci-backend-abstraction/README.md` — structural fixture + 5 real-machine dogfood smoke evidence + AC behavior table (15+ rows). `/skill-creator benchmark` NOT applicable — no LLM prompt variable in deterministic Python refactor.

**Out of Scope** (explicit deferrals):

- GHA backend real implementation → v1.32.0+ next cycle (~4-6h L2 Spec)
- GitLab CI / Forgejo Actions backends → aria-fleet M7+
- GitProvider ABC → aria-fleet M7+ 主线

**Convergence indicators**:

- 3-agent independent surface (R1 post_spec): `_compute_verdict` undefined signature (tech F-03 + ba a3f8c2d1 + qa F-04) — substance convergence pattern
- R2 unanimous PASS_WITH_WARNINGS: agent withdrawal + verdict improvement + 无振荡
- Rev1.1 catch 1 paper-fix (ba R2 N-1 §B.4 query order) — meta dogfood

## [1.30.3] - 2026-05-28

### Fixed — defensive None guard in `_common.py::_run` (Forgejo Aria #131)

Closes Forgejo Aria [#131](https://forgejo.10cg.pub/10CG/Aria/issues/131) (state-scanner scan.py exit 30 on Windows CJK locale, AttributeError on `out.splitlines()`). 1-file fix.

**Root cause (already fixed pre-#131)**: missing `encoding="utf-8"` in subprocess wrapper — under Windows GBK locale, `text=True` would fall back to `locale.getpreferredencoding()` and crash on UTF-8 git output (commit messages with CJK / emoji per aria-standards `git-commit.md` 双语规范). **Fixed in Forgejo aria-plugin #61 (v1.21+, 2026-05-20)**. The Aria #131 report came from a v1.20.0 install — user only needs to upgrade.

**v1.30.3 belt-and-suspenders**: codifies the str-only return contract explicitly:

- `scripts/collectors/_common.py::_run`: return changed from `(p.returncode, p.stdout, p.stderr)` to `(p.returncode, (p.stdout or ""), (p.stderr or ""))` — defensive against any future subprocess thread race that surfaces None outputs despite `capture_output=True`.
- Docstring adds "**Contract guarantee**" section documenting stdout/stderr are ALWAYS strings (possibly empty), never None — callers can safely call `.splitlines()` / `.strip()` / `.startswith()` without explicit None checks.

**Verification**: smoke test with mocked `subprocess.run` returning `stdout=None, stderr=None` confirms guard emits empty strings; full 631/631 test suite unchanged.

**Forward-compat**: the None guard is a pure-defensive no-op under normal subprocess behavior (post-#61 `encoding=utf-8` ensures stdout/stderr are always strings). It only fires if Python's subprocess implementation ever changes / has a bug / is mocked with None.

**Tests**: 631/631 PASS (no new tests; inline smoke test verified mock-None scenario).

## [1.30.2] - 2026-05-28

### Fixed — multi-terminal-coordination 3-issue bundle (sandbox blockers + RECOMMENDATION_RULES + phase-d-closer multi-track)

Closes Forgejo aria-plugin [#57](https://forgejo.10cg.pub/10CG/aria-plugin/issues/57) (sandbox zero-day double: refspec invalid + PyYAML missing) + [#56](https://forgejo.10cg.pub/10CG/aria-plugin/issues/56) (RECOMMENDATION_RULES follower 推荐缺失) + [#67](https://forgejo.10cg.pub/10CG/aria-plugin/issues/67) (phase-d-closer D.3 latest.md History mechanical check). 6-file fix (4 code + 2 doc); 631/631 tests PASS.

**#57 Finding 1 — `coordination_fetch.py` refspec invalid**:

- `scripts/collectors/coordination_fetch.py`: replaced module-level constant `_FETCH_REFSPECS = ["refs/heads/*", COORDINATION_REF]` with function `_build_fetch_refspecs(remote)` returning `[f"+refs/heads/*:refs/remotes/{remote}/*", COORDINATION_REF]`. Wildcards in refspecs require explicit `src:dst` form per git-fetch(1); the single-src form produces `fatal: invalid refspec refs/heads/*` with rc=128. Call site at `cmd = ["git", "fetch", remote, "--no-tags", *fetch_refspecs]`.
- Live verified: `coordination_fetch.success=true` (was `false`), `refs_fetched=["+refs/heads/*:refs/remotes/origin/*", "refs/aria/coordination"]`.

**#57 Finding 2 — PyYAML dependency removed**:

- `scripts/collectors/handoff.py::parse_handoff_frontmatter`: replaced `yaml.safe_load` (PyYAML) with new private helper `_parse_simple_yaml_frontmatter(raw)` — 20-line stdlib-only parser handling flat `key: value` pairs with string-typed scalars (the §2.3.1 schema requires exactly 5 such fields, no nested/list/multi-line). Supports comment lines (`#`), blank lines, surrounding-quote stripping. **No datetime coercion** (ISO timestamps stay as strings — avoids v1.22.0 datetime zero-day bug entirely).
- `scripts/collectors/handoff_multibranch.py`: removed PyYAML availability probe + `handoff_yaml_unavailable` soft_error; module docstring updated to note stdlib-only parsing.
- Live verified: 93 non-legacy tracks parsed successfully on Aria dogfood (was 0 with PyYAML probe firing).

**#56 — RECOMMENDATION_RULES.md 3 multi-terminal rules**:

- `multi_terminal_follower_detected` (priority 1.51): detects follower role via `tracks_multibranch.tracks[]` lookup — current container has no `status==active` track but other container does. Recommends `standby-observer` workflow + info on leader's track/phase. `non_blocking: false` (strong signal).
- `follower_safe_tasks_suggested` (priority 1.52, triggered by 1.51): lists non-conflict candidate tasks (local hygiene / cross-repo / carry-forward / docs+audit) + explicit anti-suggestions (no new OpenSpec in active scope / no leader-track D.3 handoff / no submodule pointer bump). `non_blocking: true`.
- `multi_terminal_handoff_dual` (priority 1.53, D.3 phase): when multi-track + leader pointer still in latest.md, recommend follower writes **separate** handoff doc (slug with follower track-id) + cross-ref to phase-d-closer SKILL.md §latest.md 维护 子步骤 1+2 mechanical.

**#67 — `phase-d-closer/SKILL.md` §latest.md 维护 restructure**:

- Original §"latest.md pointer 更新" (single-track linear succession model, 3 lines) split into 2 mechanical sub-steps:
  - **子步骤 1 (always, 不可跳过)**: History 表格 prepend 新条目 (format + position rules: committerdate desc, leader 先于 follower 同日, scope-note classification)
  - **子步骤 2 (conditional)**: Pointer 行更新 — 3-row decision table based on `snapshot.tracks_multibranch` (single-track → update / multi-track + 主线 → update / multi-track + follower → DO NOT update)
- Edge cases documented (首个 follower / rebase resolve)
- Forbidden patterns extended: ❌ multi-track follower 跳过 History prepend (实证: nexus PR #107 漏 History entry, 后开 PR #109 补救) + ❌ multi-track follower 更新 pointer 行.

**Test stability fix — `normalize_snapshot.py`** (pre-existing test brittleness exposed by #57 fix):

- Added `last_fetch_at` to `TIMESTAMP_KEYS` (was static `<missing>` pre-#57 fix when fetch always failed; now legitimately moves forward each run).
- Added `cached`, `age_seconds`, `refs_fetched` to `DROP_KEYS` (TTL-based cache metadata varies between consecutive runs: run 1 fresh / run 2 cache hit). Unique to coordination_fetch namespace, no collision risk.
- `test_two_consecutive_runs_diff_zero` now PASS (was failing because my refspec fix made fetch actually succeed, exposing the cache-vs-fresh diff that was previously masked by uniform failure).

**Backward-compat guarantee**:

- v1.22.x+ frontmatter docs: parsed identically by stdlib parser (no semantic change)
- Legacy (no-frontmatter) docs: still graceful `legacy` fallback per §2.3.4
- coordination_fetch cache file format unchanged

**Out of scope**:

- PyYAML install hook / dependency declaration (Option A from #57 proposal): not needed since Option B (stdlib parser) eliminates the dependency entirely
- One-shot backfill of historical legacy docs with retrofitted frontmatter: deferred (collector gracefully handles legacy via `legacy: true` flag)

**Rule #6 substitute**: code changes covered by unit tests (`test_p1_layer_h.py` 4 frontmatter parse tests + 631/631 full suite); doc changes (RECOMMENDATION_RULES.md + phase-d-closer SKILL.md) follow `feedback_deterministic_structural_skill_rule6_substitute` precedent (deterministic structural Skill, no LLM AB needed).

**Tests**: 631/631 PASS (no new tests added — existing test_p1_layer_h.py coverage for parse_handoff_frontmatter sufficient; smoke-test inline verification done during fix).

## [1.30.1] - 2026-05-28

### Fixed — dashboard parser + audit-engine Agent dispatch contract (2-bug bundle)

Closes Forgejo Aria [#125](https://forgejo.10cg.pub/10CG/Aria/issues/125) (dashboard AB benchmark parser outdated) + [#126](https://forgejo.10cg.pub/10CG/Aria/issues/126) (audit reports missing YAML frontmatter — 42/105 invisible to dashboard parser). 3-file doc-only fix.

**#125 — dashboard AB benchmark parser dual-format**:

- `aria/skills/aria-dashboard/SKILL.md` §Step 1.5 + §5 parse-benchmark: parser 路径优先级改为 `benchmark.json` (新格式, /skill-creator 标准产出 since 2026-05-13) → `summary.yaml` (旧格式, 向后兼容). Glob 命中合并按目录名日期排序取最新。
- `aria/skills/aria-dashboard/references/data-schema.md` §5: 新格式 schema 完整记录 (metadata / configurations / runs[] / delta / live_verify / regression / notes) + 字段映射表 (metadata.timestamp[:10]→date, runs[?config in {post-fix, with_skill}].pass_rate→with_skill_pass_rate, delta.pass_rate→delta_pass_rate, delta.verdict→verdict). Verdict 阈值 fallback (≥0.5 STRONG_POSITIVE_DELTA / ≥0.2 POSITIVE_DELTA / ≥-0.05 NEUTRAL / <-0.05 NEGATIVE_DELTA) 当 `delta.verdict` 缺失时。
- **Source incident**: 2026-05-27 aria-dashboard dogfood (Aria 项目首次 generate dashboard), parser glob `*/summary.yaml` 在新格式 dir 命中为空 → fallback 到 2026-04-09 summary.yaml (1 skill +0.82 delta, 几乎一个月前), 跨项目 dogfood 时给 owner 误导印象 "benchmark 一个月没跑了"。

**#126 — audit-engine Agent dispatch contract + dashboard fallback parser**:

- `aria/skills/audit-engine/SKILL.md` §审计报告生成 新增 `Agent dispatch contract: 强制 frontmatter 输出` 子节: dispatched agent prompt **必须** 嵌入完整 frontmatter template (8 字段: checkpoint/mode/rounds/converged/oscillation/overridden_by_user/degraded/verdict/timestamp/context/agents), 原文嵌入不得简化. Phase Skills (a-planner / b-developer / c-integrator / d-closer) 调用 audit-engine 时, 由 audit-engine 自身负责注入指令, 调用方传 checkpoint/mode/context/agent_role 即可。
- `aria/skills/aria-dashboard/SKILL.md` §4 parse-audit: 加 markdown-header fallback (frontmatter 缺失时扫描前 30 行 `**Verdict**:` / `**Date**:` / `**Round**:` / `**Mode**:` / `**Checkpoint**:` / `**Converged**:` markdown header pattern; 字段未匹配时填 null; checkpoint 缺失时从文件名前缀 fallback 如 `post_spec-R1-...md` → `post_spec`; rounds 缺失时从文件名 `R{N}` 段 fallback; agents 缺失时从文件名 `-{agent_role}.md` 后缀 fallback; timestamp 缺失时退回 file mtime). 显式标记 `_source: "frontmatter" | "markdown_fallback" | "filename_fallback"` 供 UI 加 badge 提示数据完整度。
- **Source incident**: 2026-05-27 aria-dashboard dogfood: 105 audit reports 中 63 (60%) 有 frontmatter, **42 (40%) 无 frontmatter**. 更严重: v1.29.0 flip Phase A.2 用 Agent 工具触发的 6 个 audit (4 R1 + 2 R2) 全部无 frontmatter, dashboard 显示 "63 reports" 但实际 105, 最近 5 个 audit timestamp 反而几周前 (mtime 排序 fallback 异常)。supply-side (audit-engine prompt template) + consumer-side (dashboard fallback) 双向加固。

**Backward-compat guarantee**:

- 旧格式 summary.yaml 与新格式 benchmark.json 并存时, dashboard 跨格式 glob 合并, 取最新日期 (无 silent skip);
- 旧报告 (42 个无 frontmatter) 通过 markdown-header fallback 兜底可见, 字段不全用 null + filename 推断 + mtime 标记;
- 新报告 (2026-05-28+) 由 audit-engine 强制 frontmatter, fallback 主要服务历史报告。

**Out of scope**:

- One-shot backfill 历史 42 个无 frontmatter audit reports 写入 frontmatter (Issue #126 §Proposal Option C) — 推迟到独立 follow-up, 因 fallback 已兜底可见。
- audit-engine 自身脚本化 prompt template injection (当前依赖 audit-engine SKILL.md prose contract, 由 Claude Code 解读后注入 agent prompt) — 进一步 mechanize 是 v1.31+ 主线。

**Rule #6 substitute** (per `feedback_deterministic_structural_skill_rule6_substitute` precedent — deterministic structural Skill, no LLM AB needed): 2 bug 的 root-cause analysis + Issue #125/#126 dogfood evidence (105 reports / 63-with-frontmatter / 42-without count) + fix 后 SKILL.md prose contract direct 验证 (no test code, doc-only fix).

**Tests**: 0 new tests — 3-file doc-only fix (SKILL.md + references), no script logic changed.

## [1.30.0] - 2026-05-27

### Added — `aria-forgejo-hosts-parameterization` universal-layer Forgejo host config (env + .aria/config.json)

Closes boundary audit P0 items C1+C2+C3+C4 (`.aria/notes/2026-05-27-boundary-audit-10cg-hardcode.md`). Ships Spec [`aria-forgejo-hosts-parameterization`](../openspec/changes/aria-forgejo-hosts-parameterization/proposal.md) (Approved 2026-05-27 via R1 REVISE × 3 → Rev1 → R2 PASS_WITH_WARNINGS × 3 unanimous + Rev1.1 W-1 polish, Level 2 baseline per `feedback_audit_convergence_patterns`).

**Source**: 2026-05-27 aria-fleet strategic memo (`.aria/notes/2026-05-27-aria-fleet-three-layer-architecture.md` §4 边界切割规则) — 通用层禁止 hardcode 10CG-specific 值 (per aria-fleet DEC D2). 4 处 hardcode 阻碍 aria-plugin cross-org 复用,本 minor 修。

**Mechanism**:

- **New canonical resolver** `aria/skills/state-scanner/scripts/collectors/_common.py::resolve_forgejo_hosts(project_root)` — 3-layer precedence: `ARIA_FORGEJO_HOSTS` env (comma-separated) > `.aria/config.json` `state_scanner.issue_scan.platform_hostnames.forgejo` > legacy fallback `("forgejo.10cg.pub",)`. Used by all forgejo-aware collectors.
- **forgejo_config.py**: removed module-level `_KNOWN_FORGEJO_HOSTS` constant (architectural fix per R1 ba M-2: module-level execution can't access `project_root`). `_detect_forgejo_host()` signature changed to accept `known_hosts` param (injected by `collect_forgejo_config(project_root)`).
- **issue_scan.py `_load_config()`**: env override applied AS FINAL LAYER (after config.json merge, per Rev1.1 fix R2 ba W-1 / qa R2 minor — pre-merge placement would let merge loop silently overwrite env). Restructured to drop early-return so env override fires regardless of whether `.aria/config.json` exists.
- **issue_scan.py `_detect_platform()` Level 3**: removed `forgejo.10cg.pub` URL substring heuristic (L198) — eliminates dual-codepath drift risk; Level 2 `platform_hostnames` map is sole authority for forgejo detection. github.com Level 3 fallback retained (single universal host, not org-specific).
- **DEFAULTS.json**: `forgejo.10cg.pub` retained as legacy backward-compat fallback (DEC D2 compliance: D2 禁止**新增** hardcode, legacy fallback under parameterized wrapper allowed with deprecation roadmap M7+).

**Backward compat guarantee**: zero behavior change for existing installs without explicit env or config override — `forgejo.10cg.pub` still detected via DEFAULTS.json fallback path.

**Edge case handling**:

- `ARIA_FORGEJO_HOSTS=""` / `"   "` (empty/whitespace) → fall through to config/default (NOT silently disable)
- `.aria/config.json` `forgejo: []` (empty list) → fall through to default (avoid footgun)
- Duplicate hosts preserved (callers idempotent)

**Backward-compat config layer order** (highest precedence first): env > config.json > DEFAULT_CONFIG (Python) ≡ DEFAULTS.json (file).

**Tests**: 27 new unit tests (16 in `tests/test_forgejo_config.py` + 11 in `tests/test_issue_scan_helpers.py`); 631/631 full state-scanner suite PASS unchanged. Dual-path dogfood smoke verified: default path detects `forgejo.10cg.pub`, env override path with `ARIA_FORGEJO_HOSTS=alt.example.com` correctly returns `forgejo_remote_detected: false` (legacy host no longer in known_hosts).

**Rule #6 substitute** (per `feedback_deterministic_structural_skill_rule6_substitute` — deterministic structural Skill, no LLM AB): structural fixture at `aria-plugin-benchmarks/forgejo-hosts-parameterization/README.md` (4 hardcode 删/改 map + 12 AC behavior 表 + edge case cheatsheet + dogfood smoke evidence).

**Out of scope** (defer to Sprint 2+): C5+C6 CI backend abstraction (`pre_merge_gate.py`); C7 standards SSH URL; C8 aria-orchestrator PATH; Feishu 通知抽象; Git provider ABC (M7+ aria-fleet 主线).

## [1.28.0] - 2026-05-24

### Added — `aria-submodule-pointer-regression-gate` Phase C.2.4.5 (B+) hardened pre-merge gate (warn-only mode)

Closes Forgejo Aria [#124](https://forgejo.10cg.pub/10CG/Aria/issues/124). Ships Spec [`aria-submodule-pointer-regression-gate`](../openspec/changes/aria-submodule-pointer-regression-gate/proposal.md) (Approved 2026-05-24 via R1+R2 4-agent post_spec audit CONVERGED 3/3 unanimous + 0 new Critical).

**Source incident**: 2026-05-23 PR #123 in `10CG/Aria` rebased against master, conflicted on submodule `aria` pointer. Operator ran `git checkout origin/master -- aria` without a fresh `git fetch` in the same shell session — local `origin/master` ref was stale → staged pointer was old SHA → merge silently reverted 4 dev-claude2 commits (aria-plugin v1.24.1 + atomicity-guard + v1.25.0 + v1.26.0). Caught by post-merge audit + fast-forward fix `a8e0096` in ~10 min. Mechanical gate eliminates this failure mode.

**Mechanism** in `aria/skills/phase-c-integrator/SKILL.md §C.2.4.5` (new sub-step):

- **Hook point**: BETWEEN existing §C.2.4 (Rule #8 `aether ci status` gate) AND existing §C.2.5 (Multi-Remote Push). NO existing section renumbered — minimal-cascade insertion.
- **Pre-merge**: invoked BEFORE branch-manager merge API call, AFTER §C.2.4 CI gate passes.
- **Step 1 — fail-loud fetch**: `git fetch origin` with bounded retries (1s/2s/4s × 3). Exit-code-only abort (NO grep of success patterns — too fragile). On all 3 attempts failing → terminal block exit 2.
- **Step 2 — refspec assertion**: BEFORE/AFTER `git rev-parse origin/master` comparison. If origin/master moved non-ancestor (force-push history rewrite) → block exit 3 with operator confirm.
- **Step 3 — per-submodule loop**: enumerate from `.gitmodules`; per-submodule `git fetch` + `git ls-tree` + 双向 `merge-base --is-ancestor` to classify {PASS forward / REGRESSION / DIVERGENT}; nil-SHA (first-time submodule) handled as PASS+INFO; no-change handled trivially.

**Override mechanism** (per-PR explicit, NOT sticky config — mirrors Rule #7 `secret-leak-ok-explicit` philosophy):

- **Commit trailer** `Submodule-Rollback: <sub> <old>(→|->)<new> reason=<...>` — accepts both Unicode `→` and ASCII `->` (LANG=C/POSIX safety). SHA normalization via `git rev-parse` resolves short SHAs (≥7 chars). Mismatched SHAs rejected.
- **PR label** `submodule-rollback-approved` — settable only by repo maintainers via Forgejo API. On API failure, gate falls through to next check (no-label conservative).

**Two-phase rollout** (mirrors Rule #8 cadence):

- **v1.28.0** (this release): `mode=warn` default. Detection + logs `WOULD-BLOCK` to `metrics/submodule-gate-warns.jsonl`; does NOT refuse merge. 14-day observation window for ecosystem FP feedback. Minimum-observation guard ≥3 gate executions before flip.
- **v1.29.0** (planned, 14d hard date after v1.28.0 ship OR FP <2% over 20+ WOULD-BLOCK events): `mode=block` default. Refuses merge with exit 1.

**Telemetry** (JSONL race-safe via kernel atomic write < PIPE_BUF):

- `aria/metrics/submodule-gate-warns.jsonl` — WOULD-BLOCK events (warn mode) + `human_reviewed_as_fp` field
- `aria/metrics/submodule-gate-blocks.jsonl` — BLOCK events (block mode, post v1.29.0)
- `aria/metrics/submodule-gate-overrides.jsonl` — override usage (trailer or label)
- `aria/metrics/submodule-gate-misses.jsonl` — tripwire detections (post-merge regressions that escaped gate)

**Replay tests**: 13 assertions across 10 scenarios in `aria/skills/phase-c-integrator/tests/test_submodule_gate.sh`. All PASS at ship time:
1. Happy path forward bump
2. Pure regression (block mode + warn mode)
3. Divergent history
4. Stale-ref fetch recovery (clean + fetch failure)
5. Legitimate revert with trailer override (valid + mismatched)
6. No-change
7. First-time submodule (CRITICAL — qa R1 TEST GAP closed by Rev1)
8. Submodule removed from feature
9. Concurrent force-push race (deterministic pre-stage)
10. Detached HEAD submodule (Rev1 NEW)

**Tripwire** (post-merge mechanical detection of (B+) gate misses):

- Workflow: `.forgejo/workflows/submodule-gate-tripwire.yml` in `10CG/Aria` main repo (NOT `aria/cron/` in aria-plugin)
- v1.28.0: `on: workflow_dispatch` only (manual trigger for verification)
- v1.29.0: switch to weekly `on: schedule` cron (Sundays 04:00 UTC)
- On miss detected: append to `metrics/submodule-gate-misses.jsonl` + file Forgejo issue with `gate-tripwire-count` label
- Cron always writes `last_run_timestamp` (outage detection per R1 qa M-qa-3)

**Auto-promote (A) post-merge backward-move detector** (Spec §Risks codified pre-commitment): if any of (a) regression escapes (B+) within 12 months OR 100 merges, (b) (B+) fetch-failure incident manifests in audit logs, (c) non-PR-flow regression observed → ship (A) without re-brainstorm. Counter mechanism: mechanical `aria/metrics/submodule-gate-misses.jsonl` + monthly review by simonfishgit.

**Companion convention doc**: `standards/conventions/submodule-pointer-hygiene.md` v1.0.0 (zero-code, NOT numbered CLAUDE.md Rule — convention SOT lives in `standards/conventions/`).

**Rule #6 structural substitute**: `aria-plugin-benchmarks/submodule-gate/README.md` documents 10-scenario fixtures + dogfood evidence + atomicity guard. NOT `/skill-creator` LLM AB (wrong instrument for deterministic git plumbing) per `feedback_deterministic_structural_skill_rule6_substitute`.

**Brainstorm history** (DEC-20260524-002 + R1+R2+R3 audit trajectory):

- Brainstorm R1: 4 agents discuss 3 candidates (A post-merge / B pre-merge / C rebase hook); B unanimous accept, C unanimous REJECT as code (BLOCKER: no git hook injection point for `git checkout -- <path>` in interactive rebase)
- R2: tech-lead concedes A+B → B only (fail-loud fetch hardening closes 80% stale-ref gap); code-reviewer concedes B only → A+B (disjoint failure modes: post-merge reads tree-embedded SHAs immutable vs pre-merge reads mutable refs); ai-engineer (neutral 3rd) proposes unified anchor (B+) hardened + measured tripwire
- R3: 4/4 ACCEPT_R3 unanimous validate ai-engineer anchor + 3 Q-NEW MINOR (all spec-resolvable)
- post_spec R1: 4 agents, 4 Critical + 19 Important + 20 Minor (all addressed in Rev1)
- post_spec R2: 3 agents, **CONVERGED 3/3 unanimous + 0 new Critical** + 11 cosmetic Minors (batch-fixed Phase B.1)

**Risk class**: Backward-compatible per Aria 向后兼容 principle — v1.28.0 ships warn-only, gives ecosystem 14d to surface false positives before v1.29.0 block flip.

### Added — Convention doc + tripwire workflow + Rule #6 substitute

- NEW file `standards/conventions/submodule-pointer-hygiene.md` (v1.0.0) — 4 conventions (always fetch / no stale-ref checkout / use override for legitimate rollback / sequenced multi-repo gitlink bump)
- NEW file `.forgejo/workflows/submodule-gate-tripwire.yml` (draft, workflow_dispatch only in v1.28.0)
- NEW dir `aria/metrics/` + `.gitkeep` (telemetry append-only JSONL files added to `.gitignore` via file-extension-specific pattern `metrics/*.json` / `metrics/*.jsonl`)
- NEW dir `aria-plugin-benchmarks/submodule-gate/` with structural fixture README
- NEW helper `aria/skills/phase-c-integrator/scripts/submodule_gate.sh` (Bash, stdlib + git only, ~330 LOC)
- NEW test `aria/skills/phase-c-integrator/tests/test_submodule_gate.sh` (10 scenarios, 13 assertions, ~440 LOC)

### Updated

- `aria/skills/phase-c-integrator/SKILL.md`: added §C.2.4.5 section detail (~180 lines) + config table row + overview workflow block + minor §C.2.4 cross-ref
- `CLAUDE.md` 信息地图: added Submodule pointer 卫生 row (NOT numbered Rule)

### Migration

- **Backward-compatible**: existing PR workflows unaffected (warn-only mode). `mode=off` config escape hatch available for emergency bypass.
- **v1.29.0 flip preparation**: monitor `metrics/submodule-gate-warns.jsonl` during 14d window; file `submodule-rollback-approved` PR label + commit trailer practices for any deliberate rollback workflow.
- **Multi-terminal Layer L claim** (`refs/aria/coordination`): Phase B claimed `aria/skills/phase-c-integrator/SKILL.md` via Layer L for safe parallel editing.

## [1.27.0] - 2026-05-24

### Added — O8 closure: aria-doctor `--self-test` + `--help` user-facing flags (skill v1.0.0 → v1.1.0)

Closes v1.24.0 roadmap item O8 (per [Track D handoff §6](../docs/handoff/2026-05-23-aria-secret-guard-plugin-default-shipped.md) → roadmap burndown §6).

**New script flags** in `aria/skills/aria-doctor/scripts/check_secret_guard_install.sh`:

#### `--self-test`

Wraps the existing 8 unit tests (which previously required developers to directly invoke `aria/skills/aria-doctor/tests/check_secret_guard_install.test.sh`) with a user-facing diagnostic harness:

1. **Environment diagnostics** — bash / jq / python3 versions + hard-dep check (fails fast if jq missing)
2. **Live env check** — invokes the script itself on current `$CLAUDE_PROJECT_DIR` + derived plugin root, displays state + sub_flags + advisory excerpt
3. **Unit tests** — runs all 8 cases covering 5 primary states + 2 sub-flags + banner-missing edge
4. **Summary verdict** — `ALL PASS ✓` (exit 0) / `FAILURES detected ✗` (exit 1) / `test file not found` (exit 2, indicates plugin layout drift)

Usage:
```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/aria-doctor/scripts/check_secret_guard_install.sh --self-test
```

Recommended for:
- Post-install verification (after `aria-plugin` upgrade)
- Pre-bug-report sanity check
- CI canary monitoring (`aria-doctor` health in pipeline)
- Manual diagnostic when secret-guard behaves unexpectedly

#### `--help` / `-h`

Prints Usage block extracted from script header. Documents both check mode (positional `[PROJECT_DIR] [PLUGIN_ROOT]` with JSON output) and self-test/help flags. Useful for discovery + onboarding.

### Backward compatibility

- **Positional single-check mode unchanged** — `bash check_secret_guard_install.sh [PROJECT_DIR] [PLUGIN_ROOT]` still returns single-line JSON identical to v1.26.0
- aria-doctor skill schema (5 states + 2 sub-flags + advisory) unchanged — atomicity guard contract preserved
- Unknown flag (`--bogus`) rejected with exit 2 + helpful pointer to `--help` (no silent fall-through to positional parsing that might confuse with absent positional args)

### Test counts (unchanged)

- secret-guard.test.sh: 219/219 PASS
- secret-scan.test.sh: 44/44 PASS
- check_secret_guard_install.test.sh: 8/8 PASS (direct invocation)
- check_secret_guard_install.sh --self-test: 8/8 PASS + env diagnostics + live env check
- **Total: 271/271 PASS** (no test added; --self-test is a runner wrapper not new test cases)

### Why MINOR (not PATCH)

New user-facing script API (`--self-test` and `--help` flags). Although the underlying schema + check logic unchanged, adding user-callable subcommands is a feature addition consumer scripts may rely on. Per Aria SemVer convention.

### Companion changes

- `aria/skills/aria-doctor/SKILL.md` v1.0.0 → v1.1.0:
  - §Usage table: added `--self-test` and `--help` flag rows
  - §Tests: new "User-facing self-test (v1.27.0+)" subsection with usage example + recommended scenarios
  - §Version history: 1.1.0 entry

### NOT addressed in this release

- aria-doctor self-test cross-project verification (would require running it ON SilkNode / Aether / etc. installations) — deferred to O1 SilkNode P2.5 dogfood (parallel track)
- Static analysis / schema validation that the script itself emits valid JSON for all states — captured by existing 8 unit tests, no new test added

### Refs

- Roadmap item O8: `docs/handoff/2026-05-23-aria-secret-guard-roadmap-burndown.md` §6
- v1.26.0 predecessor: aria-plugin PR #62 SHA `8578609`
- SKILL.md companion: `aria/skills/aria-doctor/SKILL.md` v1.0.0 → v1.1.0

## [1.26.0] - 2026-05-23

### Performance — O3 closure: hook perf optimization (~5× cold-start, ~4× warm-path)

Closes v1.24.0 roadmap item O3. Reclaims the original 100ms performance budget that was relaxed to 400/150ms in v1.24.0 post-dogfood after empirical measurement found 337ms p95 on Bash path.

**Two structural changes** to `aria/hooks/secret-guard.sh`:

#### (1) Consolidated entry jq call

Before: 3 separate `printf '%s' "$input" | jq -r '...'` subshell invocations (type check + tool_name extract + per-branch command/file_path extract).

After: 1 `readarray -t < <(jq -r '...')` call extracting all 4 fields at entry. Per-line readarray (not `IFS=$'\t' read` with `@tsv`) preserves empty fields — tab is whitespace IFS, consecutive tabs collapse.

#### (2) Bash builtin `=~` regex in risky_patterns sweep

Before: `echo "$command" | grep -qE "$pat"` × ~100 patterns = ~100 subprocess forks per invocation.

After: `[[ "$command" =~ $pat ]]` — bash builtin, no fork. POSIX ERE compatible (no regex changes needed).

### Performance results (empirical, n=30 samples post-warmup)

| Path | v1.24.0 | v1.26.0 | Δ |
|------|---------|---------|---|
| Cold start (fresh shell) | 600-1400ms | **59-68ms** | -90% to -95% |
| Bash matcher warm p95 | 337ms | **76ms** | **-77%** |
| Read/Edit warm p95 | ~102ms | **41ms** | -60% |

**All paths comfortably under the original 100ms performance budget**.

### Verification

- secret-guard.test.sh: **219/219 PASS** (unchanged)
- secret-scan.test.sh: 44/44 PASS (unchanged)
- aria-doctor: 8/8 PASS (unchanged)
- **Total: 271/271 PASS** — zero behavior change, pure performance refactor
- Cold-start via `env -i HOME=$HOME PATH=$PATH bash` to defeat process cache

### Why MINOR (not PATCH)

Pure performance refactor of two hot code paths in security-relevant hook. Reclaims documented performance budget. Per Aria SemVer convention, structural hook refactor with measurable consumer-visible impact = MINOR+.

### NOT addressed in this release (deferred)

The remaining ~30 pre-loop `echo "$command" | grep -qE` filter checks (lines ~167, 243-335 — guard:ack detection, filter detection like jq/grep/sed/cut/awk, redirect detection) were NOT converted. They contribute ~30 × ~3ms ≈ 90ms of remaining overhead. v1.26.0 already hits budget; converting is deferred as low-priority polish (potential v1.27.x).

### Refs

- Roadmap item O3: `docs/handoff/2026-05-23-aria-secret-guard-plugin-default-shipped.md` §6
- v1.24.0 dogfood F1 finding: `openspec/archive/2026-05-23-aria-secret-guard-plugin-default/smoke-evidence.md` §1
- Performance budget originally set: v1.24.0 proposal.md §Impact (relaxed to 400/150ms post-empirical; this release reclaims original 100ms)

## [1.25.0] - 2026-05-23

### Added — O4 closure: Bash matcher regex extension for local `<reader> <key-file>` (closes v1.24.0 known-limit (c))

Closes v1.24.0 CHANGELOG known-limit (c) (F2 from TASK-007 dogfood 2026-05-23).

**Coverage extension** at `aria/hooks/secret-guard.sh` Bash branch `risky_patterns` array (1 new regex line at L369):

```
(cat|head|tail|less|more|strings|hexdump|od|xxd)[[:space:]]+[^|]*(id_rsa|id_ed25519|id_ecdsa|\.pem|\.key|\.p12|\.pfx|\.jks|\.gpg|\.age|\.tfstate|/\.aws/(credentials|config)|/\.kube/config|/kubeconfig)(\b|/|$|[[:space:]])
```

Previously these `<reader> <key-file>` patterns were ONLY blocked by:
- the SSH-wrapped variant (`ssh ... cat id_rsa`) at L398 of secret-guard.sh, AND
- the Read|Edit|Write|MultiEdit matcher file_path scan at L153

Now plain Bash invocations are also blocked, achieving **Bash↔Read matcher parity**.

**Pattern list** intentionally mirrors the Read|Edit file_path regex (line 153 of secret-guard.sh):
- SSH keys: `id_rsa`, `id_ed25519`, `id_ecdsa`
- PEM/key files: `*.pem`, `*.key`
- PKCS-12 / JKS: `*.p12`, `*.pfx`, `*.jks`
- GPG / age: `*.gpg`, `*.age`
- Terraform state: `*.tfstate`
- Cloud configs: `/.aws/credentials`, `/.aws/config`, `/.kube/config`, `/kubeconfig`

**Test coverage** (`aria/hooks/tests/secret-guard.test.sh`, +6 positive + 2 negative cases):

Positive (newly blocking, was allow per known-limit (c)):
- `cat ~/.ssh/id_rsa via Bash blocked` → exit 2
- `head /etc/ssl/private/foo.key blocked` → exit 2
- `tail /home/u/keys/cert.pem blocked` → exit 2
- `less /home/u/.ssh/id_ed25519 blocked` → exit 2
- `cat /home/u/.aws/credentials blocked` → exit 2
- `strings /tmp/cert.p12 blocked` → exit 2

Negative (regex must NOT over-trigger):
- `cat foo.keyfile.txt NOT blocked` → exit 0 (word boundary guards against `.key` matching inside `keyfile`)
- `cat README.md NOT blocked` → exit 0 (plain doc file)

Companion preserved:
- `Read id_rsa correctly blocked` → exit 2 (parity confirmation, Read matcher unchanged)

**Test counts post-fix**:
- secret-guard.test.sh: 214 → **219 PASS** (+5 net = +6 positive + 2 negative − 3 previous known-limit allow cases)
- secret-scan.test.sh: 44/44 unchanged
- aria-doctor: 8/8 unchanged
- **Total: 271/271 PASS**

### Notes

- v1.24.0 CHANGELOG `[1.24.0]` "Known limitations" item (c) remains in historical record (do not delete) but is now resolved as of v1.25.0; future projects encountering the cited workarounds should upgrade to v1.25.0+.
- Bash matcher coverage gap was discovered in v1.24.0 Aria-self dogfood (TASK-007 F2 finding), labeled-test pinned in v1.24.2 (qa M N2 closure), structurally closed in this v1.25.0 release per roadmap O4.
- Why MINOR (not PATCH): adds new detection patterns to risky_patterns regex (extends matcher coverage = new functional capability for security-relevant hook).

### Refs

- v1.24.0 dogfood discovery: `openspec/archive/2026-05-23-aria-secret-guard-plugin-default/smoke-evidence.md` §1 F2
- v1.24.2 labeled tests (predecessor): aria-plugin PR #60 SHA `0530db4`
- Roadmap item: O4 from `docs/handoff/2026-05-23-aria-secret-guard-plugin-default-shipped.md` §6

## [1.24.2] - 2026-05-23

### Fixed — O5 minor cleanup from v1.24.0 post_implementation R1 audit

Closes 4 of 5 actionable minor findings from
`.aria/audit-reports/post_implementation-R1-2026-05-23-aria-secret-guard-plugin-default-orchestrator.md`:

#### (a) backend-architect M2 — `python3` runtime dependency guard

`aria/skills/aria-doctor/scripts/check_secret_guard_install.sh::json_escape()` previously assumed `python3` unconditionally. On minimal containers lacking python3, the helper would silently produce empty advisory fields in the JSON output (other fields still ran through other code paths, leaving an inconsistent corrupt JSON).

**Fix**: prefer python3 → fall back to `jq -Rs .` (jq is already a required dep used by `settings_corrupted` check) → hard-error if neither available (loud failure, never silent corruption).

#### (b) qa M N2 — F2 known-limit (c) labeled regression tests

v1.24.0 CHANGELOG documents known-limit (c): Bash matcher does NOT catch local `cat | head | tail | less | more <key-file>` for SSH/PEM/PKCS-12 keys. Until v1.24.0, no test pinned this documented behavior — any future "fix" that accidentally blocks these patterns would ship without forcing the author to update CHANGELOG.

**Fix**: 4 new test cases in `aria/hooks/tests/secret-guard.test.sh`:
- `bash_case "known-limit(c): cat ~/.ssh/id_rsa via Bash" 0`
- `bash_case "known-limit(c): head /etc/ssl/private/foo.key" 0`
- `bash_case "known-limit(c): tail /home/u/keys/cert.pem" 0`
- `read_case "known-limit(c) companion: Read id_rsa correctly blocked" 2` (proves the gap is Bash-matcher-specific, not a general hook gap)

Test counts: secret-guard.test.sh **210 → 214 PASS** (+4 known-limit cases); secret-scan.test.sh **44/44** unchanged; aria-doctor **8/8** unchanged. Total: **266/266 PASS** post-fix.

#### (c) knowledge M N1 — `<date>` placeholder resolution in SKILL.md

`aria/skills/aria-doctor/SKILL.md` L17 + L190 had `openspec/archive/<date>-aria-secret-guard-plugin-default` placeholders left over from pre-archive Spec lifecycle. Resolved to `2026-05-23-aria-secret-guard-plugin-default` (the actual TASK-015 archive date).

#### (d) knowledge M N2 — CHANGELOG "3 new entries" wording clarification

v1.24.0 `[1.24.0]` "Hook registration ... 3 new entries" was ambiguous (PreToolUse array totals 3 entries including pre-existing handoff-location-guard, but the secret-guard additions are 2 PreToolUse + 1 PostToolUse). Reworded to: "+2 PreToolUse entries + 1 PostToolUse entry = 3 new entries; pre-existing handoff-location-guard PreToolUse retained".

### Not fixed in this patch (deferred)

- `knowledge M N1 (b)`: same `<date>` placeholder also exists in **standards/conventions/secret-hygiene.md §10** version-history entry — addressed in companion standards direct-master-commit (not part of this PR).
- `backend-architect M3`: atomicity-guard.md bidirectional regex forbid — addressed in Aria-main direct-master-commit (sibling).
- `knowledge M N2 (cosmetic-only items)`: tech-lead M1 VERSION line length / code-reviewer M2 internal accounting drift / qa M N1 timing variance investigation / backend-architect M1 by-design — defer per audit categorization.

### Refs

- Source audit: `.aria/audit-reports/post_implementation-R1-2026-05-23-aria-secret-guard-plugin-default-orchestrator.md`
- Roadmap item: O5 from `docs/handoff/2026-05-23-aria-secret-guard-plugin-default-shipped.md` §6

## [1.24.1] - 2026-05-23

### Fixed — GitHub Secret Scanning push protection allowlist (O6 from v1.24.0 roadmap)

Adds `.github/secret_scanning.yml` with `paths-ignore` for hook regression test files:

- `hooks/tests/secret-guard.test.sh`
- `hooks/tests/secret-scan.test.sh`

**Why**: These test files intentionally contain realistic-looking token patterns (sk_live_/ghp_/sk-silk-/Slack webhook URL/Postgres connection strings) to verify that `secret-scan.sh` + `secret-guard.sh` regex patterns correctly catch them. GitHub's secret scanning push protection cannot distinguish test fixtures from real tokens, so v1.24.0's initial GitHub push was blocked by 5+ `unblock-secret` URLs requiring per-fixture owner action.

**Result**: structural one-time config replaces per-push owner unblock-URL clicking + per-fixture sanitization workarounds. Production hook code, skill code, and documentation are NOT excluded — they should never contain real or fixture secrets. Per memory `feedback_github_secret_scanning_push_range_blocks_history` (recorded during v1.24.0 ship as the experience that motivated this fix).

### Fixed — plugin.json / marketplace.json description Skills count typo

Description fields updated `31个 Skills` → `32个 Skills` to match actual count after v1.24.0 added the `aria-doctor` skill (v1.0.0). README.md / VERSION already had the correct `32` count; this aligns the manifest descriptions. No behavior change.

### Refs

- Source incident: 2026-05-23 v1.24.0 GitHub push block ([handoff §3 risks table](../docs/handoff/2026-05-23-aria-secret-guard-plugin-default-shipped.md))
- Memory: `feedback_github_secret_scanning_push_range_blocks_history`
- Roadmap item: O6 from `openspec/archive/2026-05-23-aria-secret-guard-plugin-default/` v1.24.1+ list

## [1.24.0] - 2026-05-23

### Added — plugin-default secret-guard + secret-scan hooks (Layer 2 mechanical enforcement of Rule #7)

Spec `aria-secret-guard-plugin-default` (Forgejo Aria [#84](https://forgejo.10cg.pub/10CG/Aria/issues/84) + [#107](https://forgejo.10cg.pub/10CG/Aria/issues/107), parent decision [`.aria/decisions/2026-05-20-secret-rotation-during-m5-deploy.md §5`](../.aria/decisions/2026-05-20-secret-rotation-during-m5-deploy.md)). All aria-plugin consumers now auto-get LLM secret leak protection by default; no per-project install needed.

**Hook source** (cherry-picked from SilkNode PR #429 v1.2 commit `8eef709`):

- `aria/hooks/secret-guard.sh` (563 lines, executable) — PreToolUse: regex-blocks ~100 risky read patterns (cloud secret managers, K8s/Vault/Nomad secret APIs, .env / id_rsa / .pem / .aws/credentials / .kube/config / etc.). `# guard:ack: <reason>` inline bypass with `~/.claude/logs/guard-bypass.log` audit trail.
- `aria/hooks/secret-scan.sh` (378 lines, executable) — PostToolUse: scans tool output, REDACTs known secret-shaped content before reaching LLM context. Warn-only (exit 0 always, fail-open by design).

**Hook registration** (`aria/hooks/hooks.json`, +2 PreToolUse entries + 1 PostToolUse entry = 3 new entries; pre-existing handoff-location-guard PreToolUse retained):

- PreToolUse `Bash` → secret-guard.sh
- PreToolUse `Read|Edit|Write|MultiEdit` → secret-guard.sh
- PostToolUse `Bash|Read|Edit|Write|MultiEdit` → secret-scan.sh
- **NotebookEdit not registered** (per Tool Matcher decision in proposal §Tool Matcher & Contract).

**Test coverage** (`aria/hooks/tests/`):

- `secret-guard.test.sh` — 208 regression cases (207 from SilkNode upstream + 1 new `${CLAUDE_PLUGIN_ROOT}` substitution runtime test).
- `secret-scan.test.sh` — 44 regression cases.
- **Total: 252/252 PASS** (ship gate satisfied).

**New skill** `aria-doctor` v1.0.0 (`aria/skills/aria-doctor/`):

`check_secret_guard_install()` function detects dual-install state with **5 primary states** + **2 sub-flags**:

- States: `not_installed` / `single_plugin` / `single_local` / `dual_install` / `corrupted_settings`
- Sub-flags (on `dual_install`): `stale_local_version` / `divergent_content`
- 8 unit tests PASS, banner regex spec documented (graceful fallback when no banner)
- R2 audit deferred items closed: BA N1 (not_installed assert-never contract), BA N2 (single_local dual-cause advisory), QA NF2 (banner-missing edge case)

**Convention update** — `standards/conventions/secret-hygiene.md` v1.0.0 → v1.1.0 (additive):

- New §0 Path↔Layer mapping table (Path 1↔Layer 0 / Path 2↔inline / Path 3↔Layer 2)
- New §5 Layer 2 enforcement (plugin SOT paths, exit semantics, Path 2 inline ack, Q1 evidence boundary, Path 1+Layer 2 互补 with known-limitation list)
- New §6 Local copy + plugin coexist mode (5-state aria-doctor pointer + cleanup strategy + backwards-compat guarantee)

**Rule #6 framing** (per memory `feedback_deterministic_structural_skill_rule6_substitute`):

aria-doctor is a deterministic structural skill (pure function: filesystem → JSON state). Rule #6 benchmark uses **structural substitute** (NOT `/skill-creator` LLM AB):

- `aria-plugin-benchmarks/ab-results/2026-05-23-aria-secret-guard-plugin-default-structural/README.md` — substitute framework + 8 test × 5-state coverage matrix
- `aria-plugin-benchmarks/.../atomicity-guard.md` — schema evolution contract (append-only sub-flags, no rename primary state)
- `aria-plugin-benchmarks/.../dogfood-evidence.md` — Aria self in-vivo capture (validates dual_install detection)

**Audit history**:

- post_spec R1: 5 PASS_WITH_WARNINGS, 1 Critical (version conflict) + 12 Major + 17 Minor across 5 agents (tech-lead + backend-architect + qa-engineer + code-reviewer + knowledge-manager)
- post_spec R2: 5 PASS_WITH_WARNINGS, 5/5 R1 ADDRESSED, 0 new Major, 12 new Minor — pragmatic 2-round convergence per memory `feedback_post_spec_audit_pragmatic_convergence`.

**Known limitations** (deliberately NOT fixed in v1.24.0 — would require regex changes with new false-positive risk; ack path is sufficient daily workaround):

- **(a) False-positive**: `cat <script> && grep .env <script>` triggers the `.env` file-read regex even though the source `<script>` is a benign code file (the substring `.env` in the script content matches without context). Parent DEC §4.3. Workaround: `# guard:ack: <reason>` per-command bypass.
- **(b) False-negative**: log-file grep patterns are not in the `risky_patterns` whitelist, so `grep -r 'PASSWORD' /var/log/` slips through. Parent DEC §2.6. Workaround: rely on operator discipline + secret-scan PostToolUse REDACT as second-line defense.
- **(c) False-negative (NEW from TASK-007 dogfood 2026-05-23)**: Bash matcher does NOT catch local `cat | head | tail | less | more <key-file>` for SSH/PEM/PKCS-12 keys (id_rsa / id_ed25519 / *.pem / *.key / *.p12). Only the SSH-wrapper variant (`ssh ... cat id_rsa`) is in the Bash regex; Read/Edit/Write/MultiEdit matcher DOES catch the same file paths via its independent path scan (line 153 of secret-guard.sh). Workarounds: (1) use Read tool instead of Bash `cat` for inspecting key files; (2) secret-scan PostToolUse provides second-line REDACT defense; (3) `# guard:ack:` bypass for legitimate one-off ack'd reads. Owner triage 2026-05-23 (smoke-evidence.md §3.1 F2): Accept as new known-limit; v1.25.x roadmap will extend Bash regex `risky_patterns`.

**Performance budget** (Revised 2026-05-23 post-TASK-007 dogfood):
- p95 < 400 ms per Bash tool event (empirical Aria-self warm = 337 ms)
- p95 < 150 ms per Read|Edit|Write|MultiEdit tool event (empirical = ~102 ms)
- Cold-start (first invocation per session): may reach 600-1400 ms (filesystem + library load)
- Original 100 ms estimate omitted the ~100-pattern regex sweep + multi-stage jq pipeline cost; revised budget reflects measured warm-path behavior
- v1.25.x roadmap: hook perf optimization (compile regex / pre-flatten jq pipeline / single-pass POSIX shell) to reclaim sub-100 ms target
- Owner triage 2026-05-23 (smoke-evidence.md §3.1 F1): Accept with budget revision

**Ship gate** (smoke-evidence.md §3 verdict): **REVIEW → PASS_TRIAGED**
- 0 unexpected_false_positive ✓
- 0 unexpected_false_negative ✓ (after F2 reclassified as known-limit per owner triage)
- 10 daily PreToolUse Bash + Read + Edit events captured with p50/p95 timing
- 3 block-validation events all blocked correctly (B1 nomad-var-get / B2 Read .env / B3 cat id_rsa → reclassified F2)
- 3 PostToolUse scan events (1 REDACT applied + 2 pass-through)
- TASK-008 SilkNode cross-project smoke: P2.5 deferred 7-day post-ship (no SilkNode owner in current session)

**Cross-references**:

- Spec: `openspec/changes/aria-secret-guard-plugin-default/` (archived after merge)
- Parent decision: `.aria/decisions/2026-05-20-secret-rotation-during-m5-deploy.md` §5 (Layer 3 决议)
- Brainstorm decision: `.aria/decisions/2026-05-22-aria-secret-guard-plugin-default-brainstorm.md`
- New memory: `feedback_claude_code_hook_merge_all_fire` (Q1 5-trial empirical evidence)

## [1.23.1] - 2026-05-22

### Fixed — state-scanner `_status` lifecycle-head extraction range (aria-plugin #50)

Spec `state-scanner-status-extraction-range` (Forgejo aria-plugin #50). `_extract_status` 抓取 `> **Status**: ...` 单行时**对单行长度无上限**。大型 spec 把 Status 字段当 mini-changelog 写成 1500+ chars 一长行时,`_normalize_status` 的 `done`/`complete` fallback 会 word-boundary 命中埋在子任务叙述里的 token,把仍 archival-blocked 的 spec 错归 `done` → 错放进 `openspec.pending_archive[]`,污染归档推荐。与已修的 #101 (substring-shadow) 同源不同面 —— #101 修了匹配方式,#50 修提取范围。

- **`_status_lifecycle_head(raw)`** — 新 helper,把 raw Status 截到第一个文档化分隔符 (em-dash `—` / en-dash `–` / 空格包围 ASCII hyphen ` - ` / 半全角分号 `;` `；` / 全角句号 `。`) 前的 lifecycle 头段;逗号 `,` 与 ASCII 句号 `.` 刻意排除 (保护 `Approved, revised` / `v2.0`)。`_normalize_status` 改在头段上分类,签名 `(raw) -> str` 不变。
- **`_status_field_overlong(raw)`** — 新瘦谓词;头段无分隔符且超 200 字符时,`openspec.py` + `requirements.py` collector 发 `status_field_truncated` soft_error (经 scan.py 聚合进 snapshot `errors[]`,exit 10 路径)。
- **token 字典扩展** — `delivered` / `shipped` 加入 `implemented` 分支 (post-merge 已交付语义)。
- `_extract_status` 本身不变 —— `raw_status` 字段仍保留完整 Status 叙述供人类展示 (`raw_status` full / `status` from-head 职责分离)。
- 23 个 regression test (`TestStatusExtractionRangeIssue50Fix` 20 + 2 e2e + 1 requirements e2e);#101 (13) + #73 (8) 既有 regression 全过,0 regression。
- post_spec audit 5-agent convergence R1 (1 Critical + ~10 Important) → R2 → R3 CONVERGED。

## [1.23.0] - 2026-05-20

### Added — state-scanner Phase 1.6.1 inline carry-forward surfacing

Spec `state-scanner-inline-carry-forward-surfacing`(Forgejo Aria #90 primary + #89 superset variant B):state-scanner Phase 1.6 OpenSpec collector 之前**仅**输出 active changes 的 status / id / path 而**完全不识别** `openspec/changes/*/tasks.md` 内累积的 inline `[carry-forward|TODO|defer(red)?|known[ -]gap|PASS-with-note]` 注释。Multi-session AI 接手时对该 backlog blind。

#### Collector enhancement

- **`scripts/collectors/openspec.py`** 新 helper `_extract_carry_forward_annotations(tasks_md_content) -> list[str]`:
  - Pattern: `r'\[(?:carry-forward|TODO|defer(?:red)?|known[ -]gap|PASS-with-note)\b[\s\S]*?\]'`
  - Positional anchoring(token 紧贴 `[`)+ token-end `\b`(防 substring extension `[carry-forwarded-stuff]`)+ `[\s\S]*?` 非贪婪跨行
  - Multi-line normalization:`\r\n` + `\n` + `\r` → single space(CRLF + LF + 单 CR 全 multi-platform)
  - INCLUDE annotations 在 ```` ``` ```` code blocks 和 `<!-- ... -->` HTML 注释内
- `collect_openspec` 集成:per-active-change scan tasks.md(missing OK,silently skip),累积到顶层新字段 `openspec.carry_forward_inventory = {total, active_change_count, by_change}`,empty 时 `total=0` field always present
- Scope:**仅** `openspec/changes/*/tasks.md`(active only,archive 严格不扫,`proposal.md` 不扫)

#### 2-tier recommendation rules

- **`RECOMMENDATION_RULES.md`** 新 §1.89 + §1.895(2-tier 避免 silent floor):
  - `carry_forward_info`(INFO,priority 1.89,1≤total<5,non-blocking)
  - `carry_forward_pile`(WARNING,priority 1.895,total≥5,non-blocking)

#### Tests + dogfood

- **16 unit tests** `tests/test_openspec.py::TestCarryForwardInventory`:9 core + 7 R1-audit gap fills(empty tasks.md / missing tasks.md / proposal.md negative scope / CRLF / nested brackets / archive substring / code-block + HTML comment INCLUDE)
- Full regression: **584/584 tests PASS**
- **Live dogfood**(B.6): baseline 4 → inject 5 → 9 exact match → cleanup → 4 baseline restored,atomicity verified(git diff 0 lines)
- **Rule #6 structural deterministic benchmark**: `aria-plugin-benchmarks/structural/state-scanner-carry-forward/README.md` — AUTO_GATE=true via binary verification per `feedback_rule6_framing_differs_by_skill_type`

#### Schema + docs

- `references/state-snapshot-schema.md` adds `openspec.carry_forward_inventory` schema(additive,schema_version 仍 1.0)
- `SKILL.md` Phase 1.6 表格标注 `carry_forward_inventory` v1.23.0+

#### Audit history

- R1(post_spec): all REVISE,0 critical / ~5 majors / ~12 minors;multi-agent 共识 3/3 Q1 dispatcher + 2/3 regex word-boundary + threshold tier
- R2: all PASS_WITH_WARNINGS,all R1 majors ADDRESSED + 0 new critical/major
- Convergence per `feedback_post_spec_audit_pragmatic_convergence`:unanimous PASS-tier + verdict 改善 + 无振荡 + 0 critical/major

#### Forgejo issues

- Closes #90(primary) + #89(superset variant B per close-by-reference selection table in proposal §Success Criteria)

## [1.22.1] - 2026-05-20

### Fixed — Zero-day dogfood bugs in v1.22.0 handoff collector

3 production bugs surfaced at first dogfood use(同日 v1.22.0 ship 后立即手动跑
`collect_handoff_multibranch` 验证 Layer H 多 track 看板时发现,符合 P2 closeout
Round 8 tech-lead Finding #4 + 新 datetime bug,两 terminals 的 frontmatter 都被误标 legacy):

- **`scripts/collectors/handoff.py::parse_handoff_frontmatter`**:
  YAML 自动把 ISO 8601 timestamp(`updated-at: 2026-05-20T04:50:34Z`)解析为
  `datetime.datetime` 对象,parser `isinstance(val, str)` 类型守卫返回 None →
  全部 v1.22.0+ handoff 被误标 legacy。**Fix**: coerce `datetime.datetime` 或
  `datetime.date` 为规范化 ISO 8601 string (UTC + 'Z' suffix) 后再做 type guard。

- **`scripts/collectors/handoff_multibranch.py::_list_origin_branches`**:
  `git for-each-ref` sort 用 `--sort=-committerdate`(本 hotfix 加),但函数末尾
  `return sorted(branches), None` **再 sort 一次撤销 git 排序** → 20-branch cap 仍
  按字典序选 archive/* + bugfix/* 而非 master/feature/*。Round 8 tech-lead Finding #4
  实质未 fix(那次 fix 只改了 git 命令但漏掉 Python re-sort)。**Fix**: 移除
  `sorted()` 保留 git committerdate desc 顺序;cap 现在按 committerdate 倒序取 top 20。

- **(配套)** Stale "lexicographic order" 错误消息文本更新为 "most-recent by committerdate"。

### Verified

- 双终端实测:`multi-terminal-coordination` (simonfish/dev-claude2, D.3, done) +
  `aria-2-0-m5-replay-reconciler-drift-review-loop-audit` (simonfish/dev-claude, D.3, active)
  都正确出现在 NON-LEGACY tracks 列表
- 108 tests still PASS(无回归)
- 直接 hotfix branch(small isolated patch,不另开 spec)

### Meta dogfood note

3 个 bugs 在 v1.22.0 ship 后 5 分钟内、同日 dogfood 暴露 + 即时修复 ship — spec ship
过程中 5 次真实 race events + 3 次 production bugs 立即可见,**solution validates
itself by being needed AND fixing itself during its own day-zero use**。Memory entry
`feedback_meta_dogfood_solution_validates_self_mid_ship` 沉淀此 pattern。

---

## [1.22.0] - 2026-05-20

### Added — Multi-terminal coordination (Layer H + Layer L + Design A)

Per OpenSpec change `multi-terminal-coordination` (Approved 2026-05-19, per DEC-20260519-001).
Methodology extension addressing multi-terminal concurrent development including **cross-container** (no shared filesystem) scenarios. Real-world race events observed during this ship cycle motivated all three layers (接错棒 / 重复劳动 / 工作树污染).

**Implementation** (3 layers, advisory + 最终一致, pure git remote 不绑 Forgejo):

- **Layer H — Handoff frontmatter schema (Rule #9 §2.3 extension)**:
  - 5 字段机读 frontmatter (`track-id` / `owner-container` / `phase` / `status` / `updated-at`)
  - state-scanner Phase 1 跨分支 fetch + 重建多 track 看板 → 根除单写者 `latest.md` siloing
  - `standards/conventions/session-handoff.md` v1.0.0 → v1.1.0 (additive)
  - `aria/templates/session-handoff.md` frontmatter head + 字段填充指引
  - Backward-compatible: existing handoffs without frontmatter → graceful legacy fallback per mtime + filename

- **Layer L — Orphan ref + claim + reconcile + 急切认领**:
  - `refs/aria/coordination` orphan ref (history-isolated)
  - claim YAML schema v1 (10 fields incl `schema_version` + `superseded_from`)
  - file-per-writer partitioning (`claims/<container-id>/<session-id>.yaml`) → push 永不写他人文件
  - reconcile 4-rule deterministic protocol (early `claimed_at` / done takeover / `stale_ttl` takeover / lex tiebreak / `clock_skew` CONFLICT downgrade)
  - `scripts/phase1_gate.py` 9-step 急切认领 (fetch → reconcile → push claim → release to Phase B)
  - 7-case `failure_handlers.py` (non-ff retry / `auth_failed` no-retry / `disk_full` / partial fetch / orphan bootstrap / `user_decision` callback)
  - claim lifecycle (acquire / heartbeat 10min / release / `stale_ttl` 30min / GC archive)

- **Design A — Conditional worktree** (per-container concurrent ≥2 tracks):
  - `lib/concurrent_tracks.py`: `count_concurrent_tracks` 检测 `needs_worktree`
  - `lib/worktree_manager.py`: create / list / remove / cleanup_on_release / auto_cleanup_done_tracks
  - Submodule independent checkout via `git worktree add` semantics
  - 误用保护: dirty worktree default refuses cleanup; archive mode preserves history

**New files** (10 lib modules + 2 scripts + 1 doc + 3 tests):
- `aria/skills/state-scanner/lib/` — claim_schema / identity / track_id / coordination_ref / constants / claim_lifecycle / gc / reconcile / failure_handlers / concurrent_tracks / worktree_manager
- `aria/skills/state-scanner/scripts/phase1_gate.py`
- `aria/skills/state-scanner/scripts/renderers/track_board.py` (P1 + collision/clock-skew upgrade)
- `aria/skills/state-scanner/scripts/writers/latest_md_writer.py`
- `aria/skills/state-scanner/docs/rule9-5layer-matrix.md`
- `aria/skills/state-scanner/tests/test_p1_layer_h.py` + `test_reconcile_golden_table.py` + `test_race_window.py` + `test_failure_injection.py` (108 tests total)

**5-layer enforcement matrix** (Rule #9 全覆盖):
- L1 hook `handoff-location-guard.sh` 文档化 "无需改动 — 仅检查路径不检查内容"
- L2 collector `handoff.py` 加 `parse_handoff_frontmatter` helper + frontmatter-aware
- L3 state-scanner: Phase 1.16 `coordination_fetch` + Phase 1.17 `handoff_multibranch` + multi-track board
- L4 规约 SOT: `standards/conventions/session-handoff.md` §2.3
- L5 D.3 template: `aria/templates/session-handoff.md` frontmatter head

**CLAUDE.md Rule #9 Extension** (Aria 主仓): 引用本 v1.22.0 Spec + DEC-20260519-001

**Audit trajectory**:
- post_spec R1 (5 agents convergence): PASS_WITH_WARNINGS 5/5, 13 major dedupe
- post_spec R2 (v2 fixes verify): 4 PASS + 1 PASS_WITH_WARNINGS (全 minor) → 实质 unanimous PASS, 0 critical / 0 major
- post_implementation R8 (P2 final, informal): tech-lead **READY_TO_MERGE** + code-reviewer **SHIP_NOW** (15 minor, all `blocks_merge: no`)

**Rule #6 structural benchmark**: `aria-plugin-benchmarks/ab-suite/multi-terminal-coordination/benchmark.yaml` + result `ab-results/2026-05-20T042320Z-multi-terminal-coordination/` with AUTO_GATE=true (4 metrics, 所有 delta > 0,所有 threshold 满足);human_review pending per Rule #6 framing.

**Dogfood**: `.aria/dogfood-reports/multi-terminal-coordination-2026-05-20.md` 含本 session 真实 race 实证 (3 organic events: wrong-baton / push-reject / submodule-detach) + counterfactual analysis;真实 metric 数值待 master merge 后 `.aria/scripts/dogfood/measure_multi_terminal.py` 运行收集 (pending verdict)。

**Refs**:
- Spec: `openspec/changes/multi-terminal-coordination/` (Approved)
- Decision: `docs/decisions/DEC-20260519-001-multi-terminal-coordination.md`
- Closeout notes: `.aria/notes/multi-terminal-coordination-{p1,p2}-closeout.md`

---

## [1.21.4] - 2026-05-20

### Fixed — state-scanner sister-bug bundle: locale crash + transitional status

- **`skills/state-scanner/scripts/collectors/_common.py:_run`** (Aria #61):
  Windows CJK locale crash. `subprocess.run(..., text=True)` was falling back
  to `locale.getpreferredencoding()` (GBK on Chinese Windows) and crashing on
  UTF-8 git output (CJK commit messages / emoji per aria-standards
  git-commit.md 双语规范). 100% of `scan.py` runs failed on Chinese Windows
  with `UnicodeDecodeError: 'gbk' codec can't decode byte 0xaf` → exit 30.
  Fix: explicit `encoding="utf-8", errors="replace"` + defensive
  `UnicodeDecodeError` catch returning rc=125 (mirrors `TimeoutExpired` /
  `FileNotFoundError` softening — `_run` contract preserved: never raises).

- **`skills/state-scanner/scripts/collectors/_status.py:_normalize_status`**
  (Aria #73): transitional status `Implementation-Complete-Pending-Obs`
  mis-classified. Original v3.0 bug ("→ done", false-positive
  `pending_archive`) was incidentally migrated to "→ pending" by v1.20.0
  #101 fix, which wrongly surfaced the spec as a "待启动" item via
  `requirements.py:56` priority_items filter
  (`status ∈ {in_progress, ready, pending}`). Aether 2026-05-04 real-world
  hit: `migrate-docker-data-root-to-local-ssd` Spec with 24h obs window.
  Fix: new transitional family ahead of pending — hyphenated phrases
  `implementation-complete` / `implementation-done` route to `implemented`
  (the canonical lifecycle slot for "post-merge, awaiting verify/archive"
  per SKILL.md token dictionary). No new state introduced.

### Tests

- **`tests/test_common.py`** (NEW, 6 tests in `TestRunUtf8Encoding`):
  CJK roundtrip / emoji roundtrip / mixed ascii+CJK+emoji / non-zero rc /
  invalid-bytes errors=replace / command-not-found rc=127. Covers `_run`
  contract end-to-end.
- **`tests/test_openspec.py::TestStatusNormalizationIssue73Fix`** (NEW, 8 tests):
  primary case / alternate spelling / narrative form / no-pending-collision /
  no-done-collision / archived-precedence / unimplemented-shadow-guard /
  phrase-anywhere.
- **Suite**: 460/460 PASS (+14 new). Smoke importlib benchmark: 15/15 PASS.

### Closes

- Forgejo Aria #61
- Forgejo Aria #73

### Spec

- `openspec/changes/state-scanner-bugfix-locale-and-transitional-status/`
  → archived to `openspec/archive/2026-05-20-...` at release ship

---

## [1.21.3] - 2026-05-17

### Fixed — issue-triage D3 schema conformance (H3 iteration-2 + iteration-3)

- **`skills/issue-triage/SKILL.md` v1.0.0 → v1.2.0**:
  - **iteration-2** (anti-hand-author): Step 0 🚫 prominent block + Stage 1
    mechanical gate. *Benchmark-disproven as the D3 cause* — kept as
    defense-in-depth (0 regression, valid for weaker models / future drift).
  - **iteration-3** (the real D3 fix): Stage 3 now inlines the exact schema
    enums verbatim — verdict (7), severity (4, no "medium"),
    recommended_action (4, no "schedule") — at the fill point instead of
    deferring to a separate conventions file. Step 6 inlines ReproCase
    required fields (case_id was the #1 omission). New Stage 3.5 best-effort
    `jsonschema` self-check before comment synthesis.

- **Root cause** (corrected): the 2026-05-13 benchmark misdiagnosed D3 0/3
  as hand-authoring. Re-benchmark proved `script_produced 8/8` (zero
  hand-authoring on Opus 4.7); real cause = AI free-texts schema-enum
  fields with plausible-but-invalid values when enums aren't inlined.

- **Benchmark** (`aria-plugin-benchmarks/ab-results/2026-05-17-issue-triage-iter2/`):
  D3 with_skill **0/4 → 4/4** (iter-1 v1.1.0 → iter-2 v1.2.0), baseline
  v1.0.0 stays 1/4 — causal, baseline-controlled delta. Rule #6 PASS
  (capability-type Skill, 不可协商, full LLM AB — deterministic-substitute
  not applicable).

---

## [1.21.2] - 2026-05-17

### Docs/clarity — H1 follow-up (PR #46 + #4 audit Important items)

- **`hooks/handoff-location-guard.sh`**: added NOTE clarifying `set -e` is
  NOT the safety mechanism — the `DECISION=$(...)` command substitution masks
  python exit codes; safe behavior is the explicit fail-open PASS fallthrough
  (PR #46 audit Important-1; comment-only, behavior unchanged)
- **`RECOMMENDATION_RULES.md`**: `handoff_drift` rule clarified — added
  `degradation: true` flag + tri-state `non_blocking` semantics table
  (`non_blocking:true` advisory / `non_blocking:false` strong-signal /
  `+degradation:true` blocking-degradation / `blocking:true` hard-block),
  aligning handoff_drift with established `prd_draft_blocking` precedent
  (PR #46 audit Important-2)
- **`references/state-snapshot-schema.md`**: added explicit note that
  `latest.md` (pointer) is never itself a candidate handoff doc —
  excluded from `latest_path`/`exists`/`misplaced_files`; dir with only
  `latest.md` → `exists=false` (PR #46 audit Important-3)
- **(`standards/conventions/session-handoff.md`)**: `{archive-date}`
  placeholder filled to `2026-05-15` (real H0 archive date) — PR #4 audit
  Minor m5, companion aria-standards PR

No behavior change — documentation/clarity only. 446/446 suite + 10/10
hook smoke pass (pre-existing issue-cache-freshness flake unrelated).
Level 1 quick-fix per `feedback_closeout_found_bug_level1_hotfix`.

---

## [1.21.1] - 2026-05-16

### Fixed — H5 handoff collector mtime/pointer divergence (post-H0 closeout finding)

- **`collectors/handoff.py`**: `latest_path` now prefers `docs/handoff/latest.md`
  pointer target (human-maintained semantic "Latest") over raw mtime-max.
  mtime is fallback only (pointer absent / unparseable / stale target).
  - New `_parse_latest_pointer()` helper (regex on `**Latest**:` line)
  - New additive `latest_source` field: `"pointer"` | `"mtime"` | `null`
  - New `soft_error("handoff_pointer_target_missing")` for stale pointer
  - Schema stays `"1.0"` (additive)
- **Why**: discovered at H0 closeout — an H0 handoff edited post-hoc (rebase/
  closeout finalize) got newest mtime and shadowed the newer US-025 handoff;
  collector reported wrong "latest", defeating H0's anti-miss purpose.
  Memory: `feedback_handoff_mtime_vs_pointer_divergence`.
- **Tests**: +4 (TestLatestPointerPriority: pointer-wins / no-pointer-mtime /
  stale-pointer-soft-error / self-ref-ignored). 446/446 suite pass.
- **Docs synced** (Rule #3): schema doc + SKILL.md handoff-awareness +
  standards/conventions/session-handoff.md §3.2

---

## [1.21.0] - 2026-05-14

### Added — Ten-step cycle Phase D.3 session-handoff stage (Spec: aria-ten-step-session-handoff-stage, Forgejo Aria #92)

- **New Phase 1.15 `handoff` collector** (`skills/state-scanner/scripts/collectors/handoff.py`):
  - Scans `docs/handoff/*.md` by mtime DESC for latest handoff doc
  - Excludes `latest.md` pointer file (real handoff docs only)
  - Detects misplaced `.aria/handoff/*.md` files → `misplaced_files` field
  - Emits soft_error on permission-denied / stat-failure paths
  - Adds top-level `handoff` field to snapshot (schema 1.0 additive — no version bump)
  - 11 unit tests covering mtime sort, age_hours, schema, edge cases, latest.md exclusion, permission errors

- **New phase-d-closer §D.3 session-handoff step** (`skills/phase-d-closer/SKILL.md`, version 1.0.0 → 1.1.0):
  - Trigger: 4-level fallback (workflow-state.json::session.started_at > 4h → cycles shipped ≥ 2 → phase markers ≥ 2 → user prompt with default yes)
  - Output path **hardcoded** `docs/handoff/{YYYY-MM-DD}-{slug}.md` (L5 enforcement)
  - Auto-updates `docs/handoff/latest.md` pointer
  - Cross-platform stat hint (Linux/macOS/portable Python)

- **New 9-section handoff template** (`templates/session-handoff.md`):
  - §0 入口 / §1 已完成 / §2 carry-forward / §3 风险 / §4 实战教训
  - §5 多维度同步 / §6 next session 入口 / §7 提交清单 / §8 Memory entries

- **New PreToolUse hook `handoff-location-guard.sh`** (`hooks/handoff-location-guard.sh`):
  - Blocks Write/Edit/NotebookEdit to `.aria/handoff/*.md`
  - Cross-platform regex (POSIX `/` + Windows `\` separator char class)
  - Resolves symlinks via `Path.resolve()` to defeat circumvention
  - JSON deny payload (preferred) + exit-2 fallback (`ARIA_HOOK_DENY_MODE=exit2`)
  - 10 shell smoke test cases (run_tests.py 集成 via subprocess wrapper)

- **New state-scanner recommendation rule `handoff_drift`** (priority 1.91, between `audit_unconverged` 1.9 and `custom_check_failed` 1.95):
  - Trigger: `snapshot.handoff.misplaced_files != []`
  - Workflow: `migrate-handoff-drift` (4-step bash: git mv + update latest.md + rmdir + commit)
  - Confidence 95%, not auto-execute (file move 涉及 git history,需用户 confirm)

- **New convention SOT `standards/conventions/session-handoff.md`** (`aria-standards`):
  - Mirrors Rule #7 secret-hygiene structure
  - 5-layer enforcement matrix documented
  - Migration notes for downstream projects
  - Source incidents (4 dogfood)

- **CLAUDE.md Rule #9 ship-time 激活**:
  - Position: after Rule #8 pre-merge gate
  - Mirrors Rule #7 structure (要点 / 触发场景 / Source incidents / Exception / 详细规范 ref)
  - 4 dogfood evidence > Rule #7/#8 (no observation period needed)

- **Aria self migration**: 6 `.aria/handoff/*.md` files migrated to `docs/handoff/` via `git mv` (100% similarity preserved). `docs/handoff/latest.md` pointer corrected to truly newest doc.

### Quality

- pre_merge audit R1 SCOPE_OK_R1 — 3 agents convergence (backend / knowledge / qa), 0 Critical, 5 Major inline-fixed (collector double stat / macOS stat / silent permission-denied / latest.md wins mtime / hook test discovery)
- 442 Python unit tests + 10 shell hook smoke tests (100% pass, no regression)
- 4 dogfood incidents (SilkNode 2026-05-09 + Aria self 2026-05-13 ×3 含 H0 spec 起草本 session)

### Forgejo Issues

- Closes #92 (ten-step cycle session-handoff stage proposal)

---

## [1.20.0] - 2026-05-13

### Added — `issue-triage` Skill (Spec: aria-issue-triage-sop, Forgejo Aria #101)

- **New Skill `issue-triage`** (`skills/issue-triage/`):
  - 6-step standard SOP for triaging issues filed against Aria-managed projects
  - `scripts/triage.py` (stdlib-only Python) + 6 sub-collectors (Step 1-5
    mechanical) + JSON schema with `partial-repro` conditional (`if verdict ==
    "partial-repro" then deviation_note required`)
  - 7-verdict dictionary including **`partial-repro`** (new — captures cases
    where issue self-report differs from actual reproduction; born from #101
    where issue claimed 4/4 hit rate but actual was 2/4 primary + 2/4 secondary)
  - Orthogonal fields: `severity` (critical/major/minor/trivial) +
    `recommended_action` (hotfix/next-cycle/backlog/close)
  - Step 6 (reproduction) supports 3 exit modes: `auto` / `pause` / `skip`
  - Cross-repo support: 5-path fail-soft version chain
    (plugin.json → .claude-plugin/plugin.json → VERSION → package.json → pyproject.toml)
  - Rule #7 secret-hygiene compliant: single subprocess chokepoint with
    `capture_output=True`, AST-verified zero leaks
  - 115 unit tests + CI workflow YAML, full schema validation gate

- **Truth-source convention** (`aria-standards`):
  - New SOT doc `standards/conventions/issue-triage.md` (464 lines) — 6-step
    SOP definition, verdict dictionary, exception template
  - SKILL.md references SOT (no duplication) — mirrors Rule #7
    secret-hygiene.md pattern

- **Skill count**: 30 user-facing → **31 user-facing** (6 internal unchanged)

### Fixed — state-scanner `_normalize_status` (Spec: aria-issue-101-status-normalize, Forgejo Aria #101)

- **Bug 1 — substring shadow class**: `done` / `complete` / etc. token checks
  used `if X in low` which matched substrings. Status strings like
  `"Approved (Rev2 CONVERGED) — Phase A done"` matched `done` and returned
  `status=done` before reaching `approved`, causing `pending_archive` false
  positives → silent risk of WIP spec moved to archive on user accept of
  state-scanner recommendation.

- **Bug 2 — missing `implemented` token**: Status values like
  `"Implemented (Phase B PR-A merged) — post-deploy 验证后归档"` returned
  `unknown` (not in token dictionary). Caused state-scanner to drop legitimate
  Implemented specs from active classification.

- **Fix — word-boundary regex** (`\b<token>\b` via new `_has_token` helper):
  - Root-causes the entire substring-shadow class
  - Bonus pre-existing bug fixes: `inactive` no longer matches `active`,
    `incomplete` no longer matches `complete`
  - Prevents would-be regression: `unimplemented` does not match `implemented`

- **Priority chain refined** per R1 audit BA-M2:
  - Terminal (archived/deprecated) → pending family → in_progress family →
    **approved → implemented** (gatekeeping state before post-merge state) →
    reviewed/active/ready → done/complete (LAST fallback)

- **New lifecycle state `implemented`**: Post-merge state, between `approved`
  and `done`. For specs with code merged but awaiting post-deploy verify /
  monitoring / archive trigger.

- **state-scanner SKILL.md** adds "Status 字段最佳实践" section: supported
  token table with priority order + recommended format examples + anti-pattern
  educational notes (historical shadow traps now safe under word-boundary).

- **Tests**: New `TestStatusNormalizationIssue101Fix` class with 13 cases
  (4 #101 真实 strings + 4 shadow guards + 5 positive regression). Full
  state-scanner test suite: 414 → 427, **0 regression**.

- **Live verify**: Aria itself `pending_archive` false positives **4 → 0**
  on current active specs.

### Methodology

- **Two cycles single-day completion** demonstrating triage SOP value:
  1. `aria-issue-triage-sop` (Phase A+B+C+D, 8 task groups, 3 repos) —
     2 audits (R1+R2 post_spec SCOPE_OK_R2), T5 dogfood PASS, T8 Rule #6
     benchmark +21.8pp overall / +53.3pp structural
  2. `aria-issue-101-status-normalize` (Phase A+B+C+D, deterministic bug fix) —
     post_spec R1 SCOPE_OK_R1, Rule #6 deterministic AB +77pp (pre 3/13 vs
     post 13/13), 0 regression
- **Public dogfood evidence**:
  - Manual triage: https://forgejo.10cg.pub/10CG/Aria/issues/101#issuecomment-5972
  - AI dogfood: https://forgejo.10cg.pub/10CG/Aria/issues/101#issuecomment-6019
- **Decision memo**: `docs/decisions/2026-05-13-rule-9-deferral.md` (main
  Aria repo) — Rule #9 (issue triage enforcement) deferred, requires
  ≥3 dogfood + 1 missed-triage incident before reconsidering

### References

- Spec archive: `openspec/archive/2026-05-13-aria-issue-triage-sop/`
- Spec archive: `openspec/archive/2026-05-13-aria-issue-101-status-normalize/`
- Audit reports: `.aria/audit-reports/post_spec-{R1,R2}-2026-05-13-*.md`
- Benchmark archive: `aria-plugin-benchmarks/ab-results/2026-05-13-issue-triage/`
- Benchmark archive: `aria-plugin-benchmarks/ab-results/2026-05-13-state-scanner-issue-101-fix/`
- Closes: Forgejo Aria #101

---

## [1.19.0] - 2026-05-10

### Added — phase-c-integrator pre-merge gate (Spec: phase-c-integrator-pre-merge-gate, Forgejo Issue #60)

- **D1 — phase-c-integrator C.2.4 Pre-Merge Precondition Gate** (`skills/phase-c-integrator/`):
  - SKILL.md version 1.2.0 → 1.3.0; new sub-step C.2.4 inserted between PR
    creation and C.2.5 multi-remote push.
  - Consume aether `--in-flight` primitive (aether-cli #116, SHA `f29abee`
    2026-05-06). aria-side verdict computation (P0-B `aether-pre-merge-check`
    skill never shipped).
  - Three-state verdict: `green` (passing + no in-flight) / `wait` (passing +
    in-flight OR pending) / `fail` (failing OR primitive error).
  - 8 new config keys under `phase_c_integrator.pre_merge_gate.*`: `enabled`,
    `primitive_preference`, `no_aether_fallback`, `wait_timeout_seconds`,
    `wait_check_intervals`, `primitive_call_timeout_seconds`, `poll_chunk_seconds`,
    `user_escape_hatch`.
  - Helper `scripts/pre_merge_gate.py` (~290 lines, stdlib + subprocess only)
    + 20 unit tests (`tests/test_pre_merge_gate.py`).
  - Subprocess hardening: `subprocess.run(timeout=N)` + max 3 retry attempts
    (5s/15s/45s backoff); aether binary version pre-flight check (greps
    `--in-flight` in `aether ci status --help`).
  - Naming clarification: phase-c-integrator-tier C.2.4 (orchestrator) ≠
    branch-manager-internal C.2.4 (`等待审批`); independent label namespaces.
- **D2 — workflow-runner `wait_recoverable` error type + `gate_state` schema**
  (`skills/workflow-runner/`):
  - SKILL.md version 2.2.0 → 2.3.0; new §Pre-Action Gate State + §wait_recoverable
    error type + §Ctrl-C 检测机制 + §Resume 语义 sections.
  - workflow-state-schema.md `format_version: 1.0 → 1.1` (additive only); new
    `gate_state` top-level optional block with field descriptions and migration
    table entry (v1.0 → v1.1: gate_state default null).
  - Defensive access pattern: `state.get("gate_state") or {}` documented.
  - Reference impl `scripts/gate_state_helper.py` (~190 lines, stdlib only)
    + 22 unit tests (`tests/test_gate_state_helper.py`): lifecycle (create /
    increment / clear) + corruption recovery + interrupt flag-file lifecycle
    (clear / set / detect / latest-wins) + polling sleep chunk with mid-sleep
    interrupt detection (injectable `sleep_func` for deterministic tests).
- **config-loader/SKILL.md**: 7 validation rules for new
  `phase_c_integrator.pre_merge_gate.*` block.

### Background

2026-05-02 SilkNode incident: PR-321 merge cancelled PR-322 main CI Run #3161
(459s deployment observability lost). Root cause: Forgejo Actions concurrency
rule + Nomad single-job topology + missing pre-merge in-flight CI check in aria
workflow. Spec passed post_spec audit R1+R2 (4 Critical → 0, unanimous
PASS_WITH_WARNINGS). T1.0 spike revised D1 design after discovering the
upstream `aether-pre-merge-check` skill was never shipped — only the underlying
`aether ci status --in-flight` query primitive exists.

### Tests

42 new unit tests, all pass (20 D1 pre_merge_gate.py + 22 D2 gate_state_helper.py).

### Backward compatibility

- `pre_merge_gate.enabled: false` config preserves v1.18.0 behavior bit-for-bit
  (gate skipped entirely).
- `.aria/config.json` without `pre_merge_gate` block → config-loader fills
  defaults (`enabled: true`); workflow infrastructure invokes gate.
- Projects without aether plugin: `no_aether_fallback: skip_with_warning`
  default emits a workflow-report warning but does not block.
- workflow-state.json v1.0 files migrate transparently to v1.1 on read with
  `gate_state: null` default.

## [1.18.0] - 2026-05-09

### Added — state-scanner inter-cycle surfacing (Spec: state-scanner-inter-cycle-surfacing)

- **G2 — UPM `## Pending Followups` markdown table parser** (`collectors/upm.py`):
  column normalization (English + Chinese aliases), pipe-escape handling,
  priority normalization (P0..P3 case-insensitive or `unknown`), BA-10 fullwidth
  U+3000 rejection in heading regex.
- **G3 — handoff_doc pointer detection** (`collectors/upm.py`): primary regex
  with explicit Chinese/English/Emoji enumeration + R2-converged fallback (BA-02
  form, no standalone `入口`); three-state path resolution (URL / absolute /
  relative) with fail-soft `unsupported_path_format` + `handoff_path_escapes_project`
  soft_errors.
- **G4 — in-progress US `priority_items[]` derived view** (`collectors/requirements.py`):
  filtered + sorted view of `items[]` (no fs re-glob); 3-level stable sort
  (status_order ASC → mtime DESC → path LEX ASC); configurable limit via
  `state_scanner.priority_items_limit` (default 5).
- **TX.0 — `git.status_clean` derived bool** (`collectors/git.py`): `staged_files == []
  AND unstaged_files == []`; untracked excluded by design; fail-soft `False`.
- **RECOMMENDATION_RULES.md v2.11.0**: 2 new rules — `pending_followups_p1`
  (priority 1.85) + `resume_in_progress_us` (priority 1.88).
- **state-snapshot-schema.md**: 4 nested-field sections + backward-compat contract
  + `errors[]` enum (`unsupported_path_format` + `handoff_path_escapes_project`).
  Schema version stays `"1.0"` (additive only).
- **`normalize_snapshot.py` DROP_KEYS**: `raw_row` + `raw_match` to stabilize
  canonical form against upstream markdown drift.

### Changed
- **state-scanner SKILL.md T5 兜底降级**: 阶段 2 "完整性兜底" 段从 17 行 (4 触发
  条件 + 3 AI 主动 Read/Grep + 过渡说明) 缩减为 ~9 行 sanity check (collector
  字段缺失检测 → soft warn). T5 inline AI guidance 由机械化 collector 字段替代.

### Fixed (sub-PR (b) R2 audit corrections)
- **upm.py error-path schema contract**: 3 error paths (no-UPM-file / read-error /
  block-not-found) now correctly OMIT `handoff_doc` key per schema §upm L160 contract
  (was emitting `handoff_doc: null`, conflating "scanner ran no match" with "no UPM
  to scan"). Pre_merge backend-architect Major closed.
- **schema.md "planned for TX-G2/G3/G4" labels**: replaced with "shipped sub-PR (b)
  2026-05-09" + Implementation history blockquotes. CLAUDE.md rule #3 violation
  closed (knowledge-manager R1+R2 Major).

### Tests
**+39 net-new tests** (372 baseline → 414 on aria submodule master):
- sub-PR (a) aria-plugin#37: +5 (status_clean derived + fail-soft + 4 normalize rules)
- sub-PR (b) aria-plugin#38: +32 (24 initial G2/G3/G4 + 8 R2 corrections)
- sub-PR (c) (this PR): +4 backward-compat verify (TX.6)

### Pre-merge audits (multi-agent convergence loop, 4 agents per round)
- sub-PR (a) aria-plugin#37: 4 rounds, R3==R4 converged, 4/4 PASS, 0 Critical/Major
- sub-PR (b) aria-plugin#38: 5 rounds, R4==R5 converged after 8 R2 corrections
- sub-PR (c) (this PR): see PR description

### Refs
- Spec: `openspec/changes/state-scanner-inter-cycle-surfacing/proposal.md`
- Sub-PR sequence: aria-plugin#37 (a, prereq) → aria-plugin#38 (b, collectors) →
  this PR (c, cleanup + version bump)
- Issue: 10CG/Aria#85 (SilkNode inter-cycle surfacing gap forcing function)

### Marketplace.json sync
- 修复 `marketplace.json` 自 v1.17.6 起的版本漂移 (相对 plugin.json 落后 1 minor).
  本次同步至 v1.18.0 闭环.

## [1.17.7] - 2026-04-28

### Fixed

- **state-scanner issue_scan _normalize_items silent bug** — 现代 Forgejo (≥1.21) 给 `/issues` endpoint 的每个 issue payload 都附加 `"pull_request": null` 字段 (与 PR 共用 schema). 旧实现用 `if "pull_request" in raw: continue` 仅检查 key 存在性, 把**所有真实 issue** 误判为 PR 静默过滤掉 → `open_count=0`, 无 `fetch_error`, `source="live"` (genuinely successful fetch but completely wrong filter result).

#### Repro & evidence

- 实测案例: Aether 项目 (10CG/Aether) 有 24 个 open issues, 但 state-scanner 报告 `issue_status.open_count=0`. recommendation engine 在 issue 通道完全失明, 无法推荐任何 issue-driven 工作.
- forgejo CLI 直接 `GET /issues?type=issues` 返回 20 issues 但 `_normalize_items` 输出 0.

#### Fix

- **File**: `aria/skills/state-scanner/scripts/collectors/issue_scan.py:336`
- 改用值类型检查: `if isinstance(raw.get("pull_request"), dict): continue`
- PRs 携带嵌套 dict (含 `merged`, `state` 等); issues 携带 `None` 或 key 缺失. 检查值类型而非 key 存在与否.
- URL `/pulls/` 第二条 belt-and-suspenders guard 保留 (兼容旧 Forgejo / corner case).

#### Test

- 旧 `test_qa_c2_pull_request_filter` 用 `pull_request: {}` (空 dict) 模拟 PR, 没覆盖现代 Forgejo 的 `null` 情形 → 测试通过 production 漏 → 漏修.
- 新增回归测试 `test_modern_forgejo_pull_request_null_on_issues`: 3 个 mixed item (2 个 `pull_request: None` issue + 1 个 `pull_request: {merged: False}` PR), 期望保留 2 个 issue.
- 86 tests 全绿 (新增 1 + 已有 85 不变).

### Bug 来源

- **upstream Forgejo 1.21+ 的 schema unification**: 新版本统一 issue/PR payload schema, 给 issue 也附 `pull_request: null` 标识 "非 PR". 旧 `_normalize_items` 写于该变更之前, presence-only check 的隐式假设 (PRs 才有 pull_request key) 失效.
- **测试盲区**: 既有测试用 `pull_request: {}` 假 PR, 与现代 Forgejo 的 null issue 形态完全不同, 无法触发 bug.
- 影响: 任何接 aria-plugin 1.17.6 及以下版本到 Forgejo ≥1.21 的项目, recommendation engine 都看不到 issue.

### 跨项目影响

下游 (e.g. Aether) 升级到 1.17.7 后建议:
- 删 `.aria/cache/issues.json` 让 scan 重新 fetch
- 确认 `state-scanner` `issue_status.open_count` 与 `forgejo GET /repos/<owner>/<repo>/issues?state=open` 实测一致
- 可能需要把 `.aria/config.json` `state_scanner.issue_scan.limit` 调高 (默认 20, Aether 24 个 open 时已超出)

## [1.17.6] - 2026-04-26

### Added

- **verify_post_push.py SHA prefix-match (Spec `verify-post-push-sha-prefix-match`)** — Round-2 audit P2.2 spike-verified real bug

#### Script changes

- **File**: `aria/skills/git-remote-helper/scripts/verify_post_push.py`
- 新增 `_sha_match(actual, expected) -> bool` 辅助函数 + `_MIN_SHA_PREFIX = 7` 常量
- 第 147 行 `if sha == expected_sha:` 改为 `if _sha_match(sha, expected_sha):`
- 语义: `actual.startswith(expected.lower()) AND len(expected) >= 7`
- 短于 7 字符 → reject as False (避免 collision 假阳性)
- full 40-char happy path 字节级一致 (40-char.startswith(40-char) ⇔ ==)

#### Doc changes

- `aria/skills/git-remote-helper/SKILL.md:101`: 示例 `--expected-sha=19f2861` → full 40-char
- `aria/skills/git-remote-helper/references/api.md`: 4 处示例 `19f2861a3b4c5d6e7f8a9b0c` (24-char) → full 40-char; `--expected-sha` 字段说明追加 prefix 兼容性

#### Bug 来源

- doc 自爆: SKILL.md/api.md 示例本身用短 SHA, 用户照抄触发 script 严格 `==` mismatch
- production safety: Aria phase-c-integrator C.2.5 调用流程用 `git rev-parse HEAD` (full 40-char), happy path 不触发, 但新用户 onboarding 是 trap

### P2.1 closed as FALSE POSITIVE

- Round-2 catalog P2.1 (verify_post_push.py 早退 vs all_match) 经 spike 证伪
- script line 147 早退在 per-remote retry loop (line 138) 内, 不跨 outer `target_remotes` loop (line 186); line 198 `all_match=all(...)` 正确聚合
- catalog 自标 verifiability=LOW, spike 闭环

### Changed

- 单 Spec patch (sister-bug bundle 因 P2.1 证伪缩水到单 Spec, 适用 `feedback_level2_patch_no_benchmark.md`)
- 100% 向后兼容 (full SHA happy path 字节级不变; 仅放宽 short prefix 接受度)

### Migration

- 现有 caller 用 full 40-char SHA → 行为不变
- 新 caller 可用 ≥7-char prefix (与 `git show`/`git checkout` 习惯一致)
- 现有 caller 用 <7-char SHA → **会变为 reject**, 需升级到 ≥7-char (实际上 Aria 流程没人这么传)

## [1.17.5] - 2026-04-26

### Added

- **Round-2 audit P1.3 + P2.3 sister-bug bundling** — 双 Level 2 micro-Spec 打包发版, audit-engine 子系统第二批 sister-bug (前批 v1.17.4 P0.2 文件名 uniqueness)

#### P1.3: audit-engine finding ID determinism

- **File**: `aria/skills/audit-engine/SKILL.md` 第 220-233 行 + `references/convergence-algorithm.md` 第 28-42 行
- **改动**: finding `id` 字段从 prose 占位符 `"auto-generated-hash"` 显式规范化为 `sha256(category:scope:severity:type)[:8]` 8-char hex prefix; 与 4-tuple `comparison_key` 同步 (4-tuple 相等 ⇔ ID 相等)
- **跨轮稳定性**: 同 finding 在 R1/R2/RN 由不同 agent 报告 → 同 ID; severity 升级 → ID 改变 (符合 comparison_key 不收敛逻辑)
- **触发**: 2026-04-26 Round-2 latent-bug audit P1.3 (catalog `openspec/archive/2026-04-25-round-2-latent-bug-audit-findings/proposal.md`)
- **价值**: audit-driven fix inline 注释 `R1-a3f2c9b1 fix:` 跨轮稳定可追溯; 4 agent 同时报相同 finding 不重复计数

#### P2.3: audit-engine 0-finding stability gate

- **File**: `aria/skills/audit-engine/references/convergence-algorithm.md` 第 44-52 行边界条件表
- **Spike Result**: 真 bug 验证 ✓ — 文档 line 48 "空结论集 (两轮都无结论) | 视为收敛" 与 memory `feedback_audit_convergence_pattern.md` + `project_premerge_iteration_pattern.md` 实战教训冲突
- **改动**: 边界条件表加 stability gate 行: 首轮 0-finding 不视为收敛, 必须进入 Round 2 作 stability confirmation. 等价表达式 `converged = (current_set == previous_set) AND (current_set != ∅ OR round_number >= 2)`
- **经验来源**: aria-plugin v1.16.0 trajectory 24→2→1→0→0 (R5=∅ 后仍跑 R6=∅ 才声称收敛)
- **触发**: Round-2 audit P2.3 spike-first 调查 (符合 `feedback_spike_first_for_data_hypotheses.md`)
- **价值**: 消除 agent context 异常导致首轮 0-finding 假阴性收敛风险

### Changed

- 双 doc-only 改动 (无 scripts 修改), 100% 向后兼容
- audit-engine 子系统连续两批 sister-bug bundling (v1.17.4 文件名 + v1.17.5 ID/stability), 验证 sister-bug 模式在同子系统多 micro-bug 场景的可重复性

### Migration

- 现有 audit 报告: 旧 finding `id` 字段保留, 不强制重新计算 (向后兼容); 新报告按 sha256 规范生成
- 现有 0-finding 收敛历史: 已成功收敛的 audit 不回溯; 新 audit 按 stability gate 规则执行

## [1.17.4] - 2026-04-25

### Added

- **Round-2 audit P0 sister-bug bundling** — 双 Level 2 micro-Spec 打包发版 (`requirements-validator-status-i18n-alignment` + `audit-engine-report-filename-uniqueness`)

#### P0.1: requirements-validator Status i18n alignment

- **File**: `aria/skills/requirements-validator/SKILL.md`
- **改动**: 第 100-148 行 PRD/Architecture/User Story 的 `version_header.required_fields` 与 `header_fields.Status` 引用 6-pattern union form; 新增独立章节 "Status 字段提取规范 (i18n alignment)" 文档化 6 个模式 + i18n 全角冒号支持 + Negative case
- **SoT**: `aria/skills/state-scanner/references/state-snapshot-schema.md` 第 142-153 行 `_STATUS_PATTERNS` (与 collector 机械等价)
- **触发**: 2026-04-25 Round-2 latent-bug audit P0.1 (catalog `openspec/archive/2026-04-25-round-2-latent-bug-audit-findings/proposal.md`); 教训作为 lint 标准的跨 Skill 第三次应用 (前两次: state-scanner v1.17.2 i18n + v1.17.3 regex-hardening)
- **价值**: 中文项目 (Kairos 等中文 adopter) 用全角冒号或 heading-prefix 形式不再被 validator 误判 Status missing

#### P0.2: audit-engine 报告文件名唯一性

- **File**: `aria/skills/audit-engine/SKILL.md` 第 429 行
- **改动**: 文件名 schema 从 `{checkpoint}-{timestamp}.md` 升级为 `{checkpoint}-R{round}-{timestamp_ms}-{spec_id}-{agent_role}.md`; 加入字段定义表 + 完整示例 + 碰撞防护设计 + 向后兼容 reader 行为
- **碰撞防护**: 4-agent 并行 dispatch (qa-engineer / code-reviewer / backend-architect / tech-lead) 同毫秒落盘不冲突; 旧文件名作为 R1/legacy 仍能被 reader 处理
- **触发**: Round-2 audit P0.2; 历史样本时间戳粒度仅到分钟/秒, strict 模式收敛比较丢 finding
- **价值**: `R_N == R_{N-1}` 收敛判定基础完整, 不再因文件名碰撞丢 agent 输出

### Changed

- 双 doc-only 改动 (无 scripts 修改), 100% 向后兼容

### Migration

- audit-engine 旧文件名 reader 自动归类 R1/legacy, 用户无需手动迁移



### Added

- **state-scanner collector field-extractor 正则鲁棒性补强** (Spec `state-scanner-collector-regex-hardening`, Level 2 patch)
  - **architecture.py** 3 patterns (`Status` / `Last Updated` / `Parent PRD`): 加 heading prefix `(?:#{1,6}\s+)?` + fullwidth colon `[：:]` + optional bold `(?:\*\*)?`. 现在支持所有形式: `**Status**: A` / `**Status**：A` / `## Status: A` / `> **Status**: A` / `## **Status**: A`
  - **forgejo_config.py** 2 patterns: `_FORGEJO_YAML_KEY` 加 fullwidth colon + blockquote prefix; `_FORGEJO_HEADING` 加 blockquote prefix
  - **readme.py** `_VERSION_PAT`: 加 heading prefix + optional bold (i18n fullwidth 已在 v1.17.1 fix)
  - 100% 向后兼容 (regex 字符类 + optional prefix 都是严格超集)
  - 触发: 2026-04-25 主动 latent bug audit (3 个并行 Explore agent dispatch). 复合应用 v1.17.1 anchor narrowness + v1.17.2 i18n fullwidth colon 教训作为 lint 标准

- **9 新单元测试**:
  - `test_architecture.py::TestRegexHardening` (6 tests): fullwidth colon × 3 fields, heading prefix × 3 fields, heading + bold combined, blockquote + fullwidth, baseline regression
  - `test_forgejo_config.py::TestRegexHardening` (2 tests): fullwidth colon + blockquote prefix
  - `test_readme.py::TestRegexHardeningHeading` (1 test): `## Version: v1.2.3` 形式

- **`references/state-snapshot-schema.md`** 新增 architecture / forgejo_config / readme 三段落各加 union form 文档 + Spec ID 引用 (v3.0 SoT 同步)

### Changed

- 3 collector 模块 docstring 注明 i18n + heading hardening Spec 引用
- `state-scanner/SKILL.md` **不变** (mechanical-mode 后 prose 已最小化, 仅指向 schema.md)

### Acceptance verified

- 371/371 stdlib unittest PASS (was 362, +9 net)
- Smoke benchmark: 12/12 (100%) PASS — `aria-plugin-benchmarks/ab-results/2026-04-25-state-scanner-regex-hardening-v1.17.3/`
- Kairos cross-project retest: zero regression (parity preserved, 7/15 stories still resolve)
- 100% backward compatible

### Why patch instead of minor

- 跨 collector 共享 lint rule, 3 文件 ~30 行 regex + 9 unit tests + schema doc
- 实施工时 ~1.5h, 与 Spec 估时一致
- 与 v1.16.2/3/4 + v1.17.1 + v1.17.2 patch 模式一致 (`feedback_smoke_vs_full_ab_benchmark.md`)
- 主动 latent bug audit 路径,无外部 issue 触发

---

## [1.17.2] - 2026-04-25

### Added

- **state-scanner i18n Status 正则增强** (Spec `state-scanner-i18n-status-regex`, Level 2 patch)
  - Patterns 1-4 加 fullwidth colon `[：:]` 字符类 — 中文 IME 默认产生全角冒号 `：` (U+FF1A), 之前仅匹配半角 `:`
  - Pattern 6 NEW: inline blockquote 多 meta 匹配 — `> **优先级**：P0 | **状态**：pending` 中 status 不在行内首键的情形
  - Pattern 5 (table) 已支持 `[：:]`, 不变
  - 100% 向后兼容 (regex 字符类扩展是严格超集)
  - 触发: 2026-04-25 state-scanner-mechanical-enforcement T8 Kairos 跨项目验证发现, Kairos `US-009-tts-voice-clone.md` 用 `> **优先级**：P0 | **里程碑**：M3 | **状态**：pending` 格式被漏检

- **7 新单元测试**:
  - `test_requirements.py::TestI18nStatusRegex` (5 tests): fullwidth colon CN / Kairos US-009 实样 / inline blockquote at-end / inline blockquote middle EN / 负样 prose 不匹配
  - `test_openspec.py` (2 tests): _extract_status 共享模块 i18n 跨 collector 传播验证

- **`references/state-snapshot-schema.md`** 新增 "Status extraction patterns" 表 (6 patterns × Sample) + i18n note. 文档落到 schema.md (v3.0 SoT, AD-SSME-6) 而非 SKILL.md, 避免 mechanical-mode Spec 已消除的 prose-vs-code 重复定义

### Changed

- `collectors/_status.py` 模块 docstring 注明 i18n enhancement Spec 引用 + 6 patterns 设计
- `state-scanner/SKILL.md` **不变** (mechanical-mode 后 Phase 1.5 prose 已最小化, 仅指向 schema.md)

### Acceptance verified

- 362/362 stdlib unittest PASS (was 355, +7 net)
- Smoke regex 测试: 12/12 cases (P1-P5 × halfwidth/fullwidth + P6 NEW + 1 negative prose). 见 `aria-plugin-benchmarks/ab-results/2026-04-25-state-scanner-i18n-v1.17.2/`
- Kairos T8 retest: US-009 `raw_status: null → "pending"` ✅; 7/15 stories 现可解析 (was 0/15)
- 100% backward compatible

### Why patch instead of minor

- 跨 collector 共享模块 (_status.py) 单文件 ~25 行 regex 改动 + tests + schema doc
- 实施工时实测 ~45 min vs Spec 估时 ~1h
- 与 v1.16.2/3/4 + v1.17.1 patch 模式一致 (`feedback_smoke_vs_full_ab_benchmark.md`)
- aria:code-reviewer 单轮 MERGE_NOW + 2 Important + 3 Minor 全数已修

---

## [1.17.1] - 2026-04-25

### Fixed

- **state-scanner readme.py blockquote regex** (Level 1 hygiene patch, 3-agent parallel review)
  - `_VERSION_PAT` 锚点 `^\s*\*\*` 不允许 `>` 字符, 导致 `> **Version**: ...` 形式 (实际 aria/README.md L5 + root README.md 都用此形式) 无法匹配
  - 后果: `readme.submodules.aria.version_match` 自 v1.16.0 起静默 None, 即便版本完全一致
  - 修复: 改为 `^>?\s*\*\*` 与 `architecture.py` 风格一致 (允许可选 blockquote 前缀)
  - 漏测原因: smoke benchmark eval-3 仅验证字段存在, 未验证 truthiness (field-presence-only false-pass pattern)

### Added

- **6 regression tests in `test_readme.py::TestVersionPatternBlockquote`**:
  - blockquote + match 检测
  - blockquote + mismatch 检测
  - 无 prefix 形式 regression baseline
  - blockquote + v-prefix 组合
  - blockquote + 中文 key
  - field-presence-only false-pass guard (catches the v1.17.0 missed-bug pattern)

### Why patch instead of minor

- 单行 collector 正则 fix, 零 API 变更, 零 schema 变更 (Level 1 hygiene)
- 3-agent (backend-architect / qa-engineer / code-reviewer) 并行 1 轮 APPROVE_WITH_NOTES
- v1.17.0 latent bug 不能等到 next minor (`version_match` 已静默错误数月)
- 与 v1.16.2/3/4 patch 模式一致 (`feedback_smoke_vs_full_ab_benchmark.md`)

---

## [1.17.0] - 2026-04-25

### Added — state-scanner v3.0.0 机械化模式 (state-scanner-mechanical-enforcement Spec)

- **Step 0 hard constraint** (SKILL.md L63-95): Phase 1 数据采集只能通过 `python3 scripts/scan.py --output .aria/state-snapshot.json`. AI 不得用 Bash/Grep 逐字段重建状态. 退出码契约 0/10/20/30 (见 schema.md §Exit code consumer contract)
- **17 collectors 包** (`scripts/collectors/`, stdlib-only Python):
  - Phase 0: interrupt
  - Phase 1: git, upm, changes
  - Phase 1.5-1.10: requirements, openspec, architecture, readme, standards, audit
  - Phase 1.11-1.14 (opt-in): custom_checks, sync, multi_remote, issue_scan, forgejo_config
- **JSON snapshot schema v1.0**: 17 顶层字段, source-of-truth = `references/state-snapshot-schema.md`, validator = `scripts/validate_schema_doc.py` 断言 doc/code 一致
- **Canonical normalizer** (T7.0): `scripts/normalize_snapshot.py` (10 rules) + `references/json-diff-normalizer.md`. T7.2 live dogfood DIFF_EXIT=0 (两次 scan.py + normalize 字节级一致)
- **Stdlib unittest test suite** (T6): 215 tests, 1.6s runtime, 0 third-party deps. 9 collectors ≥70% coverage; 6 I/O-heavy <70% (T6.5-followup tracked)
- **Migration guide** (`references/migration-v2.9-to-v3.0.md`): Why / Step 0 contract / D1-D5 / opt-out lifecycle / upgrade checklist / rollback
- **Golden baseline fixture**: `tests/fixtures/reference-snapshot-aria.json` (722 行 normalized snapshot of Aria master 2026-04-25)

### D1-D5 Intentional Divergences (preserved as v2.9 → v3.0 fixes)

- **D1**: `Status: Approved` → `approved` (NOT collapsed to `ready`)
- **D2**: `Status: Reviewed` → `reviewed` (NOT collapsed to `pending`)
- **D3**: `Parent PRD: TBD/(pending)/N/A` → `chain_valid: false` (NOT silently true)
- **D4**: YAML `key: |` block scalar → `None` (NOT literal `"|"`)
- **D5**: `Active/Deprecated/Archived` → 3 distinct states (NOT all `unknown`)

每条都有专门 regression test 守护 (test_openspec/_architecture/_upm).

### Changed — SKILL.md condensed (1178 → 454 lines, -724 net)

- Phase 1.x 14 子阶段 prose 合并为 collector 职责表 (语义委托 schema.md)
- Phase 2 入口断言: snapshot 缺失 / `snapshot_schema_version != "1.0"` 直接 abort
- Step 0 + AI 禁区表 (✅/❌ 矩阵) 强约束机械路径

### Deprecated

- **prose path opt-out** (`.aria/config.json` 设 `state_scanner.mechanical_mode: false`): 仍受支持, 但 v1.18.0 移除 (AD-SSME-5). v1.17.x cycle 监测使用量, 零告警 = 安全移除信号

### Quality Gates Met

- T6 stdlib unittest: **215/215 PASS**, 1.6s
- T7 stability dogfood: **DIFF_EXIT=0** (字节级)
- Smoke benchmark v1.17.0: **35/35 (100%) structural assertions** across 11 ab-suite eval cases (`ab-plugin-benchmarks/ab-results/2026-04-25-state-scanner-v1.17.0/benchmark.md`)
- 8 audit reports across T1-T9 (4-agent × 4-round → 1-agent × 1-round proportionality 实证)
- 9 partial-merge cycles all 4-remote parity 同步

### Migration

升级路径见 `aria/skills/state-scanner/references/migration-v2.9-to-v3.0.md`. TL;DR:
- Python 3.8+ 必需 (AD-SSME-1)
- 添加 `.aria/state-snapshot.json` 到 `.gitignore` (session artifact)
- 跨项目消费者: 从读取 AI narrative 切换为读 `.aria/state-snapshot.json`
- 临时回退: 设 `state_scanner.mechanical_mode: false` (v1.18.0 失效)

---

## [1.16.4] - 2026-04-23

### Added

- **phase-c-integrator C.2.6 — UPM Milestone Sub-progress Append** (Forgejo #22, opt-in)
  - Config `upm.milestone_driven: false` (默认关闭, opt-in 设为 true)
  - 启用时在 C.2.5 push 完成后追加 UPM sub-bullet: `YYYY-MM-DD: {sha} — {title} ({PR_URL})`, `[ ]` → `[~]`
  - 解决 multi-PR cycle (e.g., schema expand-migrate-contract 3 PR) 下 D.1 前的 1-2 周信息盲区
  - phase-d-closer D.1 新增 "Milestone-driven Mode" 子节: 启用时 D.1 只需 finalize (`[~]` → `[x]` + archive 路径)
  - 源于 M1 closeout (2026-04-23) single-D.1 update 85 tasks 实际痛点 + silknode US-074 multi-PR migration 场景
  - standards `phase-c-integration.md` + `phase-d-closure.md` 同步说明

### Fixed

- **aria-dashboard 3 Major bugs** (Forgejo #23)
  - **M1 Archived spec duration "—"**: Created date 5-step fallback chain (frontmatter strict regex → frontmatter loose regex → git log 首次 commit → archive dir 前缀 YYYY-MM-DD → null)
  - **M2 Audit verdict CSS mislabeling**: 增加 `verdict-warning` (黄色, 覆盖 PASS_WITH_*) + `verdict-neutral` (灰色, 未知 verdict), 修正既有 verdict-revise 色彩; 解析优先读 audit-engine frontmatter `verdict:` 字段
  - **M3 无 Carry-forward 可视化**: 新增 `Carry-forward` HTML section, 数据源为 audit-reports frontmatter + proposal Out of Scope, 按 `target_release` 分组, 对 polish-heavy 工作流关键信息补齐
  - **Minor 4-9 延期** 到 v1.17.x (归档 spec 元信息薄 / 双仓库感知 / docs/decisions 展示 / 审计表截断 / spec 链接 / banner fallback)
  - 真实案例 (truffle-hound v0.2.1 dashboard): `PASS_WITH_POLISH` 不再误染红; v0.2.1 carry-forward 10 条不再丢失

### Level 2 Patch Release 说明

涉及 phase-c-integrator + phase-d-closer + aria-dashboard 3 个 Skill 逻辑变更. 延续 smoke benchmark 模式, full AB deferred.

### Related

- v1.16.4 完成 Phase D.1 milestone-driven 支持 + aria-dashboard Major bug cleanup
- 本 session v1.16.1-v1.16.4 累计修复 8 个 Forgejo Issue

---

## [1.16.3] - 2026-04-23

### Fixed

- **state-scanner Phase 1.5 PRD Status 提取 + `prd_draft_blocking` 推荐规则** (Forgejo #18)
  - Phase 1.5 新增 `prd_files[]` schema: `path` / `status` / `linked_stories` / `launch_date`
  - Status 提取复用 v1.16.1 #17 修复的 Pattern 1-5 (heading-aware, case-insensitive)
  - `linked_stories` 扫描 User Story 文件 `parent_prd:` frontmatter 或 `prd-{basename}` 引用
  - 推荐规则新增 `prd_draft_blocking` (priority 5): Draft PRD + linked_stories ≥ 5 → 优先 "review-prd" 而非开发
  - 输出格式新增 ⚠️ 标注, 无 Draft PRD 时 fallback 原格式 (backward-compat)
  - 真实案例 (silknode Phase 3 Commercial Launch): 20 Story 阻塞不再静默

### Documentation

- **OpenSpec 与 Fission-AI upstream 分叉声明** (Forgejo #25, `standards/openspec/*`)
  - `standards/openspec/VALIDATION.md`: 标记 `@openspec/cli` + `validate --sync/--numbering` 为 DEPRECATED, 指向 `aria:audit-engine` 原生 validator
  - `standards/openspec/project.md`: 新增 "与 Fission-AI OpenSpec 的关系" 章节 (6 维对比表 + 4 条不跟随理由 + 3 类选型指南)
  - `standards/openspec/templates/README.md`: 内联引用 project.md 分叉章节
  - 核心陈述: aria 双层任务架构 (proposal.md + tasks.md + detailed-tasks.yaml) 与 upstream delta-based workflow 结构性不兼容, aria 不跟随 upstream
  - Backward-compat: 所有现有 `openspec/changes/*` + `openspec/archive/*` 保持合法

### Level 2 Patch Release 说明

本 patch 涉及 state-scanner Skill 逻辑变更 (新增 schema + rule) → 延续 v1.16.1/v1.16.2 smoke benchmark 模式, full AB deferred.

### Related

- v1.16.1 + v1.16.2 (2026-04-23 同日): #17 regex / #24 命名约定 / #27 change_id validation / #26 checkpoint gate
- v1.16.3 完成 state-scanner Phase 1.5 post-m0 bug 系列 (#17 + #18 两个 sister bug)
- v1.16.3 完成 OpenSpec standards 文档同步 (#24 + #25 两个 sister issue)

---

## [1.16.2] - 2026-04-23

### Fixed

- **audit-engine pre_merge checkpoint 报告完整性 gate** (Forgejo #26)
  - pre_merge audit 运行时新增 Checkpoint Report Completeness Gate
  - 对 `audit.checkpoints.*: "on"` 的每个 checkpoint, 校验 `.aria/audit-reports/{checkpoint}-*.md` 必须存在 (`post_closure` 除外, post-hoc 审计)
  - 缺失时拒绝 pre_merge 通过, 输出 ERROR 附 3 条修复路径
  - 配置 `audit.allow_incomplete_checkpoints: false` (默认) 提供显式豁免, 豁免时强制 `[WARN] incomplete checkpoint gate bypassed: missing={names}` audit trail
  - 与 Forgejo #27 (v1.16.1 修复) 互补: #26 = 横向完整性 (该跑的都跑了), #27 = 纵向真实性 (报告引的都真)
  - 真实案例 (truffle-hound v0.3.0 2026-04-22): Claude + 用户跳过 Phase A, audit 链条静默断, 发版后 state-scanner 才发现

### Level 2 Patch Release 说明

本 patch 涉及 audit-engine 逻辑变更 (新增 gate) → Phase [2] benchmark 覆盖 #26 + #27 联合验证.

### Related

- v1.16.1 (2026-04-23) 同日发布, 含 #17 state-scanner regex + #27 audit-engine change_id validation + #24 openspec 命名约定
- v1.16.2 是 v1.16.1 的 sister-bug 补丁, 同审计肌理完成

---

## [1.16.1] - 2026-04-23

### Fixed

- **state-scanner Phase 1.5 Status heading regex** (Forgejo #17)
  - Pattern 1 放宽为 `^(?:#{1,6}\s+)?Status:\s*(.+)` 支持 Markdown heading 前缀 (`## Status:`)
  - Pattern 3 中文 `状态` 统一为 `^(?:#{1,6}\s+)?\*{0,2}状态\*{0,2}[：:]\s*(.+)` 覆盖 heading + bold + plain
  - 影响: SilkNode 项目 13/77 Story 由 "unknown" 正确识别为实际状态

- **audit-engine change_id 锚点校验** (Forgejo #27)
  - 写盘前新增 Pre-write validation: change_id 必须对应 `openspec/changes/{id}/proposal.md` 或 `openspec/archive/*-{id}/proposal.md`
  - 配置 `audit.allow_dangling_change_ids: false` (默认) 提供显式豁免路径, 豁免时强制记录 `[WARN]` audit trail
  - 与 Forgejo #26 FR-1 (checkpoint 报告完整性 gate, 待修) 互补
  - 真实案例 (truffle-hound v0.3.0 2026-04-22): change_id 从未有 proposal 背书, 两份 audit 报告 dangling reference

### Documentation

- **OpenSpec change id 命名约定** (Forgejo #24, `standards/openspec/templates/README.md`)
  - 新增章节覆盖 5 维度: version 前缀 / topic 串联 / descriptor tail 枚举 / slug 长度 (硬 60, 软 40) / 多 feature 聚合
  - 引用 truffle-hound 真实 drift 样例作对照
  - 为 brainstorm / spec-drafter / state-scanner 消费者提供统一决策锚点

### Level 2 Patch Release 说明

本 patch 豁免自 `/skill-creator` 全量 benchmark (per `feedback_level2_patch_no_benchmark.md`),
但 state-scanner + audit-engine 修改涉及 Skill 逻辑 → 本 session 后续 Phase [2] 补跑这 2 个 Skill 的针对性 benchmark。

### Related

- M1 MVP closeout (aria-2.0-m1-mvp) 同日完成, 归档位置: `openspec/archive/2026-04-23-aria-2.0-m1-mvp/`

---

## [1.16.0] - 2026-04-15

### Added

- **state-scanner Phase 1.13 `scan_submodules` opt-in** (Spec: `state-scanner-submodule-issue-scan`, PR #19)
  - 新增配置项 `state_scanner.issue_scan.scan_submodules` (boolean, 默认 `false`)
  - 启用时递归扫描 `.gitmodules` 中所有 submodule 的 Forgejo/GitHub issues, 每个 submodule 独立 fail-soft
  - 新增 `issue_status.repos[]` 分组视图 + `schema_version` 字段 (v1.0 / v1.1)
  - `items[]` / `open_issues[]` 同步双写, 保持对 v1.0 消费者的向后兼容
  - 支持 meta-repo 模式 (如 Aria 主 repo + aria-plugin / aria-orchestrator / aria-standards submodule)
- **state-scanner Phase 1.13 `stage_timeout_seconds` 自适应**:
  - `scan_submodules=false` → **12s (不变, 向后兼容)**
  - `scan_submodules=true` → `max(20, (N_submodules+1) × api_timeout_seconds)` 按 submodule 数自动扩展
  - 用户显式设置时尊重覆盖值
- **state-scanner cache schema_version 守卫**: reader 识别 pre-v1.1 旧缓存 → 一次性 cold re-fetch, 避免 silent schema corruption

### Changed

- **state-scanner SKILL.md 版本**: 2.9.0 → **2.10.0**
- **state-scanner references/issue-scanning.md 版本**: 1.0.0 → **1.1.0**
- **open_blocker_issues 推荐规则**: 语义升级为跨 repo 聚合 — 任一 repo (主 + submodule) 的 blocker/critical label 触发降级推荐, 扁平化 items[] 聚合

### Backward Compatibility

- **`scan_submodules=false` (默认)** 场景行为与 v1.15.2 字节级一致 — 相同 12s 超时 + 单 repo 扫描 + 相同输出 schema (不含 `repos` 字段)
- **缓存 schema 迁移**: pre-v1.1 缓存文件被识别为 cold cache, 首次 v1.16.0 run 将一次性 re-fetch 所有 repo (无用户干预)
- **输出 schema**: items[] 新增同步写入 open_issues[] 作为别名, v1.0 消费者不受影响

### Related

- Spec: `openspec/changes/state-scanner-submodule-issue-scan/proposal.md` (Level 2 Draft)
- Parent Spec: `state-scanner-issue-awareness` (2026-04-09 archived) — 本 v1.16.0 扩展其 D6 决策, 不否定原决策
- Sister Spec: `state-scanner-mechanical-enforcement` (Draft) — 独立关注"执行纪律", 单一焦点分离
- Benchmark: `aria-plugin-benchmarks/ab-results/2026-04-15-state-scanner-submodule-issue-scan/` (+41.7pp pass rate)

## [1.15.2] - 2026-04-12

### Fixed

- **check_parity.sh shell injection 防护** — Python heredoc 内的 `$REPO` / `$REMOTE` / `$BRANCH` / `$TIMEOUT_SECONDS` 直接注入改为环境变量传参 + 单引号 heredoc (`<<'PYEOF'`), 防止路径含引号/反斜杠/换行时脚本破坏
- **check_parity.sh 死代码清理** — 删除未使用的 TIMEOUT_CMD 变量构造 (L68-86), timeout 检测已在 ls_remote 调用处内联实现

### Changed

- **verify_post_push.py `--max-retries` 注释增强** — 明确指出 max_retries=3 产生 4 总 attempts (1 initial + 3 retries), 避免命名歧义
- **fallback 路径可移植性文档** — state-scanner / phase-c-integrator / sync-detection.md 中的 `test -f aria/skills/...` 统一为 `test -f "${ARIA_PLUGIN_ROOT:-aria}/skills/..."`, 支持跨项目场景 (非 Aria 主项目时通过环境变量指定路径)

### Notes

- v1.15.2 为 Phase B Code Review 遗留 MINOR 项的集中清理, 无功能变更
- Dogfood 闭环完整: v1.15.0 实施 → v1.15.1 timeout 调优 → v1.15.2 cleanup

## [1.15.1] - 2026-04-12

### Fixed

- **git-remote-helper timeout 默认值** (dogfood 发现) — 从 5s 提升为 15s
  - Forgejo SSH over Cloudflare Access 实测 ls-remote ~8s, 5s 默认 4 次 attempt 全部超时
  - `check_parity.sh --timeout` 默认: 5 → 15
  - `verify_post_push.py --timeout` 默认: 5.0 → 15.0
  - `config.state_scanner.multi_remote.timeout_seconds`: 5 → 15
  - `config.phase_c_integrator.multi_remote_push.post_push_verify`: 新增 `timeout_seconds: 15` + `max_per_remote_seconds: 34 → 74`
  - 快速网络可设 `--timeout=5` 回到 v1.15.0 的 34s 上界
- 更新 schema.md / api.md / SKILL.md 中的 per-remote 时间上界描述 (34s → 74s)

### Notes

- v1.15.1 dogfooding 验证: 双仓库 (aria + 主) × 双远程 (origin + github) 全部 match, attempts=1 (15s 足够 1 次命中)

## [1.15.0] - 2026-04-12

### Added

- **git-remote-helper (US-012, Layer 3)** — 新 internal skill, 提供 Git 多远程 parity 检测与 push 验证的共享基础设施
  - `check_parity` 指令块: per-remote SHA 对比 + shallow/detached/未 fetch refs 守卫
  - `push_all_remotes` 指令块: 严格 post-push SHA 验证 (不依赖 "Everything up-to-date" message)
  - `verify_parity_post_push` 指令块: Python 实现指数退避 [0, 2, 4, 8]s, 上界 34s/remote
  - JSON schema canonical source, 跨平台兼容 (timeout/gtimeout/Python wrapper)

- **state-scanner Phase 1.12 多远程扩展 (US-012, Layer 1)** — 原地扩展, 不消耗 D8 配额
  - `sync_status.multi_remote.*` 新字段: 主仓库 + 子模块 per-remote parity
  - `overall_parity` 精确定义: 排除 `ahead` (正常待推送) 和 `unknown` (网络故障)
  - `multi_remote_drift` 推荐规则 (priority 1.35, warning 非阻塞)
  - 向后兼容: `submodules[]` 现有字段保留, `remote_commit` = origin 的 remote_head

- **phase-c-integrator C.2.5 Multi-Remote Push Enforcement (US-012, Layer 2)** — 合并 PR 后自动推送所有远程 + SHA 验证
  - Per-Remote Matrix Gating: 子模块推 X 失败仅阻断主仓库推 X, 其他 remote 不受影响
  - 失败优先级: `read_only_remotes` > `fail_on_partial_push` > 默认阻断
  - 配置: `.aria/config.json` 顶层 `multi_remote.*` + skill 级 null 继承

### Fixed

- **2026-04-12 v1.14.0 发版事故根因修复** — aria 子模块推 origin 但遗漏 GitHub 的场景, 现由 C.2.5 post-push SHA 验证彻底阻断

### Changed

- `branch-manager` 与 `phase-c-integrator` 边界明确: branch-manager 仍仅推 origin (PR 阶段), 多远程语义在 C.2.5 合并后生效

### AB Benchmark

- eval-10 `multi-remote-parity-drift`: Layer 1 多远程漂移检测 (state-scanner)
- eval-11 `submodule-push-github-sync-miss`: Layer 1 本次事件回归测试
- eval-hlp-1~4: Layer 3 helper (parity check / push / verify retry)
- eval-int-1: Layer 2 integrator (多远程合并推送)

## [1.14.0] - 2026-04-12

### Added

- **state-scanner Phase 1.8 扩展 (aria-plugin#9, PR #11)** — README 检查增强
  - 子模块 `aria/README.md` 版本号 vs `plugin.json` 检测
  - Skill 数量一致性 (排除 `user-invocable: false`, 当前 5 个内部 Skill)
  - Skill 列表完整性 (info 级)
  - Plugin badge 版本检测
  - `readme_outdated` 规则扩展: `readme_skill_count_mismatch` + `readme_badge_mismatch`

- **state-scanner Phase 1.14 (aria-plugin#10, PR #11)** — Forgejo 配置检测
  - 检测 Forgejo remote + `CLAUDE.local.md` 配置状态 (missing/incomplete/configured)
  - `forgejo_config_missing` 推荐规则 (priority 1.45, non-blocking)

- **forgejo-sync PRE_CHECK Step 0 (aria-plugin#10, PR #11)** — 主动引导创建 `CLAUDE.local.md`
  - SSH/HTTPS remote URL 解析, owner/repo 推断
  - 用户确认 [y/N] 后创建/追加, 无状态设计

### Fixed

- **Skill 数量修正**: 33+3=36 → 30+5=35 (agent-router, agent-team-audit 为 user-invocable: false)

### AB Benchmark

- 2 新 eval (readme-skill-count-badge + forgejo-config-detection): avg delta +46.7% (POSITIVE)

## [1.13.0] - 2026-04-11

### Added

- **project-analyzer Skill (US-011, PR #8)** — 扫描项目技术栈/框架/工作模式, 输出 project-profile.yaml
  - Glob + Read 识别 7+ 技术栈 (Node.js/Python/Go/Flutter/Rust/Java/C++)
  - monorepo 子包检测, 工具链识别 (CI/CD/ORM/测试)
  - 降级: 无法识别时输出 unknown + 提示手工补充

- **agent-gap-analyzer Skill (US-011, PR #8)** — 对比项目需求 vs Agent capabilities, 输出覆盖度报告
  - capabilities 标签确定性匹配 (非 LLM 解析)
  - capabilities-taxonomy.yaml 同义词规范化
  - match_rate 标签重合率计算

- **agent-creator Skill (US-011, PR #8)** — 基于缺口分析生成项目级 Agent 配置
  - few-shot exemplar 生成 STCO frontmatter + capabilities + body
  - 确认机制: 交互预览 / --dry-run / --confirm
  - 同名覆盖保护 + 5 技术栈模板 (Node.js/Python/Go/Flutter/generic)

- **capabilities 机读字段** — 11 Agent frontmatter 新增 capabilities 标签列表
- **capabilities-taxonomy.yaml** — 54 个标签 + 同义词映射
- **agent-router v1.1.0** — 运行时注入 .aria/agents/ 项目级 Agent (非 Plugin 静态注册)

### AB Benchmark

- 3 新 Skill with/without 对比: avg delta +0.15 (POSITIVE)
  - project-analyzer: +0.00 (baseline 也能分析, Skill 提供标准 schema)
  - agent-gap-analyzer: +0.25 (确定性匹配 vs 主观评分)
  - agent-creator: +0.20 (dry-run + STCO 强制)

## [1.11.2] - 2026-04-11

### Changed

- **STCO Agent Description 模式 (US-010, PR #6)** — 11 Agent description 重写为 Scope-Trigger-Contract-Output 四要素
  - 6 消歧对: tech-lead↔backend-architect, code-reviewer↔qa-engineer, knowledge-manager↔context-manager
  - PromptX 三段式启发, 自然语言投射 (非 Gherkin 语法)

### Added

- **Handoff Contract v1.0 (US-010, PR #6)** — Agent 间结构化上下文传递协议
  - `subagent-driver/references/handoff-contract.md`
  - 预留 `agent_source: plugin|project` 支持 Layer 2 项目级 Agent

### Fixed

- **legal-advisor 三类行为异常 (Aria#10, PR #7)**
  - 新增 Multi-Round Protocol (修复拒绝承认历史立场)
  - 新增 Output Format YAML verdict 模板 (修复格式不遵循)
  - 新增 Critical Constraints "DO NOT write files" (修复未授权文件写入)

## [1.11.1] - 2026-04-10

### Added

- **Dual Delta Reporting Tool** (`aria-plugin-benchmarks/tools/calc_dual_delta.py`)
  定型自 Aria#8 spike (2026-04-10), 从 prototype 升格为正式 reporting 工具.
  - 计算 `internal_delta` + `cross_project_delta` + `inflation_ratio` 的报告工具
  - 支持 3 种 eval_metadata 格式 + 2 种 grading 字段名
  - 通过 `category` 字段 (可选) 区分 aria_convention / generic_capability / behavior_contract assertions
  - **不是 gate**: Rule #6 不变, 仅 informational
  - 集成 `INFLATION_CAP_UPPER=1.0` 守卫, 病理性负 cross 自动 clamp + warning
  - user-friendly 错误处理 (FileNotFoundError / JSONDecodeError / 格式校验)
  - 9 个 pytest unit tests, 包含 cap 分支 + None 分支真实覆盖
- **ASSERTION_CATEGORY_GUIDE.md** (`aria-plugin-benchmarks/`)
  Category 字段标注指南, 3 个 enum 值 + 5 正反例 + 歧义默认规则
- **HISTORICAL_CAVEATS.md** (`aria-plugin-benchmarks/`)
  Skills 的 dual delta 实测数据存档. 透明度补充, 非警告:
  - state-scanner v2.9.0: inflation 4.9% (VALIDATED)
  - commit-msg-generator v2.0.1: inflation 11.3% (MOSTLY VALIDATED)
- **AB_TEST_OPERATIONS.md "Dual Delta Reporting" 章节** — 两步运行示例 + inflation 解读指南 + 非 gate 声明

### Changed

- **aria-plugin**: v1.11.0 → **v1.11.1** (patch release, transparency enhancement)
- CHANGELOG 注明: **无 breaking change**, 无 Rule #6 变更, 无发版门禁变更

### Background (Why only a patch)

Aria#8 原 RCA 基于纸面估算 ("state-scanner ~50% 虚高" / "commit-msg 100% 虚高") 立了 3 个 Level 3 Spec 计划 Rule #6 重构 + Release Gate 2.0 + Escape Valve. Spike (2026-04-10) 实测**证伪原假说**:

- state-scanner v2.9.0 实测 inflation **4.9%** (噪音级别, 非 ~50%)
- commit-msg-generator v2.0.1 实测 inflation **11.3%** (非 100%)
- 3 个 Level 3 Spec 降级为 1 个 Level 2 Spec

因此 v1.11.1 仅包含透明度工具, **不改变任何发版决策**. 见 `docs/analysis/spike-report-2026-04-10.md`.

### Audit Process

两个独立的审计流程都已通过:

1. **post_spec convergence audit** (Phase A.1, 3 rounds, 4 agents):
   - Agents: tech-lead + knowledge-manager + qa-engineer + code-reviewer
   - Round 1: 1 PASS + 3 REVISE (35 findings: 1 CRITICAL + 13 major + 21 minor)
   - Round 2: 4 PASS (3 new minor: km_n1 标签歧义 + qa nf_01/nf_02 test fixture)
   - Round 3: 4 PASS (0 new findings, **严格收敛** ✅)

2. **Phase B.2 Final Review** (code-reviewer 单 agent 两阶段审查):
   - Phase 1 Spec Compliance: PASS (AC1-AC9 全部验证)
   - Phase 2 Quality: PASS (0 critical, 0 important)
   - Final Vote: **PASS, 0 blockers**

### 已知偏差 (non-blocker, 透明度披露)

- **ASSERTION_CATEGORY_GUIDE.md**: 实际 134 行, Spec AC3 原约束 "≤ 100 行".
  超出的 34 行是 "External category_map files" 和 "How to add categories" JSON 示例,
  显著提升文档实用性. code-reviewer Final Review 接受为 **non-blocking**,
  将在 D.2 归档时 Spec AC3 追认上限为 "≤ 140 行".

### Meta-Lesson

`meta_lesson_spike_first`: 数据驱动的量化假说必须 spike-first 实测验证再立 Spec. 本次避免了 ~1600 行无用工作. 已沉淀到 `MEMORY.md` → `feedback_spike_first_for_data_hypotheses.md`.

### References

- Spec: `openspec/changes/benchmark-transparency-enhancement/proposal.md`
- Spike: `docs/analysis/spike-report-2026-04-10.md`
- Parent Issue: Forgejo Aria#8

---

## [1.11.0] - 2026-04-09

### Added

- **state-scanner v2.9.0** — 两个新子阶段扩展状态感知能力 (Forgejo Issue #6)
  - **Phase 1.12 — 本地/远程同步检测** (`state_scanner.sync_check.*`, 默认开启)
    - 主分支 upstream ahead/behind 计算 (修复 upstream 未配置场景 exit ≠ 0)
    - Submodule 四级 fallback 链 (origin/HEAD → ls-remote → config_default → unavailable)
    - 浅克隆检测 (git ≥ 2.15 `--is-shallow-repository` + `.git/shallow` 兼容 fallback)
    - FETCH_HEAD 跨平台时间戳读取 (`git log -1 --format=%cr`)
    - 不主动 `git fetch` (Tier 2 `ls-remote` 5s 超时例外)
    - 新增推荐规则: `submodule_drift` + `branch_behind_upstream` (降级非阻断)
  - **Phase 1.13 — Issue 感知扫描** (`state_scanner.issue_scan.*`, 默认关闭 opt-in)
    - 平台检测 4 级优先级 (显式 config → hostname 映射 → URL 推断 → 兜底)
    - Forgejo + GitHub CLI 适配 (复用 `forgejo` / `gh` wrapper, 不管理 token)
    - IssueItem normalize 映射 (Forgejo `.labels[].name` vs GitHub `.labels[].name`)
    - 启发式关联 US-NNN 和 OpenSpec change 名 (单词边界正则 + URL 保护)
    - 10 个 `fetch_error` 枚举值统一 (network_unavailable / cli_missing / auth_missing / auth_failed / rate_limited / not_found_or_no_access / timeout / platform_unknown / parse_error / unknown)
    - 15 分钟缓存 TTL (`.aria/cache/issues.json`) + 同步 refresh + 旧缓存 fallback
    - 总阶段超时 12s (Forgejo + CF Access TLS 余量) + API 超时 5s
    - 新增推荐规则: `open_blocker_issues` (降级非阻断)
  - **SKILL.md 阶段数量上限规约** (D8): 当前 13/15 阶段，超过 15 必须重构为分组
- **config-loader v2.9** — 13 个新字段 (sync_check 4 + issue_scan 9) 默认值与验证规则
- **references/sync-detection.md** (新建) — Phase 1.12 完整实现逻辑
- **references/issue-scanning.md** (新建) — Phase 1.13 完整实现逻辑

### Changed

- **state-scanner**: v2.8.0 → v2.9.0 (新增 2 个子阶段, 11 → 13)
- **config.template.json**: 新增 `state_scanner.sync_check` 和 `state_scanner.issue_scan` 完整 block
- **.gitignore**: 新增 `.aria/cache/` 和 `.aria/heartbeat-scan.json` 运行时目录/文件
- **Skill 数量**: 33 (state-scanner 功能扩展，非新增 Skill)

### Fixed

- state-scanner 过去无法检测本地与远程的 sync 状态，容易在陈旧代码上做错推荐
- state-scanner 过去无法感知 open issues，用户需手动轮询平台

### Audit Process

- **post_spec 检查点**: 2 轮 convergence 审计 (Round 1 REVISE 22 issues → Round 2 PASS 收敛)
- **审计报告**: `.aria/audit-reports/post_spec-2026-04-09T1240Z.md` + `post_spec-2026-04-09T1315Z.md`
- **OpenSpec 并行发布**:
  - `openspec/changes/state-scanner-remote-sync-check/` (Level 2)
  - `openspec/changes/state-scanner-issue-awareness/` (Level 3)

---

## [1.10.0] - 2026-04-03

### Added

- **aria-dashboard Skill** — 项目进度看板生成器
  - 5 数据解析器: UPM, User Stories, OpenSpec, Audit Reports, AB Benchmark
  - 单文件自包含 HTML 模板 (深色主题, 响应式, 零 CDN)
  - 跨项目兼容: UPM 双格式 (HTML 注释 + YAML 代码块), Story 中英文字段
  - Issue 存储适配器设计 (Git 原生 + GitHub/Forgejo API 双模式)
  - Phase 1 完整看板交付, Phase 2-3 (Issue 提交 + 心跳 Agent) 待实施

### Changed

- **Skills 总数**: 32 → 33 (29 → 30 user-facing)

---

## [1.9.0] - 2026-04-02

### Added

- **audit-engine Skill** — 多轮收敛/挑战审计编排器
  - convergence 模式: 全员讨论 → 结论提取 → 四元组收敛判定
  - challenge 模式: 讨论组/挑战组对抗 → objections resolved 判定
  - 结构化结论 schema `{type, severity, category, scope, summary}`
  - 汇总引擎 (合并 + 去重 + 冲突标记)
  - 振荡检测 + 未收敛三路径降级策略
  - 审计报告生成 (含 Verdict 计算)
  - AB benchmark: delta +0.5 (WITH_BETTER)
- **7 个审计检查点** — 覆盖十步循环全流程
  - 已有升级: post_spec, post_implementation, pre_merge → audit-engine
  - 新增: post_brainstorm, post_planning, mid_implementation, post_closure
- **config-loader 审计兼容层** — experiments.agent_team_audit 自动映射到 audit.*
- **完整审计配置模板** — 11 Agents x 7 检查点默认分组
- **state-scanner v2.7.0** — 审计状态扫描 + adaptive 路由 + audit_unconverged 推荐规则

### Changed

- **Skills 总数**: 29 → 31 (28 → 29 user-facing, 2 → 3 internal: +audit-engine)
- **state-scanner** — 新增 Phase 1.10 审计状态扫描, Phase 4 adaptive 上下文传递
- **config-loader** — 新增 audit 配置块默认值, 旧配置兼容映射

---

## [1.8.0] - 2026-03-27

### Added

- **aria-report Skill** — 向 Aria 维护团队报告 Bug、提交功能建议或提问
  - 三种 Issue 类型: Bug Report / Feature Request / Question
  - 自动收集环境信息 (Plugin 版本、Skills 数量、OS、配置状态)
  - 隐私审查: 提交前必须用户确认完整内容
  - 三级提交路由: Forgejo (内部) → GitHub API → GitHub Pre-filled URL (降级)
  - 目标仓库: Forgejo `10CG/Aria` / GitHub `10CG/aria-plugin`
  - 与 state-scanner、agent-team-audit 集成建议

### Changed

- **Skills 总数**: 28 → 29 (27 → 28 user-facing)

---

## [1.7.2] - 2026-03-20

### Fixed

- **hooks 重复加载错误** — 删除 plugin.json 中的 `"hooks"` 字段和冗余的 `.claude-plugin/hooks.json`。`hooks/hooks.json` 由 Claude Code 自动加载，无需手动引用

---

## [1.7.1] - 2026-03-19

### Fixed

- **hooks.json 路径解析** — `plugin.json` 中的 hooks 路径从 `./hooks/hooks.json` 改为 `./hooks.json`，hooks.json 移至 `.claude-plugin/` 目录，修复 Claude Code 无法找到 hooks 配置的问题
- **hooks.json 格式修正** — 添加 plugin 专用 `"hooks"` 包装对象和 `"matcher"` 字段

---

## [1.7.0] - 2026-03-19

### Added

- **项目级配置基础设施** (`.aria/config.json`)
  - 新增 `config-loader` 内部 Skill — 统一配置加载、验证、默认值合并
  - `config.template.json` 模板文件，含完整 schema 注释
  - 6 个核心 Skills 集成配置读取 (state-scanner, workflow-runner, tdd-enforcer, branch-finisher, phase-c-integrator, phase-b-developer)
  - 配置优先级: `.aria/config.json` > `.claude/tdd-config.json` > Skill 默认值
- **state-scanner README 同步检查** (阶段 1.8)
  - 检测 README.md 版本号与 VERSION/plugin.json 是否一致
  - 检测最后更新日期与 CHANGELOG 最新条目是否一致
  - 新增推荐规则: `readme_outdated` (优先级 1.3)
- **state-scanner 插件依赖检测** (阶段 1.9)
  - 三状态检测: 无条目 / 未初始化 / 正常
  - 新增推荐规则: `standards_missing` (优先级 1.4, 建议性, 非阻塞)
- **Agent Team 集体审计** (实验功能, 默认关闭)
  - 新增 `agent-team-audit` Skill (experimental)
  - 三个审计触发点: pre_merge, post_implementation, post_spec
  - Verdict 系统: PASS / PASS_WITH_WARNINGS / FAIL
  - 问题去重算法 (category + affected_file)
  - 并发控制: max 2 parallel agents, 120s/300s 超时
  - 集成到 phase-c-integrator (pre_merge) 和 phase-b-developer (post_implementation)

### Changed

- **state-scanner** v2.6.0 — 新增配置加载、README 同步、标准依赖检测
- **RECOMMENDATION_RULES.md** v2.6.0 — 新增 readme_outdated + standards_missing 规则和检测方法
- **.gitignore** — 新增 `.aria/` 运行时文件排除

### Technical Debt (记录)

- state-scanner 阶段号膨胀 (1.0 到 1.9)
- `.claude/tdd-config.json` 与 `.aria/config.json` 长期并存需统一

---

## [1.6.0] - 2026-03-18

### Added

- **workflow-runner auto-proceed 模式** - Phase 间自动推进，减少手动确认步骤
  - 工作流状态持久化 (`.aria/workflow-state.json`)
  - Gate 1 (Spec 审批) 和 Gate 2 (Main Merge) 不可跳过
  - 失败时自动回退到手动模式
- **state-scanner 置信度评分** - 基于三维模型 (信号清晰度/风险等级/可逆性) 量化推荐可信度
  - 高置信度 (>90%) + auto_proceed 时可自动执行 (commit_only/quick_fix/doc_only)
  - 审计日志记录所有自动执行操作
- **SessionStart 中断恢复** - 检测未完成工作流并提示恢复/放弃/检查

### Changed

- **state-scanner** v2.5.0 - 新增置信度评分、自动执行策略、中断检测
- **workflow-runner** - 新增 auto-proceed 模式、状态持久化、Gate 强制机制

### Fixed

- **state-scanner** - 修复置信度评分导致编号选项格式回归的问题
  - 强制默认行为: 必须展示编号选项并等待用户选择
  - 自动执行仅在 `.aria/config.json` 明确配置时触发

### AB Test Verification

- state-scanner: delta +0.165 (WITH_BETTER) — 修复后验证通过
- workflow-runner: delta +0.33 (WITH_BETTER) — 新功能验证通过
- 基线数据: aria-plugin-benchmarks/ab-results/2026-03-18-verification/

---

## [1.5.1] - 2026-02-08

### Fixed

- **state-scanner OpenSpec 检测逻辑** - 修复只扫描 changes 目录，未扫描 archive 目录的问题
  - 新增 `openspec/archive/` 目录扫描支持
  - 明确区分 `standards/openspec/` (格式定义库) 和项目 `openspec/` (工作区)
  - 新增待归档 Spec 检测 (Status=Complete 但仍在 changes/)
  - 新增 OpenSpec 状态输出格式（活跃变更、已归档、待归档）

---

## [1.5.0] - 2026-02-08

### Added

- **openspec-archive Skill** - 归档已完成的 OpenSpec 变更
  - 自动验证 Spec 完成状态
  - 执行 openspec archive CLI 命令
  - **自动修正 CLI 归档位置 bug** (openspec/changes/archive/ → openspec/archive/)
  - 清理空目录并验证最终结果
  - 更新 phase-d-closer 引用新的 openspec-archive skill

### Changed

- **Cloudflare Access 自动处理重构** - 彻底解决 AI 不自动使用 CF Access 配置的问题
  - 新增 `FORGEJO_API_PRE_CHECK.md` - 统一的前置检查规范，作为所有 Forgejo API 调用的唯一真理来源
  - **branch-manager/SKILL.md** - 将前置检查嵌入执行流程 C.2.3，不再作为文档说明
  - **forgejo-sync/SKILL.md** - 引用统一检查规范文档
  - **phase-c-integrator/SKILL.md** - 更新引用统一规范

### Design Philosophy

```yaml
v1.4.1 问题:
  - 检查规则放在文档章节，AI 需要主动理解
  - 配置在 forgejo-sync，但 PR 创建在 branch-manager
  - 没有强制执行点

v1.5.0 解决方案:
  - 创建统一的 FORGEJO_API_PRE_CHECK.md
  - 检查规则嵌入执行流程步骤中
  - AI 按步骤执行时强制检查
  - 所有 Skills 引用同一规范
```

### Fixed

- **AI 自动检测 Cloudflare Access** - 前置检查成为执行流程的一部分，AI 必须执行

---

## [1.4.1] - 2026-02-07

### Added

- **Cloudflare Access AI 自动处理** - AI 主动识别和处理 Forgejo 的 Cloudflare Access 保护
  - 新增 `cloudflare_access` 配置项 - 控制 AI 是否使用 CF Access 模式
  - 新增 `API_CALL_PATTERN.md` - 统一的 Forgejo API 调用模式文档
  - AI 执行前检查规则 - API 调用前自动检测 `cloudflare_access.enabled`
  - 错误自动检测 - API 返回 403/CF 错误时自动提示配置
  - 自动配置提示模板 - 检测到 CF 保护时输出配置示例

### Changed

- **forgejo-sync SKILL.md** - 新增 "AI 执行前检查 (不可协商规则)" 章节
- **branch-manager SKILL.md** - 更新 Forgejo API 调用，支持 CF Access 头部
- **phase-c-integrator SKILL.md** - 添加 Cloudflare Access 引用
- **forgejo-sync 规范 (standards)** - 新增 Cloudflare Access 支持要求

---

## [1.4.0] - 2026-02-07

### Added

- **两阶段代码审查** - Superpowers 风格的代码审查机制
  - 新增 `aria:code-reviewer` Agent - 执行 Phase 1 (规范合规性) + Phase 2 (代码质量) 检查
  - 新增 `requesting-code-review` Skill - 用户可调用入口，自动填充模板并启动审查
  - **subagent-driver** 集成两阶段审查 - 新增 `enable_two_phase` 参数 (默认: true)
  - 审查结果分类: Critical (必须修复) / Important (应该修复) / Minor (建议修复)
  - 支持无计划降级模式 - 无 detailed-tasks.yaml 时仅执行 Phase 2
  - 中英双语支持 - 审查结果可用中文或英文输出
  - 7 个完整示例场景 - 覆盖 PASS/FAIL/WARN/Fallback/分批/调用等场景

### Changed

- **subagent-driver** v1.3.0
  - 新增 `enable_two_phase` 参数控制两阶段审查开关
  - 新增两阶段审查流程图和文档说明
  - 审查模式对比: 传统模式 vs 两阶段模式

- **Skills 总数**: 25 → 26
- **Agents 总数**: 10 → 11

### Design Philosophy

```yaml
两阶段代码审查:
  Phase 1: 规范合规性检查 (Specification Compliance)
    - 验证实现与计划一致
    - 检查功能完整性
    - 检测范围变更
    - 阻塞性: FAIL 终止审查

  Phase 2: 代码质量检查 (Code Quality)
    - 检查代码风格
    - 检查测试覆盖
    - 检查安全性
    - 检查架构设计
    - 阻塞性: 仅 Critical 阻塞

参考实现:
  - obra/superpowers requesting-code-review
  - Superpowers Code Review 最佳实践
```

## [1.3.2] - 2026-02-06

### Changed

- **brainstorm** - v2.0.0 重大重构：基于 Superpowers 最佳实践简化对话流程
  - 移除复杂的 6 状态机 (INIT/CLARIFY/EXPLORE/CONVERGE/SUMMARY/COMPLETE)
  - 采用简洁的 3 阶段流程 (Understanding → Exploring → Presenting)
  - 新增"不可协商规则"强制对话控制
  - SKILL.md 精简 (357 → 262 行, -27%)
  - 新增 `references/principles.md` - 核心原则详解
  - 新增 `references/question-patterns.md` - 提问模式库

### Fixed

- **brainstorm** - 修复 AI 跳过对话直接生成 User Stories 的问题
  - 添加"每次只能问 1 个问题"强制约束
  - 添加"禁止一次性生成所有 User Stories"规则
  - 添加"分段验证"机制 (200-300 词/段)

## [1.3.1] - 2026-02-06

### Fixed

- **state-scanner** - 修复 Windows 环境下 Bash 命令兼容性问题
  - Claude Code 在 Windows 上使用 Git Bash/WSL，而非 Windows CMD
  - 添加跨平台命令对照表 (正确/错误语法对比)
  - 新增 `references/cross-platform-commands.md` 详细参考文档
  - 采用 Progressive Disclosure 最佳实践 (SKILL.md 精简至 1,362 词)

### Changed

- **state-scanner** v2.3.0
  - 精简 SKILL.md 中的实现注意事项章节
  - 将详细命令示例移至 references/cross-platform-commands.md
  - 更新相关文档章节结构，分类更清晰

## [1.3.0] - 2026-02-06

### Changed

- **版本规范化** - 统一所有配置文件版本信息
  - 更新 `marketplace.json` 版本: 1.1.1 → 1.3.0
  - 更新 `hooks.json` 版本: 1.1.0 → 1.3.0
  - 新增 `VERSION` 文件作为人类可读版本快照
  - Skills 数量: 24 → 25

- **tdd-enforcer** - v2.0 重大重构：从代码驱动设计改为**文档驱动设计**
  - 参考 Superpowers 的实现方式，AI 读取文档理解并执行 TDD 规则
  - 移除所有 Python 实现文件 (17+ 模块: test_runners/, validators/, hooks/, tests/)
  - 重写 SKILL.md (798 → 355 行)，采用 Progressive Disclosure 架构
  - 新增 references/ 目录包含 4 个详细参考文档
  - 配置格式变更: `strict_mode` → `strictness` (advisory|strict|superpowers)

- **brainstorm** - v1.1.0 结构优化完成
  - SKILL.md 优化 (1723 → 357 行, -79%)
  - 完整实现 Phase 1-4 核心框架

### Removed

- tdd-enforcer Python 实现:
  - `cache.py`, `config.py`, `diff_analyzer.py`
  - `state_persistence.py`, `state_tracker.py`
  - `test_runners/`, `validators/`, `hooks/`, `tests/` 目录

### Design Philosophy

```yaml
v1.x (错误):
  问题: 把 Skill 当作 Python 包来开发
  - 创建大量 Python 模块
  - 实现复杂的类继承结构
  - 编写单元测试
  根本问题: Claude Code 不会导入执行这些 Python 代码

v2.0 (正确):
  方案: 参考 Superpowers，文档驱动设计
  - SKILL.md 描述工作流
  - AI 读取并理解流程
  - AI 按流程执行检查
  优势: 符合 Agent Skills 设计原则
```

## [1.2.0] - 2026-02-05

### Added

- **brainstorm** Skill - AI-DDD 协作思考引擎，通过多轮对话澄清需求、记录设计决策
  - 三种工作模式: `problem` (问题空间探索), `requirements` (需求分解), `technical` (技术方案设计)
  - 对话状态机: INIT → CLARIFY → EXPLORE → CONVERGE → SUMMARY → COMPLETE
  - 决策记录系统: 结构化记录"为什么选 A 而非 B"
  - 约束管理: 支持 business/technical/team 三类约束
  - 与 state-scanner/spec-drafter 深度集成

- **state-scanner 增强** - 新增头脑风暴推荐规则
  - `fuzziness_requirement`: 检测模糊需求，推荐 problem 模式
  - `missing_prd`: 复杂功能变更，推荐创建 PRD
  - `prd_refinement`: PRD 需要细化，推荐 requirements 模式
  - `tech_design_needed`: 有就绪 Story 无 OpenSpec，推荐 technical 模式

- **spec-drafter 增强** - 内置头脑风暴流程
  - PRD 创建时自动触发 requirements 模式
  - OpenSpec 创建时自动触发 technical 模式
  - 基于讨论结果预填充 proposal.md
  - 决策引用系统，支持完整追溯链

### Changed

- **workflow-runner** - 新增 A.0.5 步骤 (问题空间头脑风暴)
- **Skills 总数**: 24 → 25
- **Progressive Disclosure**: brainstorm SKILL.md 采用三层加载架构 (357 行主文件 + 按需引用)

### Fixed

- 优化 SKILL.md 文件大小 (1723 → 357 行, -79%)，符合最佳实践

## [1.1.1] - 2026-01-28

### Fixed

- **Skills 调用链配置优化** - 修复 `disable-model-invocation` 配置可能阻断 skill-to-skill 嵌套调用的问题

### Changed

- 采用分层控制策略，所有 24 个 skills 显式配置 `disable-model-invocation` 参数
- **入口层 (3个)** - 保持 `disable-model-invocation: true`
  - `workflow-runner` - 十步循环总入口
  - `api-doc-generator` - 独立功能，需用户指定框架
  - `arch-scaffolder` - 独立功能，需用户指定 PRD 路径
- **功能层 (21个)** - 改为 `disable-model-invocation: false`，允许被其他 skills 调用
  - Phase 阶段: phase-a-planner, phase-b-developer, phase-c-integrator, phase-d-closer
  - 核心功能: spec-drafter, task-planner, branch-manager, subagent-driver, commit-msg-generator, progress-updater, arch-update, branch-finisher, strategic-commit-orchestrator
  - 验证/扫描: state-scanner, requirements-validator, tdd-enforcer
  - 同步/搜索: forgejo-sync, requirements-sync, arch-search
  - 内部工具: agent-router, arch-common
- `agent-router` 和 `arch-common` 设置 `user-invocable: false`（内部工具，用户不需要直接调用）

## [1.1.0] - 2026-01-26

### Added

- 初始版本发布
- 24 个 Skills
- 10 个 Agents
- Hooks 系统 (SessionStart, SessionEnd, PreToolUse)
