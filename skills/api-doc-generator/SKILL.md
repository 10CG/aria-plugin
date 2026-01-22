---
name: api-doc-generator
description: |
  从代码生成API文档和OpenAPI规范，支持多种后端框架（FastAPI、Express.js、Django等）。

  使用场景：为REST API项目生成OpenAPI 3.0规范、创建或更新API接口文档、从代码自动提取API信息。
---

# API 文档生成器

> **版本**: 2.0.0 | **最新更新**: 2025-12-10

## 🚀 快速导航

### 我应该使用这个 skill 吗？

**✅ 使用场景**:
- 为REST API项目生成OpenAPI 3.0规范
- 创建或更新API接口文档
- 从代码自动提取API信息
- 生成Swagger UI可用的文档
- 同步代码与文档

**❌ 不使用场景**:
- 仅需要查看现有文档 → 直接阅读
- GraphQL API → 使用GraphQL专用工具
- 非HTTP API（如gRPC）→ 使用对应工具

### 快速开始 (3步)

```yaml
步骤1: 扫描代码库
  → 使用 Grep 查找路由定义
  → 使用 Glob 定位API文件

步骤2: 分析API端点
  → 提取HTTP方法、路径、参数、schema

步骤3: 生成文档
  → 使用 OPENAPI_TEMPLATE.yaml 生成OpenAPI规范
  → 使用 MARKDOWN_TEMPLATE.md 生成可读文档
```

---

## 📋 支持的框架

| 语言/平台 | 框架 | 路由标识 |
|----------|------|---------|
| **Python** | FastAPI, Flask, Django | `@app.route`, `@router.get`, `path()` |
| **Node.js** | Express, NestJS | `app.get()`, `@Get()`, `router.post()` |
| **Dart/Flutter** | Shelf, Serverpod | `Router()`, `@Route()` |
| **其他** | 任何RESTful API | 标准HTTP方法定义 |

---

## 🔄 执行流程

### 步骤1: 发现API端点

使用 **Grep** 工具搜索路由定义：

```bash
# 搜索路由装饰器和定义
grep -r "@route\|@app\|@api\|@Get\|@Post\|@Put\|@Delete" --include="*.py" --include="*.js" --include="*.dart"
```

使用 **Glob** 工具定位API文件：

```bash
# 查找常见的API文件
glob "**/*api*.py"
glob "**/*routes*.py"
glob "**/*controller*.dart"
```

### 步骤2: 分析API代码

对每个发现的端点，使用 **Read** 工具读取代码并提取：

1. **HTTP方法**: GET, POST, PUT, DELETE, PATCH
2. **路径**: `/api/users/{id}`
3. **路径参数**: `{id}`, `{userId}`
4. **查询参数**: `?page=1&limit=10`
5. **请求体**: JSON schema
6. **响应**: 状态码和响应体schema
7. **认证要求**: Bearer token, API key等
8. **描述和示例**

### 步骤3: 生成OpenAPI规范

使用 **Write** 工具创建 `openapi.yaml`，基于 **OPENAPI_TEMPLATE.yaml** 模板：

**模板位置**: `.claude/skills/api-doc-generator/OPENAPI_TEMPLATE.yaml`

**关键替换**:
- `${PROJECT_NAME}` → 项目名称
- `${PROJECT_DESCRIPTION}` → 项目描述
- 添加实际的 paths, schemas, parameters

### 步骤4: 生成Markdown文档

使用 **Write** 工具创建 `API.md`，基于 **MARKDOWN_TEMPLATE.md** 模板：

**模板位置**: `.claude/skills/api-doc-generator/MARKDOWN_TEMPLATE.md`

**包含内容**:
- 快速开始指南
- 所有端点的详细说明
- 请求/响应示例
- 错误处理说明
- 数据模型定义

---

## 📚 模板使用

### OpenAPI 模板

**文件**: `OPENAPI_TEMPLATE.yaml`

**特点**:
- 完整的OpenAPI 3.0结构
- 包含认证、用户、待办事项示例端点
- 标准化的响应格式
- 通用的错误处理schema

**使用方法**:
1. 复制模板内容
2. 替换 `${PROJECT_NAME}` 等占位符
3. 根据实际API调整端点和schema
4. 删除不需要的示例端点

### Markdown 模板

**文件**: `MARKDOWN_TEMPLATE.md`

**特点**:
- 清晰的文档结构
- curl示例命令
- TypeScript接口定义
- 错误码表格

**使用方法**:
1. 复制模板结构
2. 填入实际的端点和参数
3. 更新示例数据
4. 添加项目特定说明

---

## ✅ 最佳实践

### 1. 一致的响应格式

所有API响应使用统一格式：

```json
{
  "success": true/false,
  "data": { ... },      // 成功时
  "error": { ... },     // 失败时
  "message": "..."      // 可选的消息
}
```

### 2. 合理的HTTP状态码

- `200 OK`: 成功
- `201 Created`: 创建成功
- `204 No Content`: 删除成功
- `400 Bad Request`: 请求格式错误
- `401 Unauthorized`: 未认证
- `403 Forbidden`: 无权限
- `404 Not Found`: 资源不存在
- `422 Unprocessable Entity`: 验证失败
- `500 Internal Server Error`: 服务器错误

### 3. RESTful设计

```
GET    /users          # 获取列表
POST   /users          # 创建
GET    /users/{id}     # 获取单个
PUT    /users/{id}     # 更新
DELETE /users/{id}     # 删除
```

### 4. 版本控制

在URL中包含版本号：
```
https://api.example.com/v1/users
https://api.example.com/v2/users
```

### 5. 分页参数

```
GET /users?page=1&limit=20
```

响应包含分页信息：
```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "limit": 20,
  "totalPages": 5
}
```

---

## 🔧 工具和验证

### 在线编辑器

生成的OpenAPI文档可以在以下工具中使用：

- [Swagger Editor](https://editor.swagger.io/) - 在线编辑和验证
- [Redoc](https://redocly.github.io/redoc/) - 生成美观的文档
- [Stoplight](https://stoplight.io/) - 协作式API设计

### 验证规范

```bash
# 使用swagger-cli验证
npx @apidevtools/swagger-cli validate openapi.yaml

# 使用spectral验证（更严格）
npx @stoplight/spectral-cli lint openapi.yaml
```

### 生成客户端SDK

```bash
# 生成TypeScript客户端
npx @openapitools/openapi-generator-cli generate \
  -i openapi.yaml \
  -g typescript-axios \
  -o ./sdk/typescript

# 生成Dart客户端
npx @openapitools/openapi-generator-cli generate \
  -i openapi.yaml \
  -g dart \
  -o ./sdk/dart
```

### Mock Server

```bash
# 使用prism创建mock服务器
npx @stoplight/prism-cli mock openapi.yaml
```

---

## 📤 输出文件

生成的文档包括：

1. **openapi.yaml** - OpenAPI 3.0规范文件
2. **API.md** - Markdown格式的API文档
3. **README.md** - 使用说明和快速开始（可选）
4. **examples/** - 请求和响应示例（可选）

---

## 💡 维护建议

### 保持文档同步

- **代码变更时及时更新文档** - 在同一PR中更新代码和文档
- **使用CI/CD验证** - 在CI中自动验证OpenAPI规范
- **版本控制** - 文档和代码一起提交到Git
- **代码审查** - 文档变更也需要review

### 文档质量

1. 为每个端点提供清晰的描述
2. 包含完整的请求和响应schema
3. 说明认证和权限要求
4. 提供实际的请求示例
5. 使用有意义的示例数据

### 命名规范

- **一致的命名**: 统一使用 camelCase 或 snake_case
- **有意义的名称**: `userId` 而非 `id`
- **清晰的操作**: `createUser` 而非 `add`

---

## 🔍 常见问题

**Q: 如何处理文件上传？**
A: 在OpenAPI中使用 `multipart/form-data` content type:
```yaml
requestBody:
  content:
    multipart/form-data:
      schema:
        type: object
        properties:
          file:
            type: string
            format: binary
```

**Q: 如何定义可选参数？**
A: 使用 `required: false` 和 `nullable: true`:
```yaml
parameters:
  - name: search
    in: query
    required: false
    schema:
      type: string
      nullable: true
```

**Q: 如何处理数组响应？**
A: 使用 `type: array` 和 `items`:
```yaml
responses:
  '200':
    content:
      application/json:
        schema:
          type: array
          items:
            $ref: '#/components/schemas/User'
```

---

## 📖 参考资源

- **OPENAPI_TEMPLATE.yaml** - 完整的OpenAPI模板
- **MARKDOWN_TEMPLATE.md** - Markdown文档模板
- **EXAMPLES.md** - 实际使用示例
- **CHANGELOG.md** - 版本历史

### 外部链接

- [OpenAPI 3.0 规范](https://swagger.io/specification/)
- [OpenAPI Generator](https://openapi-generator.tech/)
- [API设计最佳实践](https://github.com/microsoft/api-guidelines)

---

*本Skill遵循OpenAPI 3.0规范和RESTful API设计最佳实践。*
