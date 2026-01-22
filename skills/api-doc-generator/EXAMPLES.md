# API 文档生成器 - 实用示例

> 本文档提供了 api-doc-generator skill 的实际使用示例，展示如何为不同项目生成API文档。

---

## 📚 示例目录

- [示例1: 为FastAPI项目生成文档](#示例1-为fastapi项目生成文档)
- [示例2: 为Express.js项目生成文档](#示例2-为expressjs项目生成文档)
- [示例3: 更新现有API文档](#示例3-更新现有api文档)
- [示例4: 为Flutter Backend生成文档](#示例4-为flutter-backend生成文档)

---

## 示例1: 为FastAPI项目生成文档

### 场景
你有一个使用FastAPI开发的Todo App后端，需要生成OpenAPI文档和Markdown文档。

### 项目结构
```
backend/
├── app/
│   ├── main.py
│   ├── routes/
│   │   ├── auth.py
│   │   ├── users.py
│   │   └── todos.py
│   └── models/
│       ├── user.py
│       └── todo.py
└── requirements.txt
```

### 执行步骤

#### 步骤1: 发现API端点

使用Grep查找路由定义：
```bash
grep -r "@router\|@app\\.get\|@app\\.post" backend/app/routes/
```

**发现的端点**:
```python
# backend/app/routes/auth.py
@router.post("/auth/login")
@router.post("/auth/logout")

# backend/app/routes/users.py
@router.get("/users")
@router.post("/users")
@router.get("/users/{user_id}")
@router.put("/users/{user_id}")
@router.delete("/users/{user_id}")

# backend/app/routes/todos.py
@router.get("/todos")
@router.post("/todos")
@router.get("/todos/{todo_id}")
@router.put("/todos/{todo_id}")
@router.delete("/todos/{todo_id}")
```

#### 步骤2: 分析端点详情

读取 `backend/app/routes/auth.py`：
```python
@router.post("/auth/login", response_model=TokenResponse)
async def login(credentials: LoginRequest):
    """
    用户登录接口

    Args:
        credentials: 登录凭证（邮箱和密码）

    Returns:
        TokenResponse: JWT token和用户信息
    """
    # ... implementation
```

**提取信息**:
- HTTP方法: POST
- 路径: `/auth/login`
- 请求体: `LoginRequest` (email, password)
- 响应: `TokenResponse` (token, user)
- 描述: 用户登录接口

#### 步骤3: 生成OpenAPI文档

创建 `backend/docs/openapi.yaml`，基于 OPENAPI_TEMPLATE.yaml：

```yaml
openapi: 3.0.0
info:
  title: Todo App API
  version: 1.0.0
  description: |
    Todo App RESTful API

    ## 认证
    使用JWT Bearer Token认证

servers:
  - url: http://localhost:8000/api/v1
    description: 本地开发
  - url: https://api.todoapp.com/v1
    description: 生产环境

paths:
  /auth/login:
    post:
      summary: 用户登录
      tags: [auth]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [email, password]
              properties:
                email:
                  type: string
                  format: email
                password:
                  type: string
                  minLength: 8
      responses:
        '200':
          description: 登录成功
          content:
            application/json:
              schema:
                type: object
                properties:
                  token:
                    type: string
                  user:
                    $ref: '#/components/schemas/User'
  # ... 其他端点
```

#### 步骤4: 生成Markdown文档

创建 `backend/docs/API.md`：

```markdown
# Todo App API 文档

## 快速开始

### 登录
\```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123"
  }'
\```

响应:
\```json
{
  "token": "eyJ...",
  "user": {
    "id": "123",
    "email": "user@example.com"
  }
}
\```

## API端点

### POST /auth/login
用户登录

**请求体**:
- `email` (string, required): 用户邮箱
- `password` (string, required): 密码（最少8位）

**响应**: 200 OK
...
```

### 执行结果

**生成的文件**:
- ✅ `backend/docs/openapi.yaml` (完整的OpenAPI 3.0规范)
- ✅ `backend/docs/API.md` (可读的Markdown文档)

**验证**:
```bash
npx @apidevtools/swagger-cli validate backend/docs/openapi.yaml
# ✅ Validation passed
```

**在线预览**:
访问 Swagger Editor 导入 openapi.yaml 查看交互式文档

---

## 示例2: 为Express.js项目生成文档

### 场景
Node.js + Express.js 项目，需要为REST API生成文档。

### 项目结构
```
backend/
├── src/
│   ├── index.js
│   ├── routes/
│   │   ├── auth.js
│   │   └── tasks.js
│   └── controllers/
└── package.json
```

### 执行步骤

#### 步骤1: 发现路由

```bash
grep -r "router\\.get\|router\\.post\|app\\.get\|app\\.post" backend/src/routes/
```

**发现的端点**:
```javascript
// backend/src/routes/auth.js
router.post('/auth/login', authController.login);
router.post('/auth/register', authController.register);

// backend/src/routes/tasks.js
router.get('/tasks', tasksController.getAll);
router.post('/tasks', tasksController.create);
router.get('/tasks/:id', tasksController.getOne);
router.put('/tasks/:id', tasksController.update);
router.delete('/tasks/:id', tasksController.delete);
```

#### 步骤2: 分析Controller

读取 `backend/src/controllers/authController.js`：

```javascript
/**
 * @route POST /api/auth/login
 * @desc 用户登录
 * @access Public
 */
exports.login = async (req, res) => {
  // 接收: { email, password }
  // 返回: { token, user }
  // ...
};
```

#### 步骤3: 生成OpenAPI

基于提取的信息创建 `docs/openapi.yaml`

#### 步骤4: 生成Markdown

创建 `docs/API.md` 包含所有端点说明

### 特殊处理

**Express路由参数**:
- Express: `/:id` → OpenAPI: `/{id}`
- Express: `/users/:userId/tasks/:taskId` → OpenAPI: `/users/{userId}/tasks/{taskId}`

---

## 示例3: 更新现有API文档

### 场景
API已有文档，但添加了新端点需要更新。

### 新增端点
```python
# backend/app/routes/todos.py
@router.patch("/todos/{todo_id}/complete")
async def mark_complete(todo_id: str):
    """标记待办事项为已完成"""
    # ...
```

### 更新步骤

#### 步骤1: 读取现有文档

```bash
read backend/docs/openapi.yaml
```

#### 步骤2: 添加新端点

在 `paths` 部分添加：

```yaml
/todos/{todo_id}/complete:
  patch:
    summary: 标记待办事项为已完成
    tags: [todos]
    security:
      - bearerAuth: []
    parameters:
      - name: todo_id
        in: path
        required: true
        schema:
          type: string
    responses:
      '200':
        description: 更新成功
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Todo'
      '404':
        $ref: '#/components/responses/NotFound'
```

#### 步骤3: 更新Markdown文档

在 API.md 添加新端点说明：

```markdown
### PATCH /todos/{id}/complete
标记待办事项为已完成

**路径参数**:
- `id` (string): 待办事项ID

**响应**: 200 OK
\```json
{
  "id": "123",
  "title": "Buy groceries",
  "status": "completed"
}
\```
```

#### 步骤4: 验证更新

```bash
npx @apidevtools/swagger-cli validate backend/docs/openapi.yaml
```

---

## 示例4: 为Flutter Backend生成文档

### 场景
使用Dart Shelf框架的Flutter后端项目。

### 项目结构
```
backend/
├── bin/
│   └── server.dart
├── lib/
│   ├── routes/
│   │   ├── auth_routes.dart
│   │   └── task_routes.dart
│   └── handlers/
└── pubspec.yaml
```

### 代码示例

```dart
// lib/routes/auth_routes.dart
import 'package:shelf/shelf.dart';
import 'package:shelf_router/shelf_router.dart';

Router authRoutes() {
  final router = Router();

  // POST /auth/login
  router.post('/auth/login', loginHandler);

  // POST /auth/register
  router.post('/auth/register', registerHandler);

  return router;
}

/// 用户登录
///
/// Request: { "email": "...", "password": "..." }
/// Response: { "token": "...", "user": {...} }
Response loginHandler(Request request) async {
  // ...
}
```

### 生成文档

#### 步骤1: 扫描路由

```bash
grep -r "router\\.get\|router\\.post" backend/lib/routes/
```

#### 步骤2: 分析Handler

读取每个handler的注释和代码，提取请求/响应格式

#### 步骤3: 生成OpenAPI

创建 `backend/docs/openapi.yaml`，注意 Dart 特定的类型映射：

```yaml
# Dart String → OpenAPI string
# Dart int → OpenAPI integer
# Dart double → OpenAPI number
# Dart bool → OpenAPI boolean
# Dart Map<String, dynamic> → OpenAPI object
# Dart List<T> → OpenAPI array
```

---

## 💡 技巧和最佳实践

### 1. 处理认证

大多数API需要认证，在OpenAPI中定义一次，所有端点引用：

```yaml
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT

paths:
  /protected-endpoint:
    get:
      security:
        - bearerAuth: []
```

### 2. 复用Schema

定义通用schema，在多处引用：

```yaml
components:
  schemas:
    PaginatedResponse:
      type: object
      properties:
        items:
          type: array
        total:
          type: integer
        page:
          type: integer

# 使用:
responses:
  '200':
    content:
      application/json:
        schema:
          allOf:
            - $ref: '#/components/schemas/PaginatedResponse'
            - properties:
                items:
                  type: array
                  items:
                    $ref: '#/components/schemas/User'
```

### 3. 处理错误

定义通用错误响应：

```yaml
components:
  responses:
    NotFound:
      description: 资源不存在
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ErrorResponse'

# 使用:
paths:
  /users/{id}:
    get:
      responses:
        '404':
          $ref: '#/components/responses/NotFound'
```

### 4. 版本管理

在servers中定义版本：

```yaml
servers:
  - url: https://api.example.com/v1
    description: Version 1
  - url: https://api.example.com/v2
    description: Version 2 (latest)
```

---

## 🔧 工具链集成

### 自动化文档生成

创建脚本 `scripts/generate-api-docs.sh`:

```bash
#!/bin/bash

# 1. 调用 api-doc-generator skill
echo "Generating API documentation..."

# 2. 验证生成的OpenAPI规范
echo "Validating OpenAPI spec..."
npx @apidevtools/swagger-cli validate docs/openapi.yaml

# 3. 生成客户端SDK
echo "Generating client SDKs..."
npx @openapitools/openapi-generator-cli generate \
  -i docs/openapi.yaml \
  -g typescript-axios \
  -o sdk/typescript

# 4. 启动本地文档服务器
echo "Starting documentation server..."
npx redoc-cli serve docs/openapi.yaml
```

### CI/CD集成

在 `.github/workflows/api-docs.yml`:

```yaml
name: API Documentation

on:
  pull_request:
    paths:
      - 'backend/app/routes/**'
      - 'docs/openapi.yaml'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Validate OpenAPI Spec
        run: npx @apidevtools/swagger-cli validate docs/openapi.yaml

      - name: Check for outdated docs
        run: |
          # 检查是否有新端点未文档化
          # 自定义检查脚本
```

---

**更多示例和场景，请参考 [SKILL.md](./SKILL.md)**
