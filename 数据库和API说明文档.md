# FengWen数据库模块和API模块文档说明

**版本**: 1.0.0  
**日期**: 2025年10月1日  
**项目**: FengWenServer - fengwen系统后端

---

## 目录

1. [项目概述](#项目概述)
2. [数据库结构文档](#数据库结构文档)
3. [API接口文档](#api接口文档)
4. [环境配置说明](#环境配置说明)
5. [部署说明](#部署说明)

---

## 项目概述

### 系统简介
本系统基于 `FastAPI` 框架开发，提供用户信息提交、八字测算、支付集成（Shopify）、邮件通知等功能。

### 技术栈
- **后端框架**: FastAPI
- **数据库**: PostgreSQL / SQLite (可配置)
- **ORM**: SQLAlchemy
- **缓存**: Redis (FastAPI Cache)
- **支付集成**: Shopify
- **邮件服务**: MJML + 自定义邮件服务
- **数据验证**: Pydantic

### 核心功能模块
1. 用户信息管理与八字测算
2. 邮箱验证服务
3. Shopify 支付集成与 Webhook 处理
4. 管理后台（产品管理、翻译管理）
5. 缓存管理
6. 邮件模板渲染与发送

---

## 数据库结构文档

### 1. astrology_records (八字测算记录表)

存储用户提交的个人信息和八字测算结果。

**表名**: `astrology_records`

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | Integer | PRIMARY KEY, INDEX | 记录唯一标识符 |
| email | String(255) | NOT NULL, INDEX | 用户邮箱地址 |
| name | String(255) | NOT NULL | 用户姓名 |
| birth_date | DateTime | NOT NULL | 出生日期 |
| birth_time | String(10) | NOT NULL | 出生时间 (HH:MM 格式) |
| gender | String(10) | NOT NULL | 性别 (Male/Female) |
| lunar_date | String(50) | NULL | 农历日期 |
| full_result_zh | Text | NULL | 完整测算结果（中文版本，JSON格式） |
| full_result_en | Text | NULL | 完整测算结果（英文版本，JSON格式） |
| is_purchased | Boolean | NOT NULL, DEFAULT FALSE | 支付状态标识 |
| shopify_order_id | String(255) | NULL | Shopify订单ID |
| created_at | DateTime | NOT NULL, DEFAULT NOW | 记录创建时间（UTC） |

**索引**:
- `idx_email_created`: 复合索引 (email, created_at) - 优化按邮箱和时间查询
- `idx_purchased_created`: 复合索引 (is_purchased, created_at) - 优化按支付状态和时间查询

**说明**:
- `full_result_zh` 和 `full_result_en` 存储完整的测算结果，包含八字、六道轮回、正缘画像等信息
- `is_purchased` 为 TRUE 时表示用户已完成支付，可发送完整报告邮件
- `shopify_order_id` 用于防止重复处理同一订单的 webhook

---

### 2. products (产品信息表)

存储前端展示的产品卡片信息，系统固定维护3个产品。

**表名**: `products`

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | Integer | PRIMARY KEY, INDEX | 产品唯一标识符 |
| name | String(255) | NOT NULL, INDEX | 产品名称 |
| image_url | String(500) | NULL | 产品图片URL |
| redirect_url | String(500) | NULL | 点击产品后的跳转URL |
| created_at | DateTime | NOT NULL, DEFAULT NOW | 创建时间（UTC） |
| updated_at | DateTime | NOT NULL, DEFAULT NOW | 更新时间（UTC，自动更新） |

**索引**:
- `idx_product_name`: 单列索引 (name) - 优化按产品名称查询

**业务规则**:
- 系统始终保持 3 个产品记录
- 删除产品时会自动创建占位产品
- 创建产品时最多只能有 3 个产品

---

### 3. translation_pairs (翻译对照表)

存储中英文翻译对照关系，用于测算结果的多语言展示。

**表名**: `translation_pairs`

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | Integer | PRIMARY KEY, INDEX | 翻译对唯一标识符 |
| chinese_text | Text | NOT NULL | 中文文本 |
| english_text | Text | NOT NULL | 英文文本 |
| created_at | DateTime | NOT NULL, DEFAULT NOW | 创建时间（UTC） |
| updated_at | DateTime | NOT NULL, DEFAULT NOW | 更新时间（UTC，自动更新） |

**说明**:
- 用于八字术语、命理概念的中英文对照
- 支持批量导入和导出功能

---

### 4. site_config (站点配置表)

存储系统级配置信息（键值对形式）。

**表名**: `site_config`

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | Integer | PRIMARY KEY, INDEX | 配置唯一标识符 |
| config_key | String(100) | UNIQUE, NOT NULL, INDEX | 配置键名 |
| config_value | Text | NOT NULL | 配置值 |
| updated_at | DateTime | NOT NULL, DEFAULT NOW | 更新时间（UTC，自动更新） |

**说明**:
- 存储系统级别的动态配置
- `config_key` 保证唯一性

---

### 数据库连接配置

系统支持 PostgreSQL 和 SQLite 两种数据库：

**PostgreSQL 配置（生产环境推荐）**:
```
DATABASE_URL=postgresql://用户名:密码@主机:端口/数据库名
```

或通过独立环境变量：
```
DB_TYPE=postgresql
DB_USER=astrology_user
DB_PASSWORD=your_secure_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=astrology_db
```

**SQLite 配置（开发环境）**:
```
DB_TYPE=sqlite
```

**连接池配置** (PostgreSQL):
- 连接池大小: 10
- 最大溢出: 20
- 连接超时: 30秒
- 连接回收时间: 1800秒
- 查询超时: 30秒

---

## API接口文档

所有API端点前缀为 `/api`

### 认证说明

管理员接口需要通过 Cookie 认证：
- Cookie 名称: `access_token`
- Token 类型: JWT
- 有效期: 可配置（默认24小时）
- 获取方式: 通过 `/admin/login` 登录后自动设置

---

## 公开API接口

### 1. 提交用户信息

**端点**: `POST /api/submit-info`

**描述**: 提交用户基本信息并创建测算记录，保留接口，实际没有使用。

**请求体** (JSON):
```json
{
  "name": "张三",
  "email": "zhangsan@example.com",
  "birth_date": "1990-05-15",
  "birth_time": "08:30",
  "gender": "Male"
}
```

**请求字段说明**:
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 用户姓名 |
| email | string | 是 | 邮箱地址（Email格式验证） |
| birth_date | string | 是 | 出生日期（YYYY-MM-DD格式） |
| birth_time | string | 是 | 出生时间（HH:MM格式） |
| gender | string | 是 | 性别（Male或Female） |

**响应示例**:
```json
{
  "record_id": 123,
  "lunar_date": "农历 1990年四月廿一",
  "preview_result": "Your personalized reading is being prepared...",
  "message": "Please verify your email to see complete results."
}
```

**状态码**:
- 200: 成功
- 500: 服务器错误

---

### 2. 发送验证码

**端点**: `POST /api/send-verification`

**描述**: 向指定邮箱发送验证码

**请求体** (JSON):
```json
{
  "email": "zhangsan@example.com"
}
```

**响应示例**:
```json
{
  "success": true,
  "error": "",
  "message": "Verification code sent successfully"
}
```

**错误响应**:
```json
{
  "success": false,
  "error": "INVALID_EMAIL",
  "message": "Invalid email address format"
}
```

**错误代码说明**:
| 错误代码 | HTTP状态码 | 说明 |
|----------|-----------|------|
| INVALID_EMAIL | 400 | 邮箱格式无效 |
| EMAIL_NOT_EXIST | 400 | 邮箱不存在 |
| PROVIDER_ERROR | 400 | 邮件服务商错误 |
| EMAIL_BLACKLISTED | 403 | 邮箱已被列入黑名单 |
| RATE_LIMIT | 429 | 请求过于频繁 |
| SEND_FAILED | 500 | 发送失败 |
| INTERNAL_ERROR | 500 | 内部服务器错误 |

**状态码**:
- 200: 成功
- 400: 邮箱格式错误或不存在
- 403: 邮箱被禁用
- 429: 请求频率过高
- 500: 服务器错误

---

### 3. 验证邮箱

**端点**: `POST /api/verify-email-first`

**描述**: 验证用户输入的验证码是否正确

**请求体** (JSON):
```json
{
  "email": "zhangsan@example.com",
  "code": "123456"
}
```

**响应示例**:
```json
{
  "success": true,
  "error": "",
  "message": "Email verified successfully"
}
```

**错误响应**:
```json
{
  "success": false,
  "error": "INVALID_CODE",
  "message": "Invalid verification code"
}
```

**错误代码说明**:
| 错误代码 | HTTP状态码 | 说明 |
|----------|-----------|------|
| CODE_EXPIRED | 400 | 验证码已过期 |
| INVALID_CODE | 400 | 验证码无效 |
| INTERNAL_ERROR | 500 | 内部服务器错误 |

**状态码**:
- 200: 验证成功
- 400: 验证码错误或过期
- 500: 服务器错误

---

### 4. 八字测算

**端点**: `POST /api/astrology/calculate`

**描述**: 完整的八字测算计算（需先验证邮箱）

**请求体** (JSON):
```json
{
  "name": "张三",
  "email": "zhangsan@example.com",
  "birth_date": "1990-05-15",
  "birth_time": "08:30",
  "gender": "Male"
}
```

**前置条件**:
- 必须先通过 `/api/verify-email-first` 验证邮箱
- 验证码有效期内（通常5-10分钟）

**响应示例**:
```json
{
  "record_id": 123,
  "astrology_results": {
    "bazi": {
      "success": true,
      "data": {
        "base_info": { ... },
        "bazi_info": { ... },
        "chenggu": { ... },
        "wuxing": { ... },
        "xiyongshen": { ... }
      }
    },
    "liudao": {
      "success": true,
      "data": {
        "base_info": { ... },
        "liudao_info": { ... }
      }
    },
    "zhengyuan": {
      "success": true,
      "data": {
        "base_info": { ... },
        "zhengyuan_info": { ... }
      }
    }
  },
  "chinese": { ... }
}
```

**响应字段说明**:
- `record_id`: 测算记录ID
- `astrology_results.bazi`: 八字测算结果
- `astrology_results.liudao`: 六道轮回结果（部分遮罩）
- `astrology_results.zhengyuan`: 正缘画像结果（部分遮罩）
- `chinese`: 中文版本的测算结果

**数据遮罩说明**:
- 未支付用户的 `liudao` 和 `zhengyuan` 数据会被部分遮罩
- 支付后通过邮件发送完整结果

**缓存机制**:
- 相同用户信息的请求会返回缓存结果
- 缓存有效期: 可配置（默认1小时）

**状态码**:
- 200: 测算成功
- 400: 邮箱未验证或数据格式错误
- 500: 服务器错误

---

### 5. 创建支付链接

**端点**: `POST /api/astrology/create-payment-link`

**描述**: 为指定的测算记录创建 Shopify 支付链接

**请求体** (JSON):
```json
{
  "record_id": 123
}
```

**响应示例**:
```json
{
  "shopify_url": "https://your-store.myshopify.com/checkouts/..."
}
```

**状态码**:
- 200: 成功创建支付链接
- 404: 记录不存在
- 500: 创建链接失败

---

### 6. 获取产品列表

**端点**: `GET /api/products`

**描述**: 获取所有产品信息（最多3个）

**响应示例**:
```json
[
  {
    "id": 1,
    "name": "Product 1",
    "image_url": "https://example.com/image1.jpg",
    "redirect_url": "https://example.com/product1"
  },
  {
    "id": 2,
    "name": "Product 2",
    "image_url": "https://example.com/image2.jpg",
    "redirect_url": "#"
  },
  {
    "id": 3,
    "name": "Product 3",
    "image_url": "https://example.com/image3.jpg",
    "redirect_url": "#"
  }
]
```

**状态码**:
- 200: 成功

---

### 7. Shopify Webhook

**端点**: `POST /api/webhook/shopify`

**描述**: 接收 Shopify 支付完成通知，自动发送完整测算报告邮件

**请求头**:
- `X-Shopify-Hmac-Sha256`: Shopify 签名（生产环境必须）
- `X-Shopify-Topic`: Webhook 事件类型

**支持的事件类型**:
- `orders/paid`: 订单已支付
- `orders/fulfilled`: 订单已完成
- `orders/create`: 订单已创建

**请求体**: Shopify 订单数据（JSON格式）

**处理流程**:
1. 验证 Webhook 签名（生产环境）
2. 提取订单中的 `record_id` 或通过邮箱匹配记录
3. 更新记录的支付状态
4. 根据用户喜用神选择邮件模板
5. 渲染邮件内容并发送完整测算报告

**邮件模板选择规则**:
| 喜用神 | 模板文件 |
|--------|----------|
| 水 / Water | astrology_report_water.mjml.j2 |
| 火 / Fire | astrology_report_fire.mjml.j2 |
| 金 / Metal | astrology_report_metal.mjml.j2 |
| 木 / Wood | astrology_report_wood.mjml.j2 |
| 其他 | astrology_report_earth.mjml.j2 |

**响应示例**:
```json
{
  "status": "success"
}
```

**其他响应**:
```json
{
  "status": "already_processed_duplicate_webhook"
}
```

**状态码**:
- 200: 成功处理
- 400: 无效的JSON数据
- 401: 签名验证失败
- 500: 服务器错误

---

## 管理员API接口

所有管理员接口需要先登录，通过 Cookie 认证。

### 认证相关

#### 1. 管理员登录

**端点**: `POST /admin/login`

**描述**: 管理员登录并获取访问令牌

**请求体** (JSON):
```json
{
  "username": "admin",
  "password": "your_password"
}
```

**响应示例**:
```json
{
  "message": "Login successful"
}
```

**Cookie 设置**:
- `access_token`: JWT令牌（HttpOnly, SameSite=Lax）

**状态码**:
- 200: 登录成功
- 400: 用户名或密码为空
- 401: 认证失败
- 500: 服务器错误

---

### 产品管理

#### 2. 更新产品

**端点**: `PUT /api/admin/products/{product_id}`

**描述**: 更新指定产品的信息

**认证**: 需要管理员登录

**路径参数**:
- `product_id`: 产品ID

**请求体** (JSON):
```json
{
  "name": "New Product Name",
  "image_url": "https://example.com/new-image.jpg",
  "redirect_url": "https://example.com/new-url"
}
```

**请求字段说明** (所有字段可选):
| 字段 | 类型 | 说明 |
|------|------|------|
| name | string | 产品名称 |
| image_url | string | 产品图片URL |
| redirect_url | string | 跳转URL |

**响应示例**:
```json
{
  "id": 1,
  "name": "New Product Name",
  "image_url": "https://example.com/new-image.jpg",
  "redirect_url": "https://example.com/new-url",
  "message": "Product updated successfully"
}
```

**状态码**:
- 200: 更新成功
- 400: URL格式无效
- 401: 未认证
- 404: 产品不存在
- 500: 更新失败

---

#### 3. 删除产品

**端点**: `DELETE /api/admin/products/{product_id}`

**描述**: 删除指定产品（自动创建占位产品保持3个）

**认证**: 需要管理员登录

**路径参数**:
- `product_id`: 产品ID

**响应示例**:
```json
{
  "message": "Product deleted successfully"
}
```

**状态码**:
- 200: 删除成功
- 401: 未认证
- 404: 产品不存在
- 500: 删除失败

---

#### 4. 创建产品

**端点**: `POST /api/admin/products`

**描述**: 创建新产品（最多3个产品）

**认证**: 需要管理员登录

**请求体** (JSON):
```json
{
  "name": "New Product",
  "image_url": "https://example.com/image.jpg",
  "redirect_url": "https://example.com/product"
}
```

**响应示例**:
```json
{
  "id": 3,
  "name": "New Product",
  "image_url": "https://example.com/image.jpg",
  "redirect_url": "https://example.com/product"
}
```

**状态码**:
- 200: 创建成功
- 400: 已达到产品数量上限或URL格式无效
- 401: 未认证
- 500: 创建失败

---

### 翻译管理

#### 5. 获取所有翻译

**端点**: `GET /api/admin/translations`

**描述**: 获取所有翻译对照

**认证**: 需要管理员登录

**响应示例**:
```json
[
  {
    "id": 1,
    "chinese_text": "八字",
    "english_text": "Eight Characters",
    "created_at": "2025-01-01T00:00:00",
    "updated_at": "2025-01-01T00:00:00"
  }
]
```

**状态码**:
- 200: 成功
- 401: 未认证

---

#### 6. 添加翻译

**端点**: `POST /api/admin/translations`

**描述**: 添加新的翻译对照

**认证**: 需要管理员登录

**请求体** (JSON):
```json
{
  "chinese_text": "八字",
  "english_text": "Eight Characters"
}
```

**响应示例**:
```json
{
  "message": "Translation pair added"
}
```

**状态码**:
- 200: 添加成功
- 401: 未认证
- 500: 添加失败

---

#### 7. 更新翻译

**端点**: `PUT /api/admin/translations/{translation_id}`

**描述**: 更新指定翻译对照

**认证**: 需要管理员登录

**路径参数**:
- `translation_id`: 翻译ID

**请求体** (JSON):
```json
{
  "chinese_text": "八字命理",
  "english_text": "Eight Characters Astrology"
}
```

**响应示例**:
```json
{
  "message": "Translation updated"
}
```

**状态码**:
- 200: 更新成功
- 401: 未认证
- 404: 翻译不存在
- 500: 更新失败

---

#### 8. 删除翻译

**端点**: `DELETE /api/admin/translations/{translation_id}`

**描述**: 删除指定翻译对照

**认证**: 需要管理员登录

**路径参数**:
- `translation_id`: 翻译ID

**响应示例**:
```json
{
  "message": "Translation deleted successfully"
}
```

**状态码**:
- 200: 删除成功
- 401: 未认证
- 404: 翻译不存在
- 500: 删除失败

---

#### 9. 获取单个翻译

**端点**: `GET /api/admin/translations/{translation_id}`

**描述**: 获取指定翻译对照详情

**认证**: 需要管理员登录

**路径参数**:
- `translation_id`: 翻译ID

**响应示例**:
```json
{
  "id": 1,
  "chinese_text": "八字",
  "english_text": "Eight Characters"
}
```

**状态码**:
- 200: 成功
- 401: 未认证
- 404: 翻译不存在

---

#### 10. 批量添加翻译

**端点**: `POST /api/admin/translations/batch`

**描述**: 批量添加多个翻译对照

**认证**: 需要管理员登录

**请求体** (JSON):
```json
[
  {
    "chinese_text": "八字",
    "english_text": "Eight Characters"
  },
  {
    "chinese_text": "命理",
    "english_text": "Destiny"
  }
]
```

**响应示例**:
```json
{
  "message": "Successfully added 2 translations",
  "count": 2
}
```

**状态码**:
- 200: 添加成功
- 401: 未认证
- 500: 添加失败

---

#### 11. 导出翻译

**端点**: `GET /api/admin/export/translations`

**描述**: 导出所有翻译为JSON格式

**认证**: 需要管理员登录

**响应示例**:
```json
{
  "version": "1.0.0",
  "export_date": "2025-10-01T12:00:00",
  "total": 100,
  "translations": [
    {
      "id": 1,
      "chinese_text": "八字",
      "english_text": "Eight Characters"
    }
  ]
}
```

**状态码**:
- 200: 导出成功
- 401: 未认证
- 500: 导出失败

---

### 缓存管理

#### 12. 清空缓存

**端点**: `POST /api/admin/cache/invalidate`

**描述**: 清空指定用户或全部缓存

**认证**: 需要管理员登录

**请求体** (JSON):
```json
{
  "email": "zhangsan@example.com"
}
```

或清空全部缓存:
```json
{
  "clear_all": true
}
```

**响应示例**:
```json
{
  "message": "Cache cleared for zhangsan@example.com"
}
```

或:
```json
{
  "message": "All cache cleared"
}
```

**状态码**:
- 200: 清空成功
- 400: 参数错误
- 401: 未认证
- 500: 清空失败

---

#### 13. 获取缓存统计

**端点**: `GET /api/admin/cache/stats`

**描述**: 获取 Redis 缓存统计信息

**认证**: 需要管理员登录

**响应示例**:
```json
{
  "total_keys": 150,
  "astrology_cache_keys": 100,
  "hits": 5000,
  "misses": 500,
  "hit_rate": 90.91
}
```

**响应字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| total_keys | int | Redis中的总键数 |
| astrology_cache_keys | int | 八字测算缓存键数 |
| hits | int | 缓存命中次数 |
| misses | int | 缓存未命中次数 |
| hit_rate | float | 缓存命中率（百分比） |

**状态码**:
- 200: 成功
- 401: 未认证
- 500: 获取失败

---

### 统计信息

#### 14. 获取管理后台统计

**端点**: `GET /api/admin/stats`

**描述**: 获取管理后台各模块统计信息

**认证**: 需要管理员登录

**响应示例**:
```json
{
  "products": {
    "total": 3,
    "required": 3,
    "complete": true
  },
  "translations": {
    "total": 150
  },
  "last_update": {
    "products": 3,
    "translations": 150
  }
}
```

**状态码**:
- 200: 成功
- 401: 未认证
- 500: 获取失败

---

#### 15. 上传图片

**端点**: `POST /api/admin/upload/image`

**描述**: 上传产品图片

**认证**: 需要管理员登录

**请求类型**: `multipart/form-data`

**请求参数**:
- `file`: 图片文件（File）

**支持的图片格式**:
- image/jpeg
- image/png
- image/gif
- image/webp

**文件大小限制**: 5MB

**响应示例**:
```json
{
  "url": "/static/uploads/550e8400-e29b-41d4-a716-446655440000.jpg",
  "filename": "550e8400-e29b-41d4-a716-446655440000.jpg",
  "size": 102400
}
```

**状态码**:
- 200: 上传成功
- 400: 文件类型不支持或文件过大
- 401: 未认证
- 500: 上传失败

---

## 测试API接口

仅在非生产环境（`ENVIRONMENT != "production"`）可用

#### 16. 测试发送邮件

**端点**: `POST /api/test/send-email/{record_id}`

**描述**: 测试向指定记录的邮箱发送完整测算报告邮件

**环境限制**: 仅非生产环境可用

**路径参数**:
- `record_id`: 测算记录ID

**响应示例**:
```json
{
  "status": "success",
  "message": "Test email sent to zhangsan@example.com",
  "record_id": "123",
  "email": "zhangsan@example.com",
  "template_used": "astrology_report_water.mjml.j2",
  "advantage_element": "水"
}
```

**状态码**:
- 200: 发送成功
- 400: 记录数据错误
- 403: 生产环境禁止访问
- 404: 记录不存在
- 500: 发送失败

---

#### 17. 列出测试记录

**端点**: `GET /api/test/list-records`

**描述**: 列出可用于测试的测算记录

**环境限制**: 仅非生产环境可用

**查询参数**:
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| skip | int | 0 | 跳过记录数（分页） |
| limit | int | 10 | 返回记录数（分页） |
| only_unpurchased | bool | false | 仅返回未支付记录 |

**响应示例**:
```json
{
  "total": 5,
  "skip": 0,
  "limit": 10,
  "records": [
    {
      "id": 123,
      "email": "zhangsan@example.com",
      "is_purchased": false,
      "shopify_order_id": null,
      "created_at": "2025-10-01T12:00:00",
      "has_full_result": true
    }
  ]
}
```

**状态码**:
- 200: 成功
- 403: 生产环境禁止访问
- 500: 查询失败

---

## 环境配置说明

### 必需环境变量

**数据库配置**:
```bash
DATABASE_URL=postgresql://user:password@host:port/database
# 或者使用独立变量
DB_TYPE=postgresql
DB_USER=astrology_user
DB_PASSWORD=your_secure_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=astrology_db
```

**Redis缓存配置**:
```bash
REDIS_URL=redis://localhost:6379/0
```

**管理员认证**:
```bash
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=<bcrypt-hashed-password>
JWT_SECRET_KEY=your-secret-key-here
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

**Shopify配置**:
```bash
SHOPIFY_DOMAIN=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=your-access-token
SHOPIFY_WEBHOOK_SECRET=your-webhook-secret
SHOPIFY_PRODUCT_ID=your-product-id
```

**邮件服务配置**:
```bash
EMAIL_API_URL=your-email-service-url
EMAIL_API_KEY=your-email-api-key
EMAIL_FROM_ADDRESS=noreply@example.com
EMAIL_FROM_NAME=Astrology Service
```

**外部API配置**:
```bash
ASTROLOGY_API_URL=https://api.example.com
ASTROLOGY_API_KEY=your-api-key
```

**环境标识**:
```bash
ENVIRONMENT=production
# 可选值: development, staging, production
```

**其他配置**:
```bash
DB_ECHO=false  # 是否打印SQL日志
CACHE_TTL=3600  # 缓存过期时间（秒）
```