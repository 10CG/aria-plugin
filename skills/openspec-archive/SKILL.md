---
name: openspec-archive
description: |
  归档已完成的 OpenSpec 变更到正确的 archive/ 目录，自动修正 CLI bug。

  使用场景："归档 Spec"、"Phase D.2"、"完成变更归档"
argument-hint: "[change-name]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# OpenSpec Archive (归档器)

> **版本**: 1.1.0 | **十步循环**: D.2
> **更新**: 2026-07-05 - #95 归档 gate 硬化: Step1 扩展 C 分级证据闸 (block 死代码 / warn 模糊) + 新增 Step7 D auto-issue (归档不吞未完成)
> **历史**: 2026-02-08 - 初始版本，修复 CLI 归档位置 bug

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- Spec 所有任务已完成，需要归档
- Phase D.2 收尾阶段
- 清理已完成的变更

**不使用场景**:
- Spec 仍有活跃任务 → 完成任务后再归档
- 需要继续修改 Spec → 保持变更活跃状态

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **状态验证** | 检查 Spec 完成状态和任务完成度 (#134 完成度二元判定) |
| **完成声称真实性证据闸 (#95)** | C 分级 (🔴 block 高置信死代码 / 🟠 warn 模糊声称) — 验 tasks.md `[x]` 代码集成类声称有无真实生产语义引用 |
| **执行归档** | 调用 openspec archive CLI |
| **自动修正** | 修正 CLI 的归档目录位置 bug |
| **清理验证** | 清理空目录，验证最终结果 |
| **D auto-issue (#95)** | 归档不吞未完成 — deferred/unverified 项自动建 Forgejo tracker issue (幂等 + headless 默认) |

---

## ⚠️ 已知 Bug: OpenSpec CLI 归档位置错误

**问题**: `openspec archive` CLI 命令有 bug，输出到错误位置：

```
❌ CLI 输出: openspec/changes/archive/YYYY-MM-DD-{feature}/
✅ 正确位置: openspec/archive/YYYY-MM-DD-{feature}/
```

**本 Skill 会自动修正此问题**。

---

## 正确的目录结构

```
openspec/
├── archive/                    # ✅ 正确的归档位置
│   └── YYYY-MM-DD-{feature}/
│       ├── proposal.md
│       ├── tasks.md
│       └── detailed-tasks.yaml
└── changes/                    # 活跃变更
    └── {active-feature}/
```

---

## 执行流程

### 输入

```yaml
change_name:
  required: true
  description: 要归档的变更目录名
  example: "cloudflare-access-auto-handling"

options:
  skip_verification: false     # 仅跳过 tasks.md [x] 校验 (v1.42.0+ 收口: 不绕过 Status 归一化 gate)
  keep_changes_copy: false     # 在 changes/ 中保留副本
  dry_run: false               # 仅验证不执行 (三路输出, 见示例 3)
  archive_design_only: false   # 逃生舱 (--archive-design-only): 归档未实施稿, 须配 reason
                                # #95: 同一逃生舱也覆盖 "complete=true ∧ verdict=block" 死代码组合
                                # (见 Step 1 verdict 路由表) — 显式豁免时须在输出中同时回显
                                # 被豁免的 blocking_reasons, 不静默吞掉死代码判定
  reason: ''                   # archive_design_only 必填; ≥10 非空白字符, 拒纯空白
  ack_unverified: ''            # #95 可选, 交互模式人工确认 unverified_claims (仅记录, 不影响 D 是否建 issue — 见 §D ack 解耦)
```

### 步骤

```yaml
Step 1 - 完成 gate + C 分级证据闸 (#134 v1.42.0+ 完成度 ∧ #95 tri-state verdict):
  # ── 前置 (最前): already-archived 检查 ──
  already_archived_precheck:
    检查: ls openspec/archive/ | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}-{change_name}$'  # 日期前缀锚定防后缀误匹配  # 已存在对应条目?
    若已存在: 立即 abort (BLOCKED-already-archived)
    约束: 不进入完成度判定、不写任何标记 (标记写入属 Step 2, abort 路径零残留)

  # ── 完成 + C 分级判定: Bash 调单一可执行 SOT (--gate tri-state 模式), 不再由 AI 解释 prose ──
  # #95 TG-2: 原 legacy 二元调用 (`python3 spec_complete.py <spec_dir>`) 改为统一走 --gate 模式 ——
  # 一次调用同时拿到 #134 的 complete/complete_reason (字段不变, 只是改从同一份 JSON 里读)
  # 和 #95 新增的 tri-state verdict, 不必两次调脚本。
  gate_result:
    命令: |
      python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/state-scanner/scripts/lib/spec_complete.py" \
        --gate "openspec/changes/{change_name}"
    读取: stdout JSON {complete, complete_reason, verdict, blocking_reasons[], warnings[],
                       unverified_claims[{claim,reason,symbols}], d_payload, soft_errors[]}
      # runtime-probe-archive-gate-integration (#95 follow-up A) 条件字段: 上方 JSON 可能
      # 另含 `runtime_probe: {outcome, count, reason, symbol, ts}` —— 仅当 proposal.md
      # frontmatter 声明了 `runtime_probe:` 时才出现 (outcome ∈ pass|warn|skipped|invalid;
      # ts = 本次评估时刻 ISO-8601 UTC); 无声明的 spec 该键整体不存在 (非 null 占位, SC-1)。
      # Step 2 warn_overlay 落盘时只取其中 outcome/count/ts/symbol 四字段 (reason 不落盘,
      # 已在对应 unverified_claims 条目里承载, 见下方 Step 2 warn_overlay)。
    exit_code: 0 = allow (verdict∈{pass,warn}) / 1 = block (verdict=block)
      # code-review fix #95: --gate 的 usage 错 / gate 意外 crash 现 **fail-toward-warn**
      # (verdict=warn + exit 0 + loud soft_error/stderr), 不再 exit 2 "视同 block" —— gate
      # 侧故障宁放行也不误 block 合法归档 (SC 既有正常归档零影响)。仍读 `verdict` 做路由。
    消费约束: 读 JSON `verdict` 字段做路由决策 (tri-state 契约), **不能只看 exit code** ——
      exit code 只是 pass|warn 二合一的粗粒度信号, 无法区分 pass 与 warn (两者都需继续 Step 2,
      但 warn 需额外写 frontmatter + surface 提示)。
    # 多入口一致 verdict 不变量 (AC-1): 本 gate 与 collectors/openspec.py import 调用、
    # phase-d-closer D.2 skip_evaluation 必须对同一 spec_dir 得到相同 verdict/complete

  # ── verdict 路由表 (#95 扩展: complete 二元 ⊗ verdict 三态, 二者正交独立判定) ──
  verdict_routing:
    # complete=true (tasks.md 全 [x] 或 Status=done)
    "complete=true  ∧ verdict=pass": 放行 → 进 Step 2 路径 (a) 正常归档
    "complete=true  ∧ verdict=warn": 放行 → 进 Step 2 路径 (a) 正常归档 +
      surface warnings + 写 frontmatter unverified_claims (见 Step 2 warn 子路径) +
      交互模式可选 --ack-unverified <reason> 记录人工确认 (非阻塞, 见下)
    "complete=true  ∧ verdict=block": |
      **BLOCK** (PP-R1 cr fix — 高置信死代码, 即便 tasks 全勾也不放行; 与 #134 遗留的
      "tasks 全[x]即视为完成" 直觉相反, 这正是本 gate 存在的原因: 完成是勾出来的不是跑出来的)
      回显 blocking_reasons (点名符号 + "zero production semantic reference")
      不配逃生舱 → 中止归档; 配 archive_design_only+reason(有效) → 见下方 escape-hatch 行,
      放行但须在输出中显式回显 "此归档豁免了 C-block(死代码判定)"
    "complete=false ∧ archive_design_only=true":
      reason 校验: 去除空白字符后 ≥10 字符 (拒纯空白/过短)
      校验失败: abort (BLOCKED-invalid-reason)
      校验通过: 放行 → 进 Step 2 路径 (b) design-only 归档
        (若同时 verdict=block, 输出须同时回显 complete_reason 与 blocking_reasons 两组缺口,
         不得只提其一 — 逃生舱一次性豁免两条独立判定轴)
    "complete=false ∧ verdict∈{pass,warn} ∧ 未配逃生舱":
      默认 BLOCK (#134 既有行为不变) — 回显 spec_complete.py 的 complete_reason 列出缺口
      (未完成 task 数 / Status 归一化值 / carry-forward 注释数), 中止归档
    "complete=false ∧ verdict=block ∧ 未配逃生舱":
      默认 BLOCK — 回显 complete_reason **与** blocking_reasons 两组缺口 (双重不完整,
      非二选一提示), 中止归档

  # ── skip_verification 收口 (v1.42.0+, 与 #95 verdict 轴正交不变) ──
  skip_verification_scope:
    语义: 仅跳过 tasks.md [x] 校验, 不绕过 Status 归一化 gate, **也不绕过 C-block**
    约束: 缺 tasks.md 且 normalized Status 非 'done' 时, skip_verification=true 也 BLOCK;
      verdict=block 时 skip_verification=true 同样不放行 (C-gate 与 skip_verification 无关联)
    backward_compat_shim: 旧 skip_verification=true 且未配 archive_design_only
      → WARN + abort (不静默降级), 提示改用 --archive-design-only + reason

Step 2 - 写 proposal.md (三路径分叉 + warn 覆盖层; 标记写入属本步, 非 Step 1 副作用):
  读取: openspec/changes/{change_name}/proposal.md
  路径 (a) 正常归档 (complete=true):
    更新: Status 非 done 时更新为 Complete (向后兼容既有行为)
  路径 (b) design-only 归档 (archive_design_only=true):
    不改 Status — 仅 frontmatter 追加机读字段:
      archive_type: implementation-deferred
      archived_reason: "{reason}"
    # 消费侧: state-scanner collectors/openspec.py archive 循环读 archive_type (round-trip)
  路径 (c) dry_run=true:
    不写入任何文件 (见 dry_run 三路输出说明)

  # ── warn 覆盖层 (#95 PP-R3 qa/ba Major fix, SC-8): 与 (a)/(b) 正交叠加, 非独立第四路径 ──
  # 触发: Step 1 gate_result.verdict == "warn" (可与路径 a 或路径 b 同时成立)
  warn_overlay:
    触发条件: gate_result.verdict == "warn"
      # runtime-probe-archive-gate-integration (#95 follow-up A): 本触发条件对齐宿主原语义,
      # 不扩展不收窄 —— runtime_probe 折入不改变触发 warn_overlay 的判据, 只在该条件已成立
      # 的写入批次里额外可能带上 runtime_probe 键 (是否带上见下方"内容归属条件", 与本条件正交)。
    写入 (真写入 proposal.md frontmatter, 镜像路径 (b) archive_type/archived_reason 的写入模式,
          全新字段 — 现有 SKILL.md 无此字段, 首次落地):
      写入位置 (无既有 frontmatter 块时的插入规则, 118/118 现有归档 proposal.md 现状 —
        规则承载下方全部键, 不限于 runtime_probe): proposal.md 文本**不以 `---` 开头**
        (无既有 frontmatter 块) → 在**文件绝对起始**插入一个新块: 首行 `---`、随后各键、
        末行 `---` (与既有 `_frontmatter_block()`/`_FRONTMATTER_RE` 的解析语义严格对齐 ——
        起始行前无任何前导字符/空行), 原有正文内容整体下移 (不覆盖不截断); 文本**已以
        `---` 开头** (已有 frontmatter 块) → 在既有块内**追加**下方键 (不新起第二个
        `---...---` 块, 不重复分隔符)。
      unverified_claims:              # gate_result.unverified_claims 逐条落盘 (YAML list-of-object)
        - claim: "<tasks.md 声称原文行, 或 runtime_probe 条目的合成标签 'runtime_probe:<symbol>'>"
          reason: "<不可核验原因, 如 'symbol X unclassified reference form'>"
          symbols: ["<提取到的符号名, 可能为空数组>"]
        # ... 每条 unverified_claims 对应一个 list item (含 gate_result 折入的 probe-warn 条目)
      unverified_ack: <true|false>    # 是否提供了 --ack-unverified (headless 默认 false, 不影响 D 建 issue)
      unverified_ack_reason: "<--ack-unverified 提供的 reason, 未提供则省略此字段>"
      runtime_probe:                  # runtime-probe-archive-gate-integration (#95 follow-up A)
                                       # 条件键 —— 见下方"内容归属条件", 并非每次 warn_overlay
                                       # 触发都会写入
        outcome: "warn"|"invalid"        # 原样取自 gate_result.runtime_probe.outcome (仅此两态会落到此处)
        count: <int>                     # 原样取自 gate_result.runtime_probe.count
        ts: "<ISO-8601 UTC 时间戳>"        # 原样取自 gate_result.runtime_probe.ts (如 2026-07-05T12:00:00+00:00)
        symbol: "<声明中的 symbol 值>"      # 原样取自 gate_result.runtime_probe.symbol
        # 结果贡献仅以上 4 字段 (outcome/count/ts/symbol); gate_result.runtime_probe 另有 reason
        # 字段但**不落盘于此** —— 该原因已完整落在上方对应 unverified_claims 条目的 reason
        # 里, 此处不重复。归档后的 runtime_probe mapping 还含作者声明字段, 见下方
        # "同名键 merge-append 规则"
    runtime_probe 同名键 merge-append 规则 (带声明 spec 必然命中 —— 声明本身就是 frontmatter
      块, 故结果键与作者自写的 `runtime_probe:` 声明 mapping 同名同块; TASK-016 E2E 首次连续
      流程行使实证的契约缺口, 本条为其裁决): 结果写入 **merge-append 进同一 mapping** ——
      在既有 `runtime_probe:` mapping 内**追加** outcome/count/ts 三行 (symbol 已由声明承载
      则不重复写; 声明无效缺 symbol 时补写 probe 返回的 symbol), **不删除不修改任何作者声明
      字段** (partition/max_age_days/enabled_when 原样保留 —— 归档不改作者本体, 与下方
      「声明本身仍随 proposal.md 归档可见」同一 ethos)。不产生 YAML 重复键, 不新起第二个
      runtime_probe mapping。向前兼容: `extract_runtime_probe` 对 unknown scalar 子键宽容
      忽略, 归档后混合 mapping 仍解析为合法声明, 不制造「声明无效」噪音。**降级路径
      (作者值非块 mapping)**: 若作者的 `runtime_probe` 值不是块 mapping (如顶层
      flow-style `runtime_probe: {...}` —— 属文本层声明无效), merge-append 结构上
      不适用 → **保留作者行原样, 结果键不落盘** (不新起同名键 / 不产生重复键 / 不改写
      作者行); 「无法核验」信号已由同批 unverified_claims 条目完整承载, 无信息丢失。
      执行者若遇到既非裸 `runtime_probe:` 块行、又非上述降级形态的意外结构, **视为
      契约破坏显式报错**, 不得静默追加第二个同名键。
    runtime_probe 键内容归属条件 (与上方"触发条件"正交 —— 前者决定"这一批写不写", 本条件决定
      "这一批里包不包含 runtime_probe 键", R3 裁决): 是否写入 runtime_probe 键取决于**探针
      自身** `gate_result.runtime_probe.outcome ∈ {"warn", "invalid"}` (声明无效同样计入),
      与触发本次 warn_overlay 整批写入的门级 `verdict` 来源**无关**。即使门级 verdict 因其他
      无关声称被顶到 warn, 只要探针自身 outcome ∈ {"pass", "skipped"}, `runtime_probe` 键
      依然**不写** (SC-10 混合场景负控); `gate_result` 本身不含 `runtime_probe` 字段的 spec
      (未声明) 同样不写。pass/skipped 两态本身也**不落盘** (干净归档零噪音, 镜像
      unverified_claims 先例 —— pass 观测改由 SC-7 closure 报告/handoff 承载, 声明本身仍随
      proposal.md 归档可见)。
    与路径 (b) 共存: 若同批归档既 design-only 又 warn, frontmatter 同时含
      archive_type/archived_reason **和** unverified_claims/unverified_ack (**及可能的**
      runtime_probe) 字段, 互不覆盖
    dry_run=true: 同路径 (c), 只在 dry-run 报告中 **回显** 若执行将写入的 unverified_claims
      列表 **+ (若 `gate_result.runtime_probe.outcome ∈ {"warn", "invalid"}`) runtime_probe
      结构化结果** (outcome/count/ts/symbol, 同上方"内容归属条件"), 不实际写入 (对齐 3c
      逃生舱 dry-run 回显惯例; 保持归档前所见即所得)

  保存: (a)/(b) 路径 (含 warn_overlay 时) 写回 proposal.md; (c) 路径无写入

Step 3 - 执行 CLI 归档命令:
  命令: openspec archive {change_name} --yes
  等待: CLI 完成

Step 4 - 检测并修正归档位置:
  检测: openspec/changes/archive/ 是否存在
  如果存在:
    → 移动: openspec/changes/archive/* → openspec/archive/
    → 清理: rmdir openspec/changes/archive/
  如果不存在:
    → 验证: openspec/archive/YYYY-MM-DD-{change_name}/ 是否存在

Step 5 - 清理活跃变更目录 (可选):
  删除: openspec/changes/{change_name}/
  除非: keep_changes_copy = true

Step 6 - 验证归档结果:
  确认: 归档目录在 openspec/archive/ 下
  确认: 包含完整的 proposal.md, tasks.md, detailed-tasks.yaml

Step 7 - D auto-issue (归档不吞未完成, #95, 单一 owner):
  # 本 Step 是**唯一** issue 创建点 (proposal §What Changes 2 "单一 owner") —
  # phase-d-closer D.2 检出 deferred/unverified 后**委托**本 Step, 自己不建 issue,
  # 防双入口重复 (见 phase-d-closer SKILL.md §D.2)。

  触发: gate_result.d_payload (Step 1 --gate 调用已产出, 本 Step 直接复用, 不重新调脚本) != null
    # d_payload 由 lib 聚合 "tasks.md 未勾选项 + carry-forward 注释, 或 (tasks.md 缺失时)
    #   detailed-tasks.yaml 非-done status 项 + carry-forward 注释" (deferred) 与
    # "全部 unverified_claims" (无论 §Step2 warn_overlay 是否写了 --ack-unverified) 而来;
    # 干净归档 (无 deferred 且无 unverified) → d_payload=null → 本 Step 完全跳过, 不产生任何输出

  headless 默认 (#95 PP-R1 cr fix, v2.0 Layer 2 自主归档核心):
    无论交互模式是否提供 --ack-unverified, 本 Step 判定只看 d_payload 是否非 null,
    **不看** ack 状态 — un-acked 的 unverified claim 更危险, 更需要兜底 (proposal "ack 解耦")。
    这使 headless/无人值守归档也会自动创建 tracker (非 stall 非静默)。

  backend 检测 (对称 aria-report 的路由风格, 但仅 2 级 — 非-Forgejo 明确降级为草稿, 不追加
  GitHub 自动创建通道, 见 proposal Out-of-scope):
    命令: command -v forgejo >/dev/null 2>&1 && git remote get-url origin 2>/dev/null | grep -qE '10cg\.pub|forgejo'
    backend=forgejo: 走下方 forgejo 创建流程
    backend=其它 (非-Forgejo 项目 / forgejo CLI 不可用): 降级 — 打印 d_payload.body 作为
      "待创建 issue 草稿" + 提示用户在项目自己的 issue tracker 手动创建, 不尝试调用其它平台 API

  owner/repo 解析 (code-review fix #95: 显式化 {owner}/{repo}, 降 headless Layer 2 歧义):
    命令: git remote get-url origin
    行为: 从 URL 抽 owner/repo —— 形如 `.../{owner}/{repo}.git` 或 `git@host:{owner}/{repo}.git`,
      取末两段路径去 `.git` 后缀 (如 `ssh://forgejo.10cg.pub/10CG/Aria.git` → owner=10CG repo=Aria)。
    失败 (无 origin / 解析不出): 降级为草稿模式 (同"backend=其它"), 不带未解析占位符盲调 API。

  幂等 / 去重 (search-before-create, marker = d_payload.marker = `<!-- archive-tracker:{spec_id} -->`):
    命令: | # code-review fix #95: 分页遍历全部 open issue (原 limit=50 无翻页, open issue>50 会漏既有 tracker → 重复开)
      page=1; found=""
      while :; do
        batch=$(forgejo GET "/repos/{owner}/{repo}/issues?state=open&limit=50&page=${page}" 2>&1)
        # 用 python3 (非 jq — shell-jq-crlf-hygiene) 在每个 issue.body 搜 marker 精确子串; 输出命中 number 或空
        hit=$(printf '%s' "$batch" | python3 -c 'import sys,json;m=sys.argv[1];d=json.load(sys.stdin);print(next((str(i["number"]) for i in d if m in (i.get("body") or "")), ""))' "{marker}")
        [ -n "$hit" ] && { found="$hit"; break; }
        # 本页不足 50 条 = 最后一页, 停止翻页
        n=$(printf '%s' "$batch" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))')
        [ "$n" -lt 50 ] && break
        page=$((page+1))
      done
    判定: marker (HTML 注释) 精确子串匹配, 非模糊 title 匹配 — 对已存在 issue 100% 精确定位,
      同一 spec_id 重复归档/重跑不重复开 issue; 分页确保 open issue>50 的仓库也不漏
    命中 (found 非空): 跳过创建, 输出 "已存在 tracker issue #{found}, 未重复创建"
    未命中: 继续创建

  SHA 回链填充 (已知设计取舍, 见下 "已知限制"):
    命令: git rev-parse --short HEAD
    行为: 用该 SHA 替换 d_payload.body 中的占位行
      "> 归档 SHA 回链: 由 openspec-archive Step2 归档提交后填入"
      → "> 归档 SHA 回链: {sha} (Step 1-6 归档动作完成时的 HEAD)"
    已知限制: 本 Skill 自身不执行 git commit (Phase D 的提交由调用方/用户在 D 阶段收尾时统一提交,
      参见 phase-d-closer §D.3 "提示 user commit handoff doc" 同惯例) — 此处捕获的 SHA 是
      **归档动作发生时**的 HEAD, 不必然是"归档变更被提交"的那个 commit。若调用方需要精确的
      归档提交 SHA, 应在实际提交后于 issue 下追评论补充 (本 Skill 不强制, 不阻塞)

  创建 (未命中幂等检查时):
    命令: |
      forgejo POST "/repos/{owner}/{repo}/issues" -d '{
        "title": "[Archive Tracker] {spec_id} — 归档残留待办",
        "body": "{d_payload.body (SHA 回链已填充)}"
      }'
    Rule #7 secret 卫生: 打印命令输出前确认响应体只含 issue 元数据 (number/url/title),
      不含 Authorization/token 字段; forgejo CLI wrapper 本身不回显请求头, 无需额外 redirect

  API 失败路径 (不静默, proposal §What Changes 2):
    判定: forgejo POST 非 2xx / curl 网络错误 / CLI 缺失
    行为: 打印 d_payload.body 完整草稿到对话 (chat-visible) + WARN 提示 API 失败原因,
      **归档不因此 abort** (Step 1-6 已成功完成, 本 Step 失败只影响"是否自动建了 tracker",
      不影响归档本身) — 绝不静默 fail-soft 吞掉残留工作可见性 (对称 D 的 "非静默" 设计原则)

  输出:
    d_issue_created: true|false
    d_issue_number: <int>|null
    d_issue_url: "<url>"|null
    d_issue_skip_reason: "clean_archive"|"duplicate_found"|"non_forgejo_backend"|"api_failed"|null
```

---

## 输出格式

```yaml
success: true
change_name: "cloudflare-access-auto-handling"
archive_path: "openspec/archive/2026-02-08-cloudflare-access-auto-handling"
cli_bug_fixed: true
warnings: []
verification:
  archive_exists: true
  contains_proposal: true
  contains_tasks: true
  contains_detailed_tasks: true
  wrong_dir_cleaned: true
# #95 新增字段 (verdict=warn 或 d_payload 非 null 时出现; 干净归档时省略, 向后兼容):
gate_verdict: "pass"|"warn"|"block"
unverified_claims_written: false        # true 时对应 Step 2 warn_overlay 已写 frontmatter
runtime_probe_written: false            # runtime-probe-archive-gate-integration (#95 follow-up A)
                                         # additive 字段, 与 unverified_claims_written 同一可见性
                                         # 条件 (verdict=warn 或 d_payload 非 null 时出现; 干净归档
                                         # 或无 runtime_probe 声明时省略) 但独立取值: 仅当探针自身
                                         # outcome ∈ {warn, invalid} 且 runtime_probe 键已落盘才为
                                         # true —— unverified_claims_written=true 不蕴含本字段为
                                         # true (混合场景: probe=pass 但其它声称致
                                         # unverified_claims_written=true 而本字段=false, 见 Step 2
                                         # warn_overlay 内容归属条件)
d_issue_created: false
d_issue_number: null
d_issue_url: null
```

---

## 使用示例

### 示例 1: 标准归档

```yaml
输入:
  change_name: "cloudflare-access-auto-handling"

执行:
  Step 1: ✅ gate_result verdict=pass (complete=true, 无死代码声称)
  Step 2: ✅ 更新 proposal.md 状态
  Step 3: ✅ 执行 openspec archive
  Step 4: ✅ 修正归档位置 (检测到 CLI bug)
  Step 5: ✅ 清理活跃变更目录
  Step 6: ✅ 验证归档结果
  Step 7: ⏭️ 跳过 (d_payload=null, 无 deferred/unverified, 干净归档)

输出:
  ✅ 归档成功
  📍 位置: openspec/archive/2026-02-08-cloudflare-access-auto-handling
  🐛 CLI bug 已自动修正
```

### 示例 2: 未完成任务

```yaml
输入:
  change_name: "incomplete-feature"

执行:
  Step 1: ❌ 完成 gate BLOCK (gate_result complete=false, verdict=pass — 纯 completeness 缺口,
          无死代码/模糊声称问题)
  complete_reason 回显: "tasks.md has 2/4 unchecked task(s); normalized Status = 'approved' (≠ done)"
  未完成:
    - [ ] Task 3: 实现错误处理
    - [ ] Task 4: 添加单元测试

输出:
  ❌ 归档中止 (默认 BLOCK)
  原因: spec_complete.py 判定 complete=false (缺口见 complete_reason 回显)
  建议: 完成所有任务后再执行归档; 确需归档未实施稿 → --archive-design-only + reason
```

### 示例 3: Dry Run (三路输出)

> dry_run=true 执行 Step 1 gate 全部判断 (already-archived 前置 + tasks.md + Status + 标记读取),
> 报告三路结果并保持"不实际写入"不变量。
> **注**: dry_run 三路完全基于 (a) CLI flag (b) 本地 tasks.md (c) proposal.md Status —
> 均由本 Skill 直接读取, **不依赖** state-scanner snapshot 预计算字段。
> **术语消歧 (#95)**: 下方 3a/3b/3c 示例中的 `verdict:` 前缀是历史遗留的**展示文字标签**
> (表示"本次 completeness 判定结果"), **不是** #95 新增的 JSON `verdict` 枚举字段
> (`pass`/`warn`/`block`)。dry_run 复用同一个 `--gate` 调用 (Step 1 gate_result 不区分
> dry_run 与否, 都读同一份 JSON), 因此 3a/3b/3c 场景下 `gate_verdict` 字段实际都是 `pass`
> (无死代码/模糊声称声称), 只是 completeness 二元判定 (`complete`) 独立为 true/false ——
> 3e 补充 dry_run 下 `gate_verdict=block` 的场景, 二者不冲突。

#### 3a: BLOCKED (未完成且未配逃生舱)

```yaml
输入:
  change_name: "test-feature"
  dry_run: true

输出:
  📋 Dry Run 结果: ❌ BLOCKED
  verdict: complete=false
  reason 回显: "tasks.md has 1/4 unchecked task(s); normalized Status = 'approved' (≠ done)"
  声明: 未发生任何写入 (dry_run)
  建议: 完成缺口后重试, 或 --archive-design-only + reason
```

#### 3b: ALLOWED (完成, 正常归档可执行)

```yaml
输入:
  change_name: "test-feature"
  dry_run: true

输出:
  📋 Dry Run 结果: ✅ ALLOWED
  verdict: complete=true ("tasks.md 全 [x] (4 task(s), 无 carry-forward/defer 注释)")
  预期归档路径: openspec/archive/2026-02-08-test-feature
  声明: 未发生任何写入 (dry_run)
  建议: 可以安全执行归档
```

#### 3c: ALLOWED-design-only (逃生舱 + reason 回显)

```yaml
输入:
  change_name: "design-doc-feature"
  dry_run: true
  archive_design_only: true
  reason: "方案被 DEC-20260609-001 替代, 仅存档设计稿供追溯"

输出:
  📋 Dry Run 结果: ✅ ALLOWED-design-only
  verdict: complete=false (逃生舱放行)
  reason 回显: "方案被 DEC-20260609-001 替代, 仅存档设计稿供追溯"
  若执行将写入 frontmatter: "archive_type: implementation-deferred" + archived_reason
  声明: 未发生任何写入 (dry_run)
```

#### 3d: reason 校验拒绝 (BLOCKED-invalid-reason)

```yaml
输入:
  change_name: "design-doc-feature"
  dry_run: true
  archive_design_only: true
  reason: "  存档  "        # 去除空白后 < 10 字符

输出:
  📋 Dry Run 结果: ❌ BLOCKED-invalid-reason
  原因: reason 不足 10 非空白字符 (拒纯空白)
  声明: 未发生任何写入 (dry_run)
  建议: 提供 ≥10 非空白字符的实质性 reason
```

#### 3e: C-block dry-run (#95, complete=true 但 gate_verdict=block)

```yaml
输入:
  change_name: "multi-terminal-coordination"
  dry_run: true

输出:
  📋 Dry Run 结果: ❌ BLOCKED (C-block, 非 completeness BLOCK)
  completeness: complete=true ("tasks.md 全 [x] (12 task(s), 无 carry-forward/defer 注释)")
  gate_verdict: block
  blocking_reasons: ["symbol 'phase1_gate' (claim: '集成 state-scanner') has zero production semantic reference (dead-code-on-arrival)"]
  声明: 未发生任何写入 (dry_run)
  建议: 补齐集成后重试, 或 --archive-design-only + reason (同时豁免 completeness 与 C-block, 若两者皆缺口)
```

### 示例 4: C-block 高置信死代码 (#95, complete=true 但仍 BLOCK)

```yaml
输入:
  change_name: "multi-terminal-coordination"   # Layer L golden 负例

执行:
  Step 1: ❌ gate_result complete=true 但 verdict=block
    blocking_reasons: ["symbol 'phase1_gate' (claim: '集成 state-scanner') has zero
                        production semantic reference (dead-code-on-arrival)"]

输出:
  ❌ 归档中止 (BLOCK — 高置信死代码, 即便 tasks.md 全 [x])
  原因: phase1_gate 在 3 个生产 collector 中只有注释/docstring 提及, 剥离后零真实
        代码引用/dynamic-dispatch/集成面/通用路径调用
  建议: 补齐 phase1_gate 的实际集成后重试; 确认此声称属实但暂缓集成 →
        --archive-design-only + reason (逃生舱同时豁免死代码判定, 见下方豁免变体)
```

**豁免变体** (owner 显式承认残留, 仍需归档):

```yaml
输入:
  change_name: "multi-terminal-coordination"
  archive_design_only: true
  reason: "phase1_gate 集成推迟到 #94 follow-up, 本次先归档设计稿"

执行:
  Step 1: ⚠️ verdict=block 但逃生舱有效 → 放行 (路径 b), 输出显式回显 blocking_reasons 未被吞掉
  Step 2: ✅ 写 frontmatter archive_type=implementation-deferred + archived_reason
  Step 3-6: ✅ 正常归档流程
  Step 7: ✅ d_payload 非 null (含未完成 deferred 项) → 创建 tracker issue #201

输出:
  ⚠️ 归档完成 (逃生舱豁免了 C-block 死代码判定, 非静默通过)
  🎫 已建 tracker issue: https://forgejo.10cg.pub/10CG/Aria/issues/201
```

### 示例 5: C-warn 模糊声称 + D auto-issue (#95)

```yaml
输入:
  change_name: "some-dogfood-heavy-spec"

执行:
  Step 1: ⚠️ complete=true, verdict=warn
    unverified_claims: [{claim: "dogfood 验证通过", reason: "无可链接产物路径", symbols: []}]
  Step 2: ✅ 正常归档 (路径 a) + warn_overlay 写入 frontmatter:
    unverified_claims: [...]
    unverified_ack: false   # 本次未交互提供 --ack-unverified (headless 默认场景)
  Step 3-6: ✅ 正常归档流程
  Step 7: ✅ d_payload 非 null (unverified_claims 非空, 无论 ack 与否都进 payload)
    → 幂等检查未命中既有 issue → 创建 tracker issue #202

输出:
  ⚠️ 归档完成, 1 条声称无法静态核验 (已写入 frontmatter)
  🎫 已建 tracker issue: https://forgejo.10cg.pub/10CG/Aria/issues/202
```

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 变更目录不存在 | change_name 拼写错误 | 检查 openspec/changes/ 目录 |
| 完成 gate BLOCK | spec_complete.py 判定 complete=false | 完成缺口后重试; 确需归档未实施稿 → `--archive-design-only` + reason |
| **C-block (#95)** | verdict=block — 点名符号零生产语义引用 (高置信死代码, 可与 complete=true 共存) | 补齐集成后重试; 确认残留待补 → `--archive-design-only` + reason (逃生舱同时豁免, 见示例 4) |
| BLOCKED-invalid-reason | reason 不足 10 非空白字符 (含纯空白) | 提供 ≥10 非空白字符的实质性 reason |
| BLOCKED-already-archived | openspec/archive/ 已存在对应条目 (Step 1 前置 abort) | 检查是否已归档; 不重复写标记 |
| `--force` (DEPRECATED) | 旧绕过通道, v1.42.0+ 收口 | 改用 `--archive-design-only` + reason (可追溯逃生舱) |
| skip_verification=true 未配逃生舱 | backward-compat shim 触发 | WARN + abort (不静默降级); 改用 `--archive-design-only` + reason |
| CLI 命令失败 | openspec CLI 未安装 | 安装 openspec CLI |
| 权限不足 | 无法移动/删除文件 | 检查文件权限 |
| **Step 7 非-Forgejo backend (#95)** | `forgejo` CLI 不可用 / remote 非 Forgejo | 降级打印 d_payload.body 待创建草稿, 提示手动在项目 issue tracker 创建; 归档本身不受影响 |
| **Step 7 API 失败 (#95)** | forgejo POST 非 2xx / 网络错误 | 打印 d_payload.body 完整草稿 + WARN, 不静默; 归档 (Step 1-6) 已完成, 不因此 abort |
| **Step 7 重复归档同 spec (#95)** | marker 幂等检查命中既有 open issue | 跳过创建, 输出既有 issue 编号, 不重复开 |

---

## 与其他 Phase 的关系

```
phase-d-closer
    │
    │ D.1 - 进度更新 (progress-updater)
    │   └── 更新 UPM 进度状态
    │
    │ D.2 - Spec 归档 (openspec-archive) ◄── 本 Skill
    │   ├── Step 1 验证完成状态 + C 分级证据闸 (#95)
    │   ├── Step 2 写 proposal.md (含 warn frontmatter, #95)
    │   ├── Step 3-6 执行归档 / 修正 CLI bug / 验证结果
    │   └── Step 7 D auto-issue (归档不吞未完成, #95, 单一 owner)
    │
    ▼
完成闭环
```

---

## 相关文档

- **Phase D 规范**: `standards/core/ten-step-cycle/phase-d-closure.md`
- **OpenSpec 项目规范**: `standards/openspec/project.md`
- **归档目录说明**: `openspec/archive/README.md`
- **已知 Bug 列表**: `standards/openspec/AGENTS.md`
- **#95 Spec**: `openspec/changes/aria-archive-gate-runtime-reality/proposal.md` (主仓, C 分级证据闸 + D auto-issue 设计 SOT)
- **spec_complete.py --gate 契约**: `state-scanner/scripts/lib/spec_complete.py` module docstring (tri-state gate_result 完整 schema)

---

## 变更历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.1.0 | 2026-07-05 | #95 归档 gate 硬化: Step 1 扩展 C 分级证据闸 (tri-state verdict, `--gate` 契约) + Step 2 warn frontmatter 覆盖层 + 新增 Step 7 D auto-issue (单一 owner + 幂等 + headless 默认) |
| 1.0.0 (含 #134 v1.42.0+ 完成度 gate, 本表历史未及时补记) | 2026-02-08 | 初始版本，实现 CLI bug 自动修正 |

---

**最后更新**: 2026-07-05
**Skill版本**: 1.1.0
