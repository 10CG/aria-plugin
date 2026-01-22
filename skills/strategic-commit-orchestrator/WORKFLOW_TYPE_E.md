# 工作流程 - 类型E: 全项目变更

> **版本**: 2.2.0
> **职责**: 主项目 + 子模块协同提交流程

本文档定义类型E（全项目变更）的完整工作流程，支持一次调用完成主项目和所有子模块的分组提交。

**适用场景**:
- 主项目有变更 **且** 至少一个子模块有变更
- 大型功能开发涉及多个模块
- OpenSpec 变更跨越主项目和子模块

**📚 文档导航**:
- **入口文档** → [SKILL.md](./SKILL.md)
- **变更类型识别** → [CHANGE_TYPES.md](./CHANGE_TYPES.md)
- **通用流程** → [WORKFLOW_CORE.md](./WORKFLOW_CORE.md)
- **子模块指南** → [SUBMODULE_GUIDE.md](./SUBMODULE_GUIDE.md)

---

## 流程概览

```
┌─────────────────────────────────────────────────────────┐
│  Phase 0: 全项目状态扫描                                 │
│  - 0.1 扫描主项目变更                                    │
│  - 0.2 扫描所有子模块变更                                │
│  - 0.3 构建变更地图 (change_map)                         │
│  - 0.4 确定执行策略                                      │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│  Phase 1-6: 子模块分组提交 (循环)                        │
│  FOR each submodule in change_map.submodules:           │
│    - 切换到子模块目录                                    │
│    - 执行标准分组提交流程 (Phase 2-6)                   │
│    - 记录 commit hash                                   │
│  END FOR                                                │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│  Phase 7: 主项目分组提交                                 │
│  - 7.1 执行主项目文件分组提交                            │
│  - 7.2 更新子模块引用                                    │
│  - 7.3 创建引用更新提交                                  │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│  Phase 8: 验证与汇总                                     │
│  - 8.1 验证所有提交                                      │
│  - 8.2 输出提交汇总报告                                  │
└─────────────────────────────────────────────────────────┘
```

---

## Phase 0: 全项目状态扫描

### 步骤 0.1: 扫描主项目变更

```bash
# 获取主项目变更（排除子模块内部变更）
git status --short --ignore-submodules=dirty

# 示例输出:
# M  .claude/skills/state-scanner/SKILL.md
# M  CLAUDE.md
# M  standards (modified content)  ← 子模块有内部变更
```

### 步骤 0.2: 扫描所有子模块变更

```bash
# 获取所有子模块状态
git submodule status

# 检测每个子模块的内部变更
git submodule foreach --quiet '
  changes=$(git status --short 2>/dev/null | wc -l)
  if [ "$changes" -gt 0 ]; then
    echo "$name:$changes"
  fi
'

# 示例输出:
# standards:15
# mobile:0
# backend:0
```

### 步骤 0.3: 构建变更地图

```yaml
change_map:
  # 主项目变更
  main_project:
    has_changes: true
    file_count: 5
    files:
      - .claude/skills/state-scanner/SKILL.md
      - .claude/skills/workflow-runner/WORKFLOWS.md
      - CLAUDE.md
      - CLAUDE.local.md
      - docs/project-planning/unified-progress-management.md
    change_type: B  # 主项目变更

  # 子模块变更列表
  submodules:
    standards:
      has_changes: true
      file_count: 15
      change_type: C  # 跨项目共享基础设施
      commit_hash: null  # 提交后填充

    mobile:
      has_changes: false

    backend:
      has_changes: false

    shared:
      has_changes: false

    .claude/agents:
      has_changes: false

  # 汇总
  summary:
    total_submodules: 5
    changed_submodules: 1
    main_has_changes: true
    overall_type: E  # 全项目变更
```

### 步骤 0.4: 确定执行策略

```yaml
execution_strategy:
  # 子模块执行顺序
  submodule_order:
    - standards    # 基础设施优先
    - shared       # 契约其次
    - backend      # 后端
    - mobile       # 前端

  # 并行策略
  parallel_mode: false  # 默认串行（安全）

  # 主项目时机
  main_after_submodules: true  # 必须在子模块之后

  # 引用更新策略
  ref_update_mode: separate_commit  # 独立提交 | merge_with_main
```

---

## Phase 1-6: 子模块分组提交

对每个有变更的子模块，执行标准分组提交流程。

### 子模块提交模板

```yaml
FOR each submodule in change_map.submodules WHERE has_changes == true:

  # 1. 切换到子模块目录
  cd {project_root}/{submodule_path}

  # 2. 识别子模块变更类型
  #    - standards → 类型C (跨项目共享)
  #    - mobile/backend → 类型A (业务子模块)

  # 3. 执行标准分组提交流程
  #    - 参考 WORKFLOW_TYPE_A/B/C.md
  #    - 参考 WORKFLOW_CORE.md (Phase 2-6)

  # 4. 记录最终 commit hash
  change_map.submodules[submodule].commit_hash = $(git rev-parse HEAD)

  # 5. 返回主项目目录
  cd {project_root}

END FOR
```

### 子模块变更类型映射

| 子模块 | 变更类型 | UPM处理 | 典型Subagent |
|--------|---------|---------|--------------|
| standards | C | 无UPM | knowledge-manager |
| .claude/agents | C | 无UPM | tech-lead |
| mobile | A | 读取子模块UPM | mobile-developer |
| backend | A | 读取子模块UPM | backend-architect |
| shared | A | 无UPM | api-documenter |

### 子模块提交示例

```bash
# === 处理 standards 子模块 ===
cd standards

# 分组提交 (参考 WORKFLOW_TYPE_C.md)
git add methodology/aria-brand-guide.md openspec/project.md
git commit -m "$(cat <<'EOF'
docs(brand): 创建 Aria 品牌指南 / Create Aria brand guide

🤖 Executed-By: knowledge-manager subagent
📋 Context: Phase1-Cycle1 evolve-ai-ddd-system
🔗 Module: standards
EOF
)"

# 记录 commit hash
# standards_hash=$(git rev-parse HEAD)

cd ..
```

---

## Phase 7: 主项目分组提交

### 步骤 7.1: 主项目文件分组提交

```yaml
# 按标准流程对主项目文件进行分组提交
# 参考 WORKFLOW_TYPE_B.md + WORKFLOW_CORE.md

主项目分组示例:
  Group 1: Skills 更新
    - .claude/skills/state-scanner/SKILL.md
    - .claude/skills/workflow-runner/WORKFLOWS.md

  Group 2: 配置更新
    - CLAUDE.md
    - CLAUDE.local.md

  Group 3: 进度文档
    - docs/project-planning/unified-progress-management.md
```

### 步骤 7.2: 更新子模块引用

```bash
# 将子模块的新 commit 添加到暂存区
git add standards
# git add mobile  (如果有变更)
# git add backend (如果有变更)

# 检查子模块引用状态
git diff --cached --submodule
```

### 步骤 7.3: 创建引用更新提交

```bash
git commit -m "$(cat <<'EOF'
chore(submodule): 更新子模块引用 / Update submodule references

更新以下子模块:
- standards: abc1234 → def5678 (6 commits)

🤖 Executed-By: knowledge-manager subagent
📋 Context: Phase8-Cycle1 evolve-ai-ddd-system
🔗 Module: main
🔗 Submodules: standards@def5678
EOF
)"
```

---

## Phase 8: 验证与汇总

### 步骤 8.1: 验证所有提交

```bash
# 验证主项目提交
git log --oneline -10

# 验证子模块状态
git submodule status

# 确保工作树干净
git status
```

### 步骤 8.2: 输出提交汇总报告

```markdown
## 全项目提交汇总

### 子模块提交

| 子模块 | 提交数 | 最终Hash | 状态 |
|--------|--------|----------|------|
| standards | 6 | eaad106 | completed |

### 主项目提交

| Commit | 类型 | 描述 |
|--------|------|------|
| cf03a38 | chore | 更新子模块引用 |
| 55e840e | docs | 配置更新 |
| 2944d4c | feat | Skills扩展 |

### 最终状态

- 主项目: clean
- 子模块: all synced
- 总提交数: 12 (主项目6 + standards 6)
```

---

## 快速检查清单

### 执行前

- [ ] 运行 `git submodule foreach git status` 确认子模块状态
- [ ] 确认所有子模块在正确的分支上
- [ ] 确认没有未解决的冲突

### 子模块提交时

- [ ] 每个子模块提交后记录 commit hash
- [ ] 确认子模块工作树干净后再处理下一个

### 主项目提交后

- [ ] 验证子模块引用已更新
- [ ] 运行 `git status` 确认工作树干净
- [ ] 检查 `git log` 确认所有提交

---

## 回滚指南

### 场景1: 子模块提交失败

```bash
# 在子模块中重置
cd {submodule}
git reset --hard HEAD~{n}  # 回滚n个提交
cd ..

# 不需要回滚其他已完成的子模块
# 修复问题后重新提交
```

### 场景2: 主项目提交失败

```bash
# 子模块提交已完成，只需处理主项目
git reset --hard HEAD~{n}

# 重新执行主项目分组提交
# 子模块引用会在新提交中包含
```

### 场景3: 需要完全回滚

```bash
# 1. 回滚主项目
git reset --hard {original_main_hash}

# 2. 回滚每个子模块
git submodule foreach 'git reset --hard {original_hash}'

# 3. 更新子模块引用
git submodule update --init --recursive
```

---

*本文档是 strategic-commit-orchestrator v2.2.0 的类型E工作流程指南。*
