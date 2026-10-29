# Survey System

> 第二阶段已增加共享题目、不可变题目版本、派生题目、问卷题目快照、使用情况和同版本跨问卷统计；第一阶段问卷与填写接口保持兼容。

一个使用 **FastAPI + MongoDB** 实现的在线问卷系统课程项目。第二阶段在第一阶段问卷闭环上增加了可共享题目、不可变题目版本、派生题目、问卷题目快照、使用情况和同版本跨问卷统计。

## 基础信息

- 后端：Python 3.10、FastAPI、PyMongo。
- 数据库：MongoDB，不使用关系数据库。
- 前端：原生 HTML、CSS、JavaScript，由 FastAPI 直接托管。
- 测试：pytest、FastAPI TestClient 和内存数据库替身。
- 当前最终回归：`141 passed, 0 failed, 0 errors, 4 warnings in 7.48s`。
- 最终实验报告：[docs/final-project-report.md](docs/final-project-report.md)。

## 项目功能

- **账号与权限**：用户名唯一；密码使用 PBKDF2 哈希保存；通过 Bearer Token 访问受保护接口；问卷所有者只能管理自己的问卷。
- **问卷管理**：创建、查询、编辑、发布和关闭问卷；支持截止时间、唯一分享标识、匿名展示配置和重复提交配置。
- **版本管理**：发布版本不直接覆盖；修改已发布问卷会基于原定义创建新草稿版本，历史版本保留。
- **题目类型**：单选、多选、文本和数值题；选项题、文本长度和数值范围等约束在服务端校验。
- **条件跳转**：按题目顺序和规则优先级计算下一题；发布前校验问卷定义，最终提交时由服务端重新计算实际作答路径。
- **答卷与统计**：答卷保存至 MongoDB；支持单选/多选选项计数、文本答案查看、数值平均值，以及整体或单题统计。
- **浏览器演示页**：提供注册登录、问卷管理、分享答题和统计查看，不需要单独安装前端构建工具。
- **题目库**：登录用户可管理自己的题目版本、共享题目、派生他人共享题目，并把指定版本复制到问卷草稿。
- **跨问卷统计**：题目所有者可按精确题目版本聚合单选、多选、数字和文本题的脱敏统计。

### 匿名填写与访问边界

本项目中的“匿名填写”指填写者仍需登录，但问卷所有者不能通过统计接口查看填写者身份。系统内部保留填写者标识，用于身份认证和重复提交控制。已发布且开放的分享问卷定义可公开读取；答题导航与提交需要登录。

默认禁止同一账号对同一问卷重复提交。问卷设置 `allow_multiple_submissions=true` 后允许重复提交。关闭或超过截止时间的问卷不能继续读取分享内容、导航或提交。

## GitHub 仓库项目结构

```text
survey-system/
├─ app/
│  ├─ algorithms/             答案、问卷定义、跳转和提交路径算法
│  ├─ core/                   配置与认证安全工具
│  ├─ db/                     MongoDB 客户端和索引
│  ├─ api.py                  认证、问卷、填写和问卷统计接口
│  ├─ question_api.py         题目库、版本、复用和跨问卷统计接口
│  ├─ services.py             用户、问卷、答卷和统计业务逻辑
│  ├─ question_services.py    题目身份、不可变版本、共享和快照逻辑
│  ├─ dependencies.py         认证和数据库依赖
│  └─ main.py                 应用入口、静态前端和健康检查
├─ frontend/
│  ├─ index.html
│  ├─ styles.css
│  └─ app.js
├─ tests/
│  ├─ test_answer_validator.py
│  ├─ test_survey_validator.py
│  ├─ test_jump.py
│  ├─ test_submission_validation.py
│  ├─ test_api_business.py
│  └─ test_health.py
├─ docs/
│  ├─ final-project-report.md
│  ├─ phase1-final-report.md
│  ├─ system-design.md
│  ├─ database-design.md
│  ├─ api.md
│  ├─ jump-algorithm.md
│  ├─ business-test-report.md
│  └─ ai-usage-log.md
├─ .env.example
├─ .gitignore
├─ requirements.txt
└─ README.md
```

`.venv/`、`.venv-phase2/`、缓存、运行日志和本地 MongoDB 数据目录属于本机运行产物，不应上传到 GitHub。

主要接口及请求示例见 [API 文档](docs/api.md)；MongoDB 集合与索引说明见 [数据库设计](docs/database-design.md)；核心跳转规则见 [跳转算法说明](docs/jump-algorithm.md)。

## 环境要求

- Windows 开发环境
- Python 3.10.7
- MongoDB 已安装并运行
- Git

## 安装依赖

建议在项目根目录使用虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果需要重新创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 本地配置

复制 `.env.example` 为 `.env`，按需修改 MongoDB 连接信息：

```powershell
Copy-Item .env.example .env
```

默认配置：

```text
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DATABASE=survey_system
AUTH_SECRET=development-only-change-me
```

## 启动服务

```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

服务默认地址：

```text
http://127.0.0.1:8000
```

## 接口访问

启动后可访问 Swagger API 文档：

```text
http://127.0.0.1:8000/docs
```

主要接口见 [docs/api.md](docs/api.md)。基本流程是：注册并登录，携带 `Authorization: Bearer <token>` 创建问卷，编辑题目，发布后使用 `share_slug` 查询和答题，最后由所有者查看统计。

接口按业务流程分为五组：

| 分组 | 接口 |
| --- | --- |
| 认证 | `POST /auth/register`、`POST /auth/login` |
| 问卷管理 | `POST /surveys`、`GET /surveys`、`GET/PATCH /surveys/{survey_id}`、`POST /surveys/{survey_id}/publish`、`POST /surveys/{survey_id}/close` |
| 题目库 | `GET/POST /question-items`、题目详情/版本/恢复/派生/使用情况/跨问卷统计、`POST /surveys/{survey_id}/questions/from-library` |
| 分享答题 | `GET /surveys/share/{share_slug}`、`POST /surveys/share/{share_slug}/next`、`POST /surveys/share/{share_slug}/submit` |
| 统计与健康 | `GET /surveys/{survey_id}/statistics`、`GET /health`、`GET /health/db` |

问卷创建、编辑、发布、关闭和统计接口需要所有者身份；分享定义的 GET 接口不要求登录，但导航和提交接口需要填写者登录。错误答案、路径外答案和非法配置会返回结构化错误信息，具体请求与响应见 [API 文档](docs/api.md)。

## 简单前端

启动 FastAPI 后访问 `http://127.0.0.1:8000/`，可以使用内置页面完成注册/登录、题目创建和版本管理、共享/派生、加入问卷、问卷发布和填写，以及题目使用情况和跨问卷统计。原有问卷 JSON 编辑入口继续保留。问卷发布后才会显示可复制的填写链接。页面直接调用同源 API，不需要额外的 Node.js 构建步骤。

服务健康检查：

```text
GET http://127.0.0.1:8000/health
```

MongoDB 连接检查：

```text
GET http://127.0.0.1:8000/health/db
```

`/health/db` 会执行 MongoDB `ping` 命令。连接失败时返回 `503` 和简洁错误信息。

## MongoDB

Windows 示例：

```powershell
New-Item -ItemType Directory -Force D:\MongoDB\data\survey-system | Out-Null
D:\MongoDB\Server\8.3\bin\mongod.exe --dbpath D:\MongoDB\data\survey-system --port 27017
```

应用启动时会创建 `users`、`surveys`、`responses`、`question_items`、`question_versions` 所需索引。题目版本使用 `(question_item_id, version_number)` 唯一索引。MongoDB 不可用时 `/health` 仍可运行，`/health/db` 会返回 503。

## 运行测试

```powershell
.\.venv\Scripts\pytest.exe
```

也可以直接使用当前 Python 环境运行：

```powershell
python -m pytest -q
```

### 测试内容

| 测试文件 | 覆盖内容 |
| --- | --- |
| `tests/test_answer_validator.py` | 四种题型、必答/缺失、选项、重复选择、文本长度、数值边界和有限性 |
| `tests/test_survey_validator.py` | 题目与选项定义、顺序、规则优先级、条件兼容性、目标和循环配置 |
| `tests/test_jump.py` | 默认导航、条件跳转、`end`、非法答案、乱序题目和规则优先级 |
| `tests/test_submission_validation.py` | 服务端实际路径、必答跳过、路径外答案、未知题目、非法目标、循环和最大步数 |
| `tests/test_api_business.py` | 阶段一业务回归，以及题目版本、共享/派生、问卷快照、使用情况和跨问卷统计 |
| `tests/test_health.py` | 健康检查、前端入口和 MongoDB 健康检查响应 |

自动化测试默认使用内存数据库替身，MongoDB 健康检查使用 mock，因此运行自动化测试不要求本地启动真实 MongoDB。

```text
141 passed, 0 failed, 0 errors, 4 warnings in 7.48s
```

4 条 warning 均为依赖弃用提示：FastAPI TestClient 的旧 `httpx` 集成提示，以及旧版 422 状态常量提示，未阻断测试。

数字答案校验的针对性测试结果为 `20 passed`，其中保留并实际执行了 `10**10000` 超大整数边界。若要单独运行某一层测试，可使用：

```powershell
python -m pytest tests/test_jump.py -q
python -m pytest tests/test_submission_validation.py -q
python -m pytest tests/test_api_business.py -q
```

真实 HTTP 和 MongoDB 验收使用隔离数据库 `survey_system_browser_test`，通过 Swagger UI 发起请求并用 `mongosh` 只读核对，记录见 [真实业务测试报告](docs/business-test-report.md)。该验收没有删除或覆盖默认数据库数据。

## 第一阶段范围

- 支持单选、多选、文本和数字题。
- 发布前校验题目、选项、跳转规则和循环。
- 已发布版本不可直接覆盖，编辑会创建新的草稿版本。
- 填写者需要登录；`allow_anonymous` 表示对问卷所有者隐藏填写者身份，不是系统级匿名。
- 默认禁止同一账号重复提交；`allow_multiple_submissions=true` 时允许重复提交。

## 已知限制

- `start_question_id` 尚未实现，提交路径默认从按 `order` 排序后的第一题开始。
- 当前没有进行中的答卷会话、答卷明细导出或所有者查看原始答卷身份的接口。
- 统计支持按版本筛选，但默认跨版本合并统计策略尚未定义为独立业务契约。
- 自动化 API 测试使用内存数据库替身；真实 MongoDB 已完成一轮隔离验收，但未覆盖并发压力、故障恢复和生产部署。
- 旧问卷和旧答卷没有题目来源字段，不会被自动猜测或纳入题目版本跨问卷统计。
- 题目版本中的跨题跳转目标不会在加入问卷时被静默删除；若目标不在问卷中，发布校验会返回 `invalid_jump_target`。
- 题目版本号由服务端生成；并发创建同一题目的版本发生唯一索引冲突时，客户端需要刷新后重试。

## 课程文档

- [最终实验报告](docs/final-project-report.md)
- [第一阶段最终实验报告](docs/phase1-final-report.md)
- [真实业务测试报告](docs/business-test-report.md)
- [系统设计](docs/system-design.md)
- [数据库设计](docs/database-design.md)
- [API 文档](docs/api.md)
- [跳转算法说明](docs/jump-algorithm.md)
- [AI 使用日志](docs/ai-usage-log.md)
