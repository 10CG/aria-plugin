---
name: tdd-enforcer
description: |
  强制执行测试驱动开发 (TDD) 工作流，使用 RED-GREEN-REFACTOR 循环确保测试先于代码编写。

  三级严格度：Advisory（警告）、Strict（强制）、Superpowers（完整循环）。

  使用场景：开发新功能时确保 TDD 最佳实践、代码质量审查。
disable-model-invocation: false
user-invocable: true
---

# TDD 强制执行器 (TDD Enforcer)

> **版本**: 2.0.0 | **设计**: 文档驱动 (Document-Driven)
> **更新**: 2026-02-06 - 重构为文档驱动设计
> **参考**: [Superpowers test-driven-development](https://github.com/obra/superpowers)

---

## 快速开始

### 我应该使用这个 skill 吗？

**使用场景**:
- ✅ 编写新功能代码时
- ✅ 需要确保测试覆盖率
- ✅ 代码质量检查前

**不使用场景**:
- ❌ 文档修改 → 无需 TDD
- ❌ 配置文件修改 → 一般跳过
- ❌ 重构已有测试 → 跳过 RED 阶段

---

## 配置 (config-loader)

执行前读取 `.aria/config.json`，缺失则使用默认值。参见 [config-loader](../config-loader/SKILL.md)。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `tdd.strictness` | `"advisory"` | 严格度: `advisory` / `strict` / `superpowers` |
| `security_commit_separation.enabled` | `false` | 安全代码 RED/GREEN commit 强制分离 (Aria #32; `.claude/tdd-config.json` 细粒度字段, strict/superpowers 下生效) |

**优先级**: `.aria/config.json` > `.claude/tdd-config.json` > Skill 默认值。`.claude/tdd-config.json` 中的细粒度字段 (`skip_patterns`, `test_patterns`, `security_commit_separation`) 继续在原位生效。

---

## 核心工作流

```
┌─────────────────────────────────────────────────────────────────┐
│                    TDD 工作流 (RED-GREEN-REFACTOR)              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   RED (失败测试)        GREEN (最小实现)      REFACTOR (重构)    │
│   ──────────────        ────────────────      ─────────────────   │
│                                                                 │
│   1. 编写测试           1. 编写最小代码        1. 优化结构       │
│   2. 运行测试           2. 运行测试            2. 提取抽象       │
│   3. 确认失败           3. 确认通过            3. 运行测试       │
│   4. 停止编码           4. 停止扩展            4. 确认通过       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三级严格度

### Level 1: Advisory (建议模式)

```yaml
触发: 用户编辑源代码时

检查:
  - 测试文件是否存在

违规处理:
  - 显示警告
  - 允许继续操作

输出示例:
  ⚠️ 未找到测试文件
  建议先编写失败的测试 (RED 阶段)

  期望测试: tests/test_{name}.py
  当前文件: src/{name}.py
```

### Level 2: Strict (严格模式)

```yaml
触发: 用户编辑源代码时

检查:
  - 测试文件是否存在
  - 测试是否处于失败状态 (RED)

违规处理:
  - 阻止操作
  - 要求修正后继续

输出示例:
  🚫 TDD 严格模式拦截
  必须先创建测试文件

  当前操作: 编辑 src/auth.py
  要求: tests/test_auth.py 中必须有失败的测试

  [创建测试] [取消]
```

### Level 3: Superpowers (完全模式)

```yaml
触发: 用户编辑源代码时

检查:
  - 测试文件存在
  - 测试处于失败状态
  - 无金装甲测试 (assert True, 跳过测试)
  - GREEN 阶段代码增量限制

违规处理:
  - 不可绕过
  - 详细违规说明
  - 强制 TDD 完整循环

额外功能:
  - 状态持久化
  - 阶段转换验证
```

---

## 安全代码 RED/GREEN commit 强制分离 (Aria #32)

> **命名**: 本特性即 #32 提议的 `level_3_strict`, 但为避开上面 strictness 第三档
> **"Level 3: Superpowers"** 的命名歧义, config key 用 `security_commit_separation`。
> 「安全代码」= credential / auth / acl / secret handling 等最需可证 test-first 的类别。

**问题**: strict/superpowers 检查"测试存在 + RED 状态", 但不强制 **commit 粒度**
RED/GREEN 分离。把 RED test + GREEN impl 打包进单 commit (Aether #42 `f105646`:
+349 test +108 impl 同 commit) → 测试质量好但审计员**无法从 git history 验证 test-first**。

**激活条件**: `strictness ∈ {strict, superpowers}` **且** `security_commit_separation.enabled=true`。

```yaml
检测触发 (ANY 满足 → 安全代码 commit 分离激活):
  - 路径匹配 security_commit_separation.path_patterns
    (默认 check*/auth*/acl*/secret*/credential* × go/py/ts — 前缀式 glob,
     有意宽松; 项目可收窄。schema path_patterns 为权威, 下方 hook 正则为示意)
  - commit message 含 commit_msg_keywords (security/auth/credential/secret/token)
  - Spec frontmatter level:3 (trigger_on_spec_level_3=true)
  注: #32 原列第 4 触发"安全相关 skill (doctor/acl/vault/variables)"未单列 config
      字段 — 由 path/keyword 在实践中覆盖 (这些 skill 的代码即落在 auth*/acl*/secret* 路径)。

commit 分离规则 (检测激活后, 含 test+prod 的单 commit 违规):
  RED commit:      message: test(<scope>): [RED] ...
                   变更仅: *_test.* / test|tests|fixtures 目录
                   (prod code 不变 — 证明测试先失败)
  GREEN commit:    message: feat(<scope>): [GREEN] ...
                   变更含: prod code + 通过的测试 (在该 commit 即过, 非仅 HEAD)
  REFACTOR commit: (可选) refactor(<scope>): [REFACTOR] ... 测试仍过, 无新测试场景

升级路径 (按 strictness; 本特性仅 enabled=true 且 strict/superpowers 才激活,
故无 advisory 行 —— advisory strictness 下整特性不生效):
  strict:      block; 用 bypass_token (默认 [skip-tdd]) 显式绕过,
               需 PR description 写 justification (记录可审计)
  superpowers: 不可绕过; bypass_token 失效, 强制拆 RED/GREEN

workflow 摩擦提示: 启用后, 安全文件的 stage-and-commit-once 工作流 (Claude Code
常见) 须改两次 commit; GREEN commit 的测试须在该 commit 即通过。blast radius 受
enabled=false + strict/superpowers + 安全路径匹配 三重门控, 仍 opt-in。
```

**可选 commit-msg hook 参考实现** (项目侧 opt-in 部署; **不**接入 Aria 自身
`hooks.json` —— Aria 是方法论项目无安全代码。本 hook 实现 **strict 档语义**,
正则为示意, schema `path_patterns` 为权威):

```bash
#!/bin/bash
# .git/hooks/commit-msg (项目侧安装) — 安全代码 RED/GREEN 分离守卫
# $1 = 提交信息文件路径 (commit-msg hook 在 message 已写入后、commit 完成前运行,
#       故能读到本次 message — pre-commit 读不到, 会误取上一条 commit)
if grep -q '\[skip-tdd\]' "$1"; then exit 0; fi   # strict bypass (superpowers 下删除此行)
staged=$(git diff --cached --name-only)
# test 文件: 前缀式 test_*.{py,js,ts} + 后缀式 *_test.* + *.{test,spec}.* + 测试目录
test_re='(^|/)test_[^/]*\.(py|js|ts)$|_test\.(go|py|ts|js)$|\.(test|spec)\.(js|ts)$|(^|/)(test|tests|fixtures|__tests__)/'
test_files=$(echo "$staged" | grep -E "$test_re")
impl_files=$(echo "$staged" | grep -vE "$test_re"'|\.(md|ya?ml|json)$')
# 安全 impl 文件: 关键字须为路径段的完整前导词 (auth.go ✓ / authority.go ✗ / oauth.go ✗ / healthcheck.go ✗)
sec_re='(^|/)(check|auth|acl|secret|credential)([_.-][a-z0-9_-]*)?\.(go|py|ts)$'
if [[ -n "$test_files" && -n "$impl_files" ]]; then
  if echo "$impl_files" | grep -qE "$sec_re"; then
    echo 'ERROR: 安全代码变更 — 请拆成独立 RED (test) 与 GREEN (impl) commit。'
    echo '匹配文件:'; echo "$impl_files" | grep -E "$sec_re"
    echo '绕过 (strict): commit message 加 [skip-tdd] + PR 说明理由 (superpowers 下删除上方 bypass 行)。'
    exit 1
  fi
fi
```

---

## 跨语言测试状态检测

### Python

```bash
# 检测框架
if [ -f pytest.ini ] || grep -q "pytest" pyproject.toml; then
    framework="pytest"
    command="pytest tests/ --collect-only --quiet"
else
    framework="unittest"
    command="python -m unittest discover -s tests"
fi

# 运行检测
result=$(eval $command)

# 判断 RED 状态
# pytest: exit_code != 0 表示有测试
# unittest: 输出包含 "FAILED" 或 "ERROR"
```

### JavaScript/TypeScript

```bash
# 检测框架
if [ -f jest.config.js ] || grep -q '"test": "jest"' package.json; then
    framework="jest"
    command="npx jest --passWithNoTests --verbose"
elif [ -f mocha.opts ]; then
    framework="mocha"
    command="npx mocha --require ./test/setup.js"
fi

# 运行检测
result=$(eval $command)

# 判断 RED 状态
# 输出包含 "failing" 或 "FAIL" 或 exit_code != 0
```

### Dart

```bash
# 检测框架
if grep -q "flutter:" pubspec.yaml; then
    framework="flutter"
    command="flutter test --dry-run"
else
    framework="dart"
    command="dart test --dry-run"
fi

# 运行检测
result=$(eval $command)

# 判断 RED 状态
# 输出包含 "FAIL" 或 exit_code != 0
```

---

## 配置文件

### 项目配置 (.claude/tdd-config.json)

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "advisory",
  "skip_patterns": [
    "**/*.md",
    "**/*.json",
    "**/config/**"
  ],
  "test_patterns": {
    "python": ["test_*.py", "*_test.py"],
    "javascript": ["*.test.js", "*.spec.js"],
    "dart": ["*_test.dart"]
  },
  "green_phase_limits": {
    "enabled": false,
    "max_lines_after_pass": 50,
    "max_new_functions": 3
  },
  "golden_testing_detection": {
    "enabled": false,
    "patterns": [
      {"pattern": "assert True", "severity": "error"},
      {"pattern": "@skip", "severity": "warning"}
    ]
  }
}
```

### 严格度级别选择

| 场景 | 推荐级别 | 理由 |
|------|---------|------|
| 新项目团队适应期 | Advisory | 学习 TDD 流程 |
| 生产环境项目 | Strict | 确保测试先于代码 |
| 高质量要求项目 | Superpowers | 完整质量控制 |

---

## 金装甲测试检测 (Superpowers)

### 反模式检测

| 模式 | 描述 | 严重程度 |
|------|------|---------|
| `assert True` | 永远通过的断言 | error |
| `assert False` | 永远通过的断言 | error |
| `@skip` | 跳过的测试 | warning |
| 空测试 | 没有断言的测试 | error |

### 多语言检测规则

```
Python:     assert\s+(True|False)\b
JavaScript: expect\((true|false)\)\.to[Bb]e\((true|false)\)
Dart:       expect\((true|false)\,\s*(true|false)\)
```

---

## 执行流程

### 当用户编辑源代码时:

```yaml
1. 检查文件类型
   └─ 跳过: *.md, *.json, 配置文件

2. 查找对应测试文件
   └─ 根据文件名映射规则

3. 应用严格度检查
   │
   ├─ Advisory: 测试不存在 → 警告
   ├─ Strict:   测试不存在或已通过 → 拦截
   └─ Superpowers: 完整检查 → 拦截

4. 返回结果
   └─ Allow / Warn / Block
```

---

## 输出格式

### 警告 (Advisory)

```yaml
status: warning
message: |
  ⚠️ TDD 规则警告

  当前文件: src/services/auth.js
  期望测试: tests/services/auth.test.js

  建议先编写失败测试 (RED 阶段)
```

### 拦截 (Strict/Superpowers)

```yaml
status: blocked
message: |
  🚫 TDD 严格模式拦截

  当前操作: 编辑 src/services/auth.js
  要求: 必须先存在失败测试

  [查看测试] [取消]
```

---

## Hook 集成

tdd-enforcer 通过 PreToolUse Hook 在 Write/Edit 操作前进行检查。

### Hook 配置

```json
{
  "name": "tdd-enforcer",
  "events": ["PreToolUse"],
  "handler": "tdd-enforcer"
}
```

### 执行时机

- 用户使用 Write 工具
- 用户使用 Edit 工具
- 检查目标文件是源代码

---

## 检查清单

### 使用前
- [ ] 确认项目需要 TDD 强制执行
- [ ] 配置 `tdd-config.json`
- [ ] 选择合适的严格度级别

### 使用后
- [ ] 测试先于代码编写
- [ ] RED-GREEN-REFACTOR 循环完整
- [ ] 无金装甲测试模式

---

## 相关文档

- [references/strictness-levels.md](references/strictness-levels.md) - 严格度级别详解
- [references/red-state-detection.md](references/red-state-detection.md) - RED 状态检测说明
- [references/green-phase-check.md](references/green-phase-check.md) - GREEN 阶段检查
- [references/migration-guide.md](references/migration-guide.md) - v1.x → v2.0 迁移
- [EXAMPLES.md](EXAMPLES.md) - 使用示例

---

**设计原则**: 文档驱动，AI 读取理解并执行检查规则。

**最后更新**: 2026-06-19 (Aria #32: 安全代码 RED/GREEN commit 强制分离 security_commit_separation)
**Skill版本**: 2.1.0 (安全代码 commit 分离)
