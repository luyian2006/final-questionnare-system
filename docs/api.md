# API 说明

默认地址：`http://127.0.0.1:8000`。完整 OpenAPI 页面：`/docs`。

## 认证

- `POST /auth/register`：JSON `{ "username": "alice", "password": "secret123" }`。
- `POST /auth/login`：返回 `access_token` 和 `token_type`。受保护接口使用 `Authorization: Bearer <access_token>`。
- `GET /auth/me`：返回当前登录用户的公开信息，供前端恢复会话所有权状态。

## 问卷管理

- `POST /surveys`：创建草稿，正文包含 `title`、`description`、`questions`、`allow_anonymous`、`allow_multiple_submissions` 和可选 `deadline_at`。
- `GET /surveys`：当前用户自己的问卷列表。
- `GET /surveys/{survey_id}`：当前用户自己的问卷详情和版本。
- `PATCH /surveys/{survey_id}`：编辑草稿；已发布问卷会复制为新草稿版本。
- `POST /surveys/{survey_id}/publish`：发布当前草稿，发布前运行问卷定义校验。
- `POST /surveys/{survey_id}/close`：关闭问卷。

## 分享答题

- `GET /surveys/share/{share_slug}`：读取已发布且未关闭、未过期的问卷定义；此读取接口不要求登录。
- `POST /surveys/share/{share_slug}/next`：需要登录，正文为 `{ "question_id": "q1", "answers": { ... } }`，返回 `goto_question`、`end`、`awaiting_answer` 或错误结果。
- `POST /surveys/share/{share_slug}/submit`：需要登录，正文为 `{ "answers": { ... } }`；服务端重新计算路径并保存答卷。

关闭或截止后，分享查询、导航和提交返回 410。非法答案返回 422，路径外答案返回 `answer_not_on_path`，默认重复提交返回 409。

## 统计与健康检查

- `GET /surveys/{survey_id}/statistics`：仅所有者可访问，支持 `version`、`question_id`、`include_text` 查询参数；返回答卷总数和单题统计。
- `GET /health`：进程健康检查。
- `GET /health/db`：MongoDB ping 检查。

统计包括单选选项计数、多选选项计数、文本答案（可关闭）和数字平均值。答卷内部保存填写者 ID 用于认证和重复控制，但当前没有向所有者提供原始答卷身份接口。
# 第二阶段题目库接口

以下接口均要求现有 Bearer Token。无权访问的私有题目以及非所有者写操作按项目既有习惯返回 404。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/question-items?scope=mine|shared|all` | 查看自己的题目及可访问的共享题目 |
| POST | `/question-items` | 创建题目身份和不可变 v1 |
| GET/PATCH | `/question-items/{item_id}` | 查看题目；所有者修改名称或共享状态 |
| GET/POST | `/question-items/{item_id}/versions` | 查看版本历史；所有者新增版本 |
| GET | `/question-items/{item_id}/versions/{version_id}` | 查看指定历史版本 |
| POST | `/question-items/{item_id}/versions/{version_id}/restore` | 恢复为新的最大版本号 |
| POST | `/question-items/{item_id}/derive` | 从可访问版本派生自己的题目 |
| GET | `/question-items/{item_id}/usage` | 所有者查看问卷版本使用情况 |
| GET | `/question-items/{item_id}/statistics?version_id=...` | 所有者查看同版本脱敏聚合统计 |
| POST | `/surveys/{survey_id}/questions/from-library` | 将指定版本完整复制到问卷草稿 |

创建题目时提交 `display_title`、`is_shared` 和兼容第一阶段题目结构的 `content`。加入问卷时提交 `question_item_id` 与 `question_version_id`。服务端生成问卷内唯一 `question_id`，并写入 `source_question_item_id`、`source_question_version_id`。题目后续更新、恢复或取消共享不会改变已有问卷和答卷快照；旧数据没有来源字段时继续按第一阶段逻辑运行。

