# D.3 Session Handoff — Mechanics

> **关联**: H0 spec (2026-05-14), Forgejo aria-plugin #67 multi-track restructure (v1.30.2). L4 convention SOT: [standards/conventions/session-handoff.md](../../../../standards/conventions/session-handoff.md)。
> **共享 SOT (session-closer-synthesis, 2026-06-25)**: 本文档是 **handoff-write 机制的单一 SOT**, 由 **phase-d-closer D.3 (周期收尾)** 与 **session-closer step4 (会话收尾)** **共同引用, 不复制** (slug 规则 / 9 段模板 variable 字典 / latest.md 2 子步骤 / Rule #9 L1+L5 / Forbidden patterns 对两者通用)。下文「触发条件 4 级 fallback」是 D.3 专属; session-closer 由 owner 直接调用触发, write 机制共用。

## 目的

session 结束时**标准化引导**写 handoff doc, 让下一个 session AI/人 zero-context 可恢复优先级 + carry-forward。历史问题: handoff 写不写、写哪个 dir、什么格式各项目自发演进, 导致跨 session 上下文丢失 (4 起 dogfood 实证, 见 H0 spec)。

## 触发条件 (任一满足即 prompt user)

按 fallback 优先级评估 (F2 audit fix per backend-M1 — 信号缺失也能 prompt):

```yaml
trigger_level_1_primary:
  signal: workflow-state.json::session.started_at
  check: now - started_at > 4h
  fallback_if_missing: go to level 2

trigger_level_2_cycles_shipped:
  signal: git log since last `docs/handoff/*.md` mtime
  check: count distinct openspec/archive/{date}-*/ entries created > N >= 2
  command_hint_linux: |
    last_handoff_mtime=$(stat -c '%Y' $(ls -t docs/handoff/*.md | head -1))
  command_hint_macos: |
    last_handoff_mtime=$(stat -f '%m' $(ls -t docs/handoff/*.md | head -1))
  command_hint_portable: |
    # Python alternative (cross-platform, recommended for AI implementations):
    last_handoff_mtime=$(python3 -c "import os, glob; files=sorted(glob.glob('docs/handoff/*.md'), key=os.path.getmtime, reverse=True); print(int(os.path.getmtime(files[0])) if files else 0)")
  count_command: |
    git log --since="@$last_handoff_mtime" --diff-filter=A --name-only -- "openspec/archive/*/proposal.md" | sort -u | wc -l
  fallback_if_missing: go to level 3

trigger_level_3_phase_count:
  signal: count distinct "Phase {A,B,C,D}" markers in commit subjects since last handoff
  check: distinct phase count >= 2
  command_hint: |
    # uses $last_handoff_mtime computed in level 2 (portable)
    git log --since="@$last_handoff_mtime" --format="%s" | grep -oE "Phase [ABCD]" | sort -u | wc -l
  fallback_if_missing: go to level 4

trigger_level_4_user_prompt:
  prompt: |
    "本 session 是否符合 D.3 触发条件之一?
       (a) 跨度 > 4h
       (b) ship >= 2 cycles
       (c) 跨 >= 2 phases
     默认 yes (D.2 archive 已成功通常意味本 session 完整闭环)。
     选择: y / n / 详情 (查看 fallback 信号原始值)"
  default_if_silent: "yes" (D.2 archive 成功且 user 在场)
```

## 输出路径硬编码 (L5 enforcement, 不可修改)

```
docs/handoff/{YYYY-MM-DD}-{slug}.md

slug 规则 (优先级):
  1. user 提供 (如 "h0-cycle-done")
  2. cycle change_id 后缀 (如 "aria-ten-step-session-handoff-stage" → "h0-stage")
  3. fallback: "session-handoff"

同日重名 fallback:
  docs/handoff/{YYYY-MM-DD}-{HHMM}-{slug}.md
```

**绝对禁止**: 写 `.aria/handoff/*` (L1 PreToolUse hook 会拦; L4 convention SOT 显式 forbidden)。

## 模板使用

读 `aria/templates/session-handoff.md` (9-section skeleton), 按 variable 字典 substitute:

| Variable | 来源 |
|----------|------|
| `{project}` | `.aria/config.json::project.name` 或 git remote 推断 |
| `{date}` | `date -u +%Y-%m-%d` |
| `{cycle_name}` | spec change_id 或 user 提供 |
| `{session_duration}` | level 1/2/3 信号计算的实测值 |
| `{shipped_cycles}` | level 2 信号 count |
| `{memory_entries_count}` | `ls ~/.claude/projects/*/memory/*.md` since last handoff |
| `{next_session_entry}` | "/aria:state-scanner" (Aria projects); 其他项目按 `.aria/config.json::next_session_command` |
| `{start_date}` | 上次 handoff 的 last_modified_iso (from snapshot.handoff) |

## 写后 frontmatter 自校验 (#137 v1.43.0+, latest.md 维护的前置)

**`owner-container` 机械填, 勿手动组装** (DEC-20260704-002 §4, 病根 #3): 手填曾漂移出 6 种不一致值 (同一物理容器 3 种主串: `simonfishgit/dev-claude` / `simonfish/dev-claude` / 裸 `dev-claude`), 破坏 §2.3.5 cross-owner vs self-multi-container collision 分类 (看板把同一人误判成多 owner)。写 frontmatter 时逐字粘贴以下确定性输出 (复用 Layer L `identity.get_identity().owner_container`):

```bash
python3 aria/skills/session-closer/scripts/handoff_autofill.py --owner-container   # e.g. simonfish/bfe8285d
```

> best-effort: 命令失败 (空输出/exit 1) 时回退模板手填规则。若机械值是裸 uuid (`~/.aria/container-id` label 空), 可给该文件设人类 label 使值更可读 + 与历史一致 (owner env 动作)。

handoff doc 写出后、进入下方 latest.md 维护**之前**, 机械验证 §2.3.1 frontmatter 5 字段齐全:

```bash
head -8 <handoff-doc> | grep -cE '^(track-id|owner-container|phase|status|updated-at):'   # 须 ==5
```

不足 → 按模板派生规则 (`aria/templates/session-handoff.md` 头部 instructions) 补齐后重验; warn-then-fix, 非硬 abort (advisory-over-hardlock per DEC-20260519-001)。缺 frontmatter 的 handoff 会被 state-scanner Phase 1.15 以 `handoff_frontmatter_missing` soft warning 点名 (多 track 看板将显示 owner=unknown)。

## latest.md 维护 (mechanical, 2 个独立子步骤)

> **v1.30.2 重要变更** (Forgejo aria-plugin #67): 拆分为 2 个 mechanical 子步骤 + 加 multi-track 显式判定。原 single-track linear succession 模型在 multi-terminal coordination 场景下歧义, follower cycle 容易把"pointer 不动"误读为"latest.md 不动", **连 History prepend 也忘了做** (实证: nexus PR #107 漏 History entry, 后开 PR #109 补救)。

### 子步骤 1 (always, 不可跳过): History 表格 prepend 新条目

- 不管 single-track 还是 multi-track, follower 还是 leader, **都要做**
- 格式: `- {YYYY-MM-DD HH:MM} — [{name}](./{filename}) ({scope-note} — {summary})`
- 位置: 按 committerdate desc 排序; 同日多个 cycle 按 HH:MM 排; 同日 leader 先于 follower
- `{scope-note}`: 标 `leader` / `follower:{track-id}` / `(empty)` for single-track
- `{summary}`: 1 句话 ≤ 80 chars 描述 cycle 核心交付

### 子步骤 2 (conditional): Pointer 行 (`**Latest**:` 字段) 更新

判定逻辑 (mechanical, 检查 `snapshot.tracks_multibranch`):

| 场景 | Pointer 更新? | 理由 |
|------|--------------|------|
| **Single-track** (`tracks_multibranch.exists == false` 或 `len(tracks) <= 1`) | ✅ 更新到新 doc | 无多终端, pointer = 唯一 latest |
| **Multi-track + 本 cycle 是项目主线** (其他 container 无 `status==active` track in `tracks_multibranch`) | ✅ 更新到新 doc | 本 cycle 是主线, 接替 pointer |
| **Multi-track + 本 cycle 是 follower scope** (其他 container 有 `status==active` track + 当前 pointer 指向该 leader doc) | ❌ **不更新** pointer (保留 leader 主线 doc) | follower 不抢主线 |

- **前一 Latest 处理** (仅子步骤 2 触发时): 改为 "Active (parallel predecessor)" 或 "superseded" (由 user 判断)

### Edge cases

- **首个 follower cycle (无 leader doc)**: 退化为 single-track 模式, 做子步骤 1 + 2
- **Follower cycle 横跨 leader 主线写新 handoff**: rebase resolve 时仍应保留 follower History entry (per existing convention)

## Forbidden patterns (L5 hardcode)

- ❌ 写到 `.aria/handoff/` (L1 hook 会拦)
- ❌ 文件名含空格或特殊字符 (用 hyphen)
- ❌ 跳过 latest.md 子步骤 1 (History prepend) — **任何 cycle 都不可跳过**, 否则 cycle 在 latest.md 隐形 (实证: nexus PR #107)
- ❌ Multi-track follower **更新 pointer 行** (子步骤 2 在 follower 模式下应跳过, 保留 leader 主线 doc)
- ❌ 用 datetime.now() 计算 — 用 UTC `date -u`
