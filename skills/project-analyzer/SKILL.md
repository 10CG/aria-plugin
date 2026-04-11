---
name: project-analyzer
description: "Scan project directory to identify tech stack, frameworks, work patterns, and toolchain. Outputs structured project profile for agent-gap-analyzer. Use when onboarding a new project or auditing project characteristics."
---

# 项目分析器

扫描目标项目,识别技术栈、框架、工作模式和工具链,输出结构化项目画像。

## 使用场景

- 接入新项目时: "分析这个项目的技术栈"
- agent-gap-analyzer 的前置步骤

## 流程

1. 使用 Glob 定位清单文件:
   - package.json, tsconfig.json → Node.js/TypeScript
   - go.mod → Go
   - requirements.txt, pyproject.toml, setup.py → Python
   - pubspec.yaml → Flutter/Dart
   - Cargo.toml → Rust
   - pom.xml, build.gradle → Java
   - Makefile, CMakeLists.txt → C/C++

2. 使用 Read 读取清单文件内容:
   - package.json: dependencies + devDependencies (框架/ORM/测试库)
   - go.mod: require 列表
   - pyproject.toml: [project.dependencies]

3. 检测工作模式:
   - monorepo: lerna.json / pnpm-workspace.yaml / packages/ 目录
   - 微服务: 多个 Dockerfile / docker-compose.yml
   - 前后端分离: frontend/ + backend/ 或 client/ + server/

4. 检测工具链:
   - CI/CD: .github/workflows/, .gitlab-ci.yml, Jenkinsfile, .forgejo/workflows/
   - 测试: jest.config.*, pytest.ini, vitest.config.*
   - ORM: prisma/, alembic/, migrations/
   - 部署: Dockerfile, *.nomad.hcl, k8s/, terraform/

5. 输出 `.aria/project-profile.yaml`:

```yaml
schema_version: "1"
name: "<project-name>"
tech_stack:
  primary_language: "TypeScript"
  runtime: "Node.js 20"
  framework: "Express + Prisma"
  frontend: null
  mobile: null
packages: []  # monorepo 子包
patterns:
  architecture: "monolith"
  testing: "Jest"
  ci_cd: "GitHub Actions"
  orm: "Prisma"
  deployment: "Docker"
work_modes:
  - "API development"
  - "Database schema evolution"
detected_from:
  - { file: "package.json", fields: ["dependencies"] }
```

## 降级处理

无法识别技术栈时:
```yaml
tech_stack:
  primary_language: "unknown"
  note: "无法自动识别,请手工补充"
```

## 注意

- 只读操作,不修改项目文件
- 输出路径: `.aria/project-profile.yaml` (在项目根目录的 .aria/ 下)
