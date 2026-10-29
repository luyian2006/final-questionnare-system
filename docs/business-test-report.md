# 真实业务测试报告

测试时间：2026-10-21

## 测试环境与隔离

- FastAPI：`http://127.0.0.1:8010`
- MongoDB：`mongodb://127.0.0.1:27018`
- 测试数据库：`survey_system_browser_test`
- 测试方式：Swagger UI 浏览器真实 HTTP 请求 + `mongosh` 只读核对
- 未使用默认 `27017` 数据库，未执行删除、清空或覆盖操作。
- `/health` 返回 200，`/health/db` 返回 200 且数据库为 connected。
- 索引已确认创建：用户名唯一、分享标识唯一、答卷查询和重复提交索引。

## 测试结果

### 认证

| 场景 | 预期 | 实际 |
| --- | --- | --- |
| 注册隔离账号 | 201 | 通过 |
| 正确密码登录 | 200，返回 Bearer token | 通过 |
| 错误密码登录 | 401 | 通过 |
| 未登录访问 `/surveys` | 401 | 通过 |
| MongoDB 密码存储 | 不保存明文 | 通过，`pbkdf2_sha256` 哈希 |

### 问卷与发布

- 创建问卷返回 201，列表和详情返回一致数据。
- 详情包含单选、多选、文本、数字四种题型。
- 其他用户访问问卷详情返回 404，所有者隔离有效。
- 合法问卷发布返回 200，`published_version=1`。
- 含循环跳转的草稿发布返回 422，错误码为 `jump_cycle_detected`；该问卷保持 draft。
- 发布后的主问卷关闭返回 200，状态为 `closed`。

### 导航与答案校验

- 单选 `skip` 条件真实导航返回 200，目标为 `q3`，命中 `skip_multi`。
- 非法单选选项返回 422 / `invalid_answer_option`。
- 合法多选返回 200；超过 `max_selected` 返回 422 / `invalid_answer`。
- 短文本返回 422 / `invalid_answer`，合法文本返回 200。
- 非整数和超范围数字分别返回 422 / `invalid_answer`，合法数字返回 `end`。

### 答题与提交

- 提交被跳过的 `q2` 答案返回 422 / `answer_not_on_path`。
- 合法跳题答卷返回 201，服务端路径为 `q1 -> q3 -> q4`。
- 同一答题者重复提交返回 409。
- 第二答题者完整路径提交返回 201，路径为 `q1 -> q2 -> q3 -> q4`。
- MongoDB 核对显示主问卷有 2 份答卷，路径和答题者 ID 均正确保存。

### 统计与状态

统计接口返回 200：

- 单选：`continue=1`、`skip=1`。
- 多选：`a=1`、`b=1`、`c=0`，仅回答该题的答卷计入。
- 文本：返回 2 条文本答案。
- 数字：平均值为 54。

关闭后分享查询和提交均返回 410 / `Survey is closed or expired`。
- 真实 HTTP 截止时间测试：使用 UTC `Z` 格式创建已过期问卷，发布返回 200，分享查询返回 410。
- 真实 HTTP 重复填写测试：`allow_multiple_submissions=true` 时同一账号连续两次提交均返回 201。

## 数据库最终核对

- `users`：3
- `surveys`：2（1 个已关闭发布问卷，1 个循环校验失败后保留的 draft）
- `responses`：2
- 主问卷 `published_version=1`，存在 `closed_at`，答卷数为 2。
- 未删除任何测试数据，测试数据均位于隔离数据库。

## 第一阶段自动化回归（当时结果）

已运行：

```powershell
$env:PYTHONPATH = (Get-Location).Path
$env:PYTHONINTMAXSTRDIGITS = '0'
uv run --no-project --python 3.10 pytest -q
```

结果：`129 passed, 3 warnings`。警告来自当前 FastAPI/Starlette 与 httpx 的兼容性提示，以及旧的 422 常量弃用提示；未阻断测试。

## 第一阶段验收的已知限制

- 该次真实业务验收使用 Swagger UI；其后项目增加了 FastAPI 根路径下的轻量演示前端。
- 第一版未实现 `start_question_id` 语义，也未接入复杂会话/草稿答卷保存。
- 重复提交默认禁止；问卷配置 `allow_multiple_submissions=true` 时允许重复答卷。
- 统计按当前实现直接查询 responses，未做缓存或复杂聚合优化。

## 第二阶段真实业务验收

测试时间：2026-10-28

### 环境与证据范围

- FastAPI：`http://127.0.0.1:8000`
- 数据库：真实 MongoDB
- `/health` 返回 200；`/health/db` 返回 200，数据库状态为 connected。
- 验收方式：真实 HTTP 请求、浏览器交互和 MongoDB 只读核对。
- 本节不是浏览器 E2E 自动化测试记录。项目没有使用 Playwright、Selenium 等工具自动执行完整前端流程；浏览器证据用于确认页面、静态资源、分享参数和分享问卷读取能够实际工作。

### 端到端业务流程

服务日志确认以下请求按顺序成功执行：

| 流程 | 实际请求与结果 |
| --- | --- |
| 注册和登录 | 两个注册请求均为 201；登录为 200 |
| 创建共享题目 | `POST /question-items` 返回 201，创建题目身份和 v1 |
| 创建问卷 | `POST /surveys` 返回 201 |
| 加入指定版本 | `POST /surveys/{survey_id}/questions/from-library` 返回 200 |
| 发布问卷 | `POST /surveys/{survey_id}/publish` 返回 200 |
| 分享读取 | `GET /surveys/share/svy_KxQ21FcX3ixE` 返回 200 |
| 答题导航 | `POST /surveys/share/svy_KxQ21FcX3ixE/next` 返回 200 |
| 提交答卷 | `POST /surveys/share/svy_KxQ21FcX3ixE/submit` 返回 201 |
| 同版本统计 | `GET /question-items/{item_id}/statistics?version_id={version_id}` 返回 200 |
| 使用情况 | `GET /question-items/{item_id}/usage` 返回 200 |

浏览器打开 `http://127.0.0.1:8000/?share=svy_KxQ21FcX3ixE` 后，首页、`styles.css` 和 `app.js` 成功加载，页面自动请求分享问卷接口并获得 200。后续多次重新打开同一分享链接，分享问卷仍可正常读取。

### MongoDB 只读核对

当次验收快照中的集合数量为：

- `users`：2
- `surveys`：1
- `responses`：1
- `question_items`：1
- `question_versions`：1

问卷中的复用题目具有服务端生成的 `qlib_...` 本地 `question_id`，并保存正确的 `source_question_item_id` 和 `source_question_version_id`。答卷的 `survey_snapshot.questions` 保留相同来源版本，答案通过本地题目 ID 与快照对应。跨问卷统计接口返回聚合结果，没有暴露答卷内部保存的 `respondent_user_id`。

### 验收结论

真实环境已确认一条第二阶段闭环：创建共享题目和 v1 -> 创建问卷 -> 加入指定版本 -> 发布 -> 打开分享问卷 -> 导航与提交 -> 查看同版本统计和使用情况。题目来源信息从问卷快照延续到答卷快照，能够支持精确版本统计。该结果与 pytest 自动化测试相互补充，但不替代完整浏览器 E2E 自动化测试。
