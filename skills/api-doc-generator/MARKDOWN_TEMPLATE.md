# API 文档模板

> 此文档是生成Markdown格式API文档的模板。使用时请替换占位符并根据实际API调整内容。

---

# API 文档

## 基础信息

- **Base URL**: `https://api.example.com/v1`
- **认证方式**: Bearer Token (JWT)
- **数据格式**: JSON
- **字符编码**: UTF-8

## 快速开始

### 1. 注册和登录

```bash
# 注册用户
curl -X POST https://api.example.com/v1/users \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123",
    "name": "张三"
  }'

# 登录获取token
curl -X POST https://api.example.com/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123"
  }'

# 响应示例
{
  "success": true,
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "user": {
      "id": "123",
      "email": "user@example.com",
      "name": "张三"
    }
  }
}
```

### 2. 使用token访问受保护端点

```bash
curl -X GET https://api.example.com/v1/todos \
  -H "Authorization: Bearer <your-token>"
```

## API端点

### 认证 Authentication

#### POST /auth/login
用户登录

**请求体**:
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**响应**: 200 OK
```json
{
  "success": true,
  "data": {
    "token": "eyJ...",
    "user": { ... }
  }
}
```

---

### 用户 Users

#### GET /users
获取用户列表（需要管理员权限）

**查询参数**:
- `page` (number, optional): 页码，默认1
- `limit` (number, optional): 每页数量，默认20
- `search` (string, optional): 搜索关键词

**响应**: 200 OK
```json
{
  "success": true,
  "data": {
    "items": [...],
    "total": 100,
    "page": 1,
    "limit": 20
  }
}
```

## 错误处理

所有错误响应遵循统一格式：

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述",
    "details": []
  }
}
```

### 常见错误码

| 状态码 | 错误码 | 说明 |
|--------|--------|------|
| 400 | BAD_REQUEST | 请求格式错误 |
| 401 | UNAUTHORIZED | 未授权 |
| 403 | FORBIDDEN | 禁止访问 |
| 404 | NOT_FOUND | 资源不存在 |
| 422 | VALIDATION_ERROR | 参数验证失败 |
| 500 | INTERNAL_ERROR | 服务器错误 |

## 数据模型

### User
```typescript
interface User {
  id: string;
  email: string;
  name: string;
  avatar?: string;
  role: 'user' | 'admin';
  createdAt: string;  // ISO 8601
  updatedAt: string;
}
```

### Todo
```typescript
interface Todo {
  id: string;
  title: string;
  description?: string;
  status: 'pending' | 'completed';
  priority: 'low' | 'medium' | 'high';
  dueDate?: string;  // ISO 8601
  userId: string;
  createdAt: string;
  updatedAt: string;
}
```
