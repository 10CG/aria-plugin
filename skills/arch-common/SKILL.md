---
name: arch-common
description: |
  架构文档 Skills 的共享配置，定义 L0/L1/L2 层级体系、命名规范和文档位置。

  此 Skill 不直接触发，由 arch-search 和 arch-update 引用。
---

# 架构文档共享配置

> **Version**: 1.1.0
> **Purpose**: 为 arch-search 和 arch-update 提供共享定义
> **Usage**: 被其他架构 Skills 引用，不直接触发
> **Methodology**: 基于 `@standards/core/architecture/` 通用方法论

---

## 方法论基础

本配置基于以下通用规范（可跨项目复用）：

| 规范 | 路径 | 说明 |
|------|------|------|
| 层级体系 | `@standards/core/architecture/layering-system.md` | L0/L1/L2 定义 |
| 文档模板 | `@standards/core/architecture/document-templates.md` | 标准模板格式 |
| 验证体系 | `@standards/core/architecture/validation-levels.md` | 三级验证规范 |
| 命名规范 | `@standards/core/architecture/naming-conventions.md` | 目录/文件/版本命名 |
| 生命周期 | `@standards/core/architecture/lifecycle-management.md` | 文档生命周期 |
| AI 指南 | `@standards/core/architecture/ai-integration-guide.md` | AI 集成规范 |

以下为本项目的具体配置和路径定义。

---

## 三层架构体系 (L0/L1/L2)

### 层级定义

| 层级 | 定义 | 文件数阈值 | 典型位置 | 文档命名 |
|------|------|-----------|---------|---------|
| **L0** | 端级总体架构 | 整个端 | 端根目录 | `ARCHITECTURE.md` |
| **L1** | 主要模块架构 | ≥10个文件 | 一级子目录 | `[模块]_ARCHITECTURE.md` |
| **L2** | 功能组件架构 | 5-10个文件 | 二级子目录 | `[组件]_ARCHITECTURE.md` |

### 层级判断流程

```
新架构文档需求
├─ 是否为端根目录？→ 是 → L0级别
└─ 否 → 文件数≥10？
    ├─ 是 → L1级别
    └─ 否 → 文件数≥5？
        ├─ 是 → L2级别
        └─ 否 → 归入父文档
```

### 创建阈值

- **≥10个文件** → L1级别，创建独立架构文档
- **5-10个文件** → L2级别，创建独立架构文档
- **<5个文件** → 归入父目录文档，不单独创建

---

## 命名规范

### 代码目录（大写+下划线）

```
backend/
├── BACKEND_ARCHITECTURE.md              ✅ L0端级架构
├── llm_provider/
│   └── LLM_PROVIDER_ARCHITECTURE.md     ✅ L1/L2模块架构
└── agents/
    └── AGENTS_ARCHITECTURE.md           ✅ L1/L2模块架构
```

### docs/目录（小写+连字符）

```
backend/docs/
├── architecture/
│   ├── llm-provider-architecture.md     ✅ 架构设计文档
│   └── agents-architecture.md           ✅ 架构设计文档
└── api/
    └── llm-provider-api.md              ✅ API文档
```

### 索引文档（固定命名）

```
backend/
├── ARCHITECTURE_DOCS_INDEX.md           ✅ 架构文档索引
└── ARCHITECTURE_DOCS_TREE.md            ✅ 文档树（自动生成）
```

---

## 模块架构入口

### 主要模块入口表

| 模块 | L0 架构文档 | UPM 文档 | 说明 |
|------|------------|----------|------|
| **Mobile** | `mobile/docs/ARCHITECTURE.md` | `mobile/docs/project-planning/unified-progress-management.md` | Flutter 应用 |
| **Backend** | `backend/docs/ARCHITECTURE.md` | `backend/project-planning/unified-progress-management.md` | FastAPI 服务 |
| **Shared** | `shared/README.md` | - | API 契约 |
| **Standards** | `standards/README.md` | - | 开发规范 |

### 架构文档搜索路径

```yaml
L0 文档 (优先搜索):
  - "{module}/ARCHITECTURE.md"
  - "{module}/docs/ARCHITECTURE.md"

L1 文档 (按需搜索):
  - "{module}/docs/architecture/*.md"
  - "{module}/*_ARCHITECTURE.md"

契约文档:
  - "shared/contracts/**/*.yaml"
  - "shared/schemas/**/*.json"

规范文档:
  - "standards/**/*.md"
```

---

## 文件类型判断

### 需要架构文档覆盖

**代码文件** ✅: `.py .js .ts .dart .java .go .kt .swift .c .cpp .rs`

### 不需要架构文档覆盖

**非代码文件** ❌: `.md .json .yaml .xml .css .png .jpg`

### 排除目录

```yaml
排除:
  - "*/node_modules/*"
  - "*/vendor/*"
  - "*/build/*"
  - "*/dist/*"
  - "*/.git/*"
  - "*/test/*" (测试代码可选)
```

---

## 版本和时间格式

### 版本号

```yaml
格式: X.Y.Z (语义化版本)
  X: 主版本（重大变更）
  Y: 次版本（功能添加）
  Z: 修订版本（Bug修复/文档更新）
```

### 时间格式

```yaml
格式: ISO 8601，精确到秒
示例: 2025-12-14T15:45:00+08:00
```

---

## 相关 Skills

| Skill | 用途 | 引用本配置 |
|-------|------|-----------|
| **arch-search** | 搜索架构文档，定位代码 | ✅ |
| **arch-update** | 创建/更新架构文档 | ✅ |

---

**最后更新**: 2025-12-28
**配置版本**: 1.2.0
