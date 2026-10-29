const tokenKey = "survey_access_token";
const userKey = "survey_username";
let currentSurvey = null;
let currentQuestionId = null;
let currentAnswers = {};
let questionScope = "mine";
let messageTimer;

const $ = (id) => document.getElementById(id);

function setMessage(message, isError = false) {
  const box = $("message");
  box.textContent = message;
  box.classList.toggle("error", isError);
  box.hidden = false;
  clearTimeout(messageTimer);
  messageTimer = setTimeout(() => { box.hidden = true; }, 4200);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const token = localStorage.getItem(tokenKey);
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) {
      clearSession();
      openAuthDialog();
      throw new Error("登录状态已失效，请重新登录。");
    }
    const detail = body && typeof body === "object" ? body.detail : body;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail || `HTTP ${response.status}`);
    throw new Error(message);
  }
  return body;
}

function clearSession() {
  localStorage.removeItem(tokenKey);
  localStorage.removeItem(userKey);
  localStorage.removeItem("survey_user_id");
  updateSession();
}

function updateSession() {
  const username = localStorage.getItem(userKey);
  const signedIn = Boolean(username && localStorage.getItem(tokenKey));
  $("sessionText").textContent = signedIn ? username : "未登录";
  $("openAuthButton").hidden = signedIn;
  $("openRegisterButton").hidden = signedIn;
  $("logoutButton").hidden = !signedIn;
}

function openAuthDialog() {
  const dialog = $("authDialog");
  if (!dialog.open) dialog.showModal();
  requestAnimationFrame(() => $("username").focus());
}

function openRegisterDialog() {
  const dialog = $("registerDialog");
  if (!dialog.open) dialog.showModal();
  requestAnimationFrame(() => $("registerUsername").focus());
}

function switchDialog(fromId, openNext) {
  const current = $(fromId);
  if (current.open) current.close();
  openNext();
}

function requireAuthentication() {
  if (localStorage.getItem(tokenKey)) return true;
  openAuthDialog();
  setMessage("请先登录后再继续。", true);
  return false;
}

function renderSignedOutState(target, subject) {
  target.classList.add("empty");
  target.replaceChildren();
  const state = document.createElement("div");
  state.className = "empty-state";
  const copy = document.createElement("div");
  copy.innerHTML = `<strong>登录后查看${subject}</strong><span>使用顶部账号入口登录或注册。</span>`;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button secondary small";
  button.textContent = "登录";
  button.addEventListener("click", openAuthDialog);
  state.append(copy, button);
  target.append(state);
}

function updateSurveySummary(surveys = null) {
  const values = surveys ? [
    surveys.length,
    surveys.filter((survey) => survey.status === "published").length,
    surveys.filter((survey) => survey.status === "draft" || (survey.published_version !== null && survey.current_version !== survey.published_version)).length,
    surveys.filter((survey) => survey.status === "closed").length
  ] : ["--", "--", "--", "--"];
  [...$("surveySummary").querySelectorAll("strong")].forEach((node, index) => { node.textContent = values[index]; });
}

function answer(question, value) {
  return { question_id: question.question_id, type: question.type, value };
}

function deadlinePayload(value) {
  return value ? new Date(`${value}:00+08:00`).toISOString() : null;
}

function serverDate(value) {
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

function deadlineInputValue(value) {
  if (!value) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23"
  }).formatToParts(serverDate(value));
  const part = (type) => parts.find((item) => item.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}`;
}

function formatDeadline(value) {
  if (!value) return "未设置";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", dateStyle: "medium", timeStyle: "short"
  }).format(serverDate(value));
}

function defaultQuestions() {
  return [
    {
      question_id: "q1", type: "single_choice", title: "整体体验如何？", required: true, order: 1,
      options: [{ option_id: "continue", label: "继续填写", order: 1 }, { option_id: "skip", label: "跳过文字题", order: 2 }],
      validation: {}, jump_rules: [{ rule_id: "skip_text", priority: 1, condition: { operator: "equals", value: "skip" }, target: { type: "question", question_id: "q3" } }]
    },
    { question_id: "q2", type: "text_input", title: "你最喜欢的部分是什么？", required: true, order: 2, validation: { min_length: 2, max_length: 120 }, jump_rules: [] },
    { question_id: "q3", type: "number_input", title: "请为本次体验打分（1-10）", required: true, order: 3, validation: { min_value: 1, max_value: 10, integer_only: true }, jump_rules: [] },
    { question_id: "q4", type: "multiple_choice", title: "你使用了哪些功能？", required: true, order: 4,
      options: [{ option_id: "create", label: "创建问卷", order: 1 }, { option_id: "fill", label: "填写问卷", order: 2 }, { option_id: "stats", label: "查看统计", order: 3 }],
      validation: { min_selected: 1, max_selected: 3 }, jump_rules: [] }
  ];
}

$("questionsJson").value = JSON.stringify(defaultQuestions(), null, 2);
$("questionContentJson").value = JSON.stringify({
  question_id: "library_question", type: "single_choice", title: "课程满意度", description: "请选择一项",
  required: true, order: 1,
  options: [{ option_id: "a", label: "满意", order: 1 }, { option_id: "b", label: "一般", order: 2 }],
  validation: {}, jump_rules: []
}, null, 2);

$("registerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = $("registerUsername").value.trim();
  const password = $("registerPassword").value;
  if (password !== $("registerPasswordConfirm").value) {
    setMessage("两次输入的密码不一致。", true);
    return;
  }
  try {
    await api("/auth/register", { method: "POST", body: JSON.stringify({ username, password }) });
    $("username").value = username;
    $("password").value = "";
    $("registerForm").reset();
    switchDialog("registerDialog", openAuthDialog);
    setMessage("注册成功，请登录。");
  } catch (error) { setMessage(error.message, true); }
});

$("openAuthButton").addEventListener("click", openAuthDialog);
$("openRegisterButton").addEventListener("click", openRegisterDialog);
$("switchToRegisterButton").addEventListener("click", () => switchDialog("authDialog", openRegisterDialog));
$("switchToLoginButton").addEventListener("click", () => switchDialog("registerDialog", openAuthDialog));
$("closeAuthButton").addEventListener("click", () => $("authDialog").close());
$("closeRegisterButton").addEventListener("click", () => $("registerDialog").close());
$("authDialog").addEventListener("click", (event) => {
  if (event.target === $("authDialog")) $("authDialog").close();
});
$("registerDialog").addEventListener("click", (event) => {
  if (event.target === $("registerDialog")) $("registerDialog").close();
});

$("authForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/auth/login", { method: "POST", body: JSON.stringify({ username: $("username").value, password: $("password").value }) });
    localStorage.setItem(tokenKey, result.access_token);
    localStorage.setItem(userKey, result.user.username);
    localStorage.setItem("survey_user_id", result.user.user_id);
    updateSession();
    $("authDialog").close();
    setMessage("登录成功。");
    loadSurveys();
    loadQuestionItems();
  } catch (error) { setMessage(error.message, true); }
});

$("logoutButton").addEventListener("click", () => {
  clearSession();
  updateSurveySummary();
  renderSignedOutState($("surveyList"), "问卷");
  renderSignedOutState($("questionList"), "题目");
  $("questionDetail").textContent = "登录后可管理题目。";
  setMessage("已退出登录。");
});

$("surveyForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!requireAuthentication()) return;
  try {
    const questions = JSON.parse($("questionsJson").value);
    const result = await api("/surveys", { method: "POST", body: JSON.stringify({
      title: $("surveyTitle").value,
      description: $("surveyDescription").value,
      questions,
      deadline_at: deadlinePayload($("surveyDeadline").value),
      allow_anonymous: $("allowAnonymous").checked,
      allow_multiple_submissions: $("allowMultiple").checked
    }) });
    setMessage(`问卷草稿已创建：${result.survey_id}`);
    await loadSurveys();
  } catch (error) { setMessage(error.message, true); }
});

$("refreshSurveys").addEventListener("click", loadSurveys);
$("myQuestionsTab").addEventListener("click", () => { questionScope = "mine"; loadQuestionItems(); });
$("sharedQuestionsTab").addEventListener("click", () => { questionScope = "shared"; loadQuestionItems(); });
$("refreshQuestions").addEventListener("click", loadQuestionItems);

$("questionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!requireAuthentication()) return;
  try {
    const result = await api("/question-items", { method: "POST", body: JSON.stringify({
      display_title: $("questionDisplayTitle").value,
      is_shared: $("questionShared").checked,
      content: JSON.parse($("questionContentJson").value)
    }) });
    setMessage(`题目已创建，当前版本 v${result.current_version.version_number}。`);
    questionScope = "mine";
    await loadQuestionItems();
    await showQuestionDetail(result.question_item_id);
  } catch (error) { setMessage(error.message, true); }
});

async function loadSurveys() {
  if (!localStorage.getItem(tokenKey)) {
    updateSurveySummary();
    renderSignedOutState($("surveyList"), "问卷");
    return;
  }
  try {
    const surveys = await api("/surveys");
    updateSurveySummary(surveys);
    const list = $("surveyList");
    list.classList.toggle("empty", surveys.length === 0);
    list.replaceChildren();
    if (!surveys.length) {
      list.innerHTML = '<div class="empty-state"><div><strong>还没有问卷</strong><span>展开“创建问卷”建立第一份草稿。</span></div></div>';
      return;
    }
    for (const survey of surveys) {
      const row = document.createElement("article");
      row.className = "survey-row";
      row.dataset.surveyId = survey.survey_id;
      const info = document.createElement("div");
      const title = document.createElement("div");
      title.className = "survey-title";
      title.textContent = survey.title;
      const meta = document.createElement("div");
      meta.className = "survey-meta";
      const hasDraft = survey.published_version !== null && survey.current_version !== survey.published_version;
      meta.textContent = `当前 v${survey.current_version} · 已发布 ${survey.published_version ? `v${survey.published_version}` : "无"}`;
      const deadline = document.createElement("div");
      deadline.className = "survey-meta";
      deadline.textContent = `截止时间：${formatDeadline(survey.deadline_at)}`;
      const badge = document.createElement("span");
      badge.className = `status-badge ${survey.status === "published" ? "published" : ""}`;
      badge.textContent = hasDraft ? "有未发布草稿" : ({ draft: "草稿", published: "已发布", closed: "已关闭" }[survey.status] || survey.status);
      info.append(title, badge, meta, deadline);
      const actions = document.createElement("div");
      actions.className = "survey-actions";
      addAction(actions, "统计", () => showStatistics(survey.survey_id));
      if (survey.status !== "closed") addAction(actions, "编辑", () => showEditor(survey.survey_id));
      if (survey.status === "draft" || hasDraft) addAction(actions, hasDraft ? "发布新版本" : "发布", () => changeSurveyState(survey.survey_id, "publish"));
      if (survey.status !== "closed") addAction(actions, "关闭", () => changeSurveyState(survey.survey_id, "close"));
      if (survey.published_version && survey.status === "published") addAction(actions, "复制填写链接", () => copyShare(survey.share_slug));
      const share = document.createElement("div");
      share.className = "share-link";
      if (survey.status === "published") share.textContent = `${location.origin}/?share=${survey.share_slug}`;
      else if (survey.status === "closed") share.textContent = "填写链接已关闭";
      else share.textContent = "发布后生成可填写链接";
      row.append(info, actions, share);
      list.append(row);
    }
  } catch (error) { setMessage(error.message, true); }
}

async function loadQuestionItems() {
  if (!localStorage.getItem(tokenKey)) {
    renderSignedOutState($("questionList"), "题目");
    return;
  }
  try {
    if (!localStorage.getItem("survey_user_id")) {
      const user = await api("/auth/me");
      localStorage.setItem("survey_user_id", user.user_id);
    }
    $("questionList").textContent = "正在加载题目…";
    const items = await api(`/question-items?scope=${questionScope}`);
    $("myQuestionsTab").classList.toggle("active", questionScope === "mine");
    $("sharedQuestionsTab").classList.toggle("active", questionScope === "shared");
    const list = $("questionList");
    list.replaceChildren();
    list.classList.toggle("empty", items.length === 0);
    if (!items.length) { list.textContent = questionScope === "mine" ? "还没有题目。" : "暂无共享题目。"; return; }
    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "question-item";
      const title = document.createElement("strong"); title.textContent = item.display_title;
      const meta = document.createElement("span"); meta.className = "survey-meta";
      meta.textContent = `v${item.latest_version_number} · ${item.is_shared ? "已共享" : "私有"}`;
      button.append(title, meta);
      button.addEventListener("click", () => showQuestionDetail(item.question_item_id));
      list.append(button);
    }
  } catch (error) { setMessage(error.message, true); }
}

async function showQuestionDetail(itemId) {
  try {
    $("questionDetail").textContent = "正在加载题目详情…";
    const [item, versions, surveys] = await Promise.all([
      api(`/question-items/${itemId}`), api(`/question-items/${itemId}/versions`), api("/surveys")
    ]);
    const isOwner = item.owner_user_id === localStorage.getItem("survey_user_id");
    const detail = $("questionDetail");
    detail.classList.remove("empty"); detail.replaceChildren();
    const header = document.createElement("div"); header.className = "detail-header";
    const heading = document.createElement("div");
    const title = document.createElement("h3"); title.textContent = item.display_title;
    const meta = document.createElement("div"); meta.className = "detail-meta";
    meta.textContent = `当前 v${item.latest_version_number} · ${item.is_shared ? "共享中" : "私有"}`;
    heading.append(title, meta); header.append(heading); detail.append(header);
    const actions = document.createElement("div"); actions.className = "detail-actions";
    if (isOwner) addAction(actions, item.is_shared ? "取消共享" : "开启共享", async () => {
      try {
        await api(`/question-items/${itemId}`, { method: "PATCH", body: JSON.stringify({ is_shared: !item.is_shared }) });
        setMessage(item.is_shared ? "题目已取消共享。" : "题目已共享。");
        await loadQuestionItems(); await showQuestionDetail(itemId);
      } catch (error) { setMessage(error.message, true); }
    });
    if (!isOwner) addAction(actions, "派生为我的题目", () => deriveQuestion(itemId));
    if (isOwner) addAction(actions, "查看使用情况", () => showQuestionUsage(itemId));
    if (isOwner) addAction(actions, "跨问卷统计", () => showQuestionStatistics(item));
    detail.append(actions);
    const list = document.createElement("div"); list.className = "version-list";
    for (const version of versions) {
      const row = document.createElement("div"); row.className = "version-row";
      const info = document.createElement("div");
      const label = document.createElement("strong"); label.textContent = `v${version.version_number}`;
      const versionMeta = document.createElement("div"); versionMeta.className = "version-meta";
      versionMeta.textContent = version.restored_from_version_id ? "由历史版本恢复" : "不可变版本";
      info.append(label, versionMeta);
      const rowActions = document.createElement("div"); rowActions.className = "actions";
      addAction(rowActions, "查看", () => showVersionContent(version));
      if (!isOwner) addAction(rowActions, "派生此版本", () => deriveQuestion(itemId, version.version_id));
      if (isOwner) addAction(rowActions, "统计", () => showQuestionStatistics(item, version.version_id));
      if (isOwner) addAction(rowActions, "恢复为新版本", async () => {
        try {
          await api(`/question-items/${itemId}/versions/${version.version_id}/restore`, { method: "POST" });
          setMessage(`已从 v${version.version_number} 创建新版本。`); await showQuestionDetail(itemId); await loadQuestionItems();
        } catch (error) { setMessage(error.message, true); }
      });
      row.append(info, rowActions); list.append(row);
    }
    detail.append(list);
    if (isOwner) {
      const form = document.createElement("form"); form.className = "form compact";
      const label = document.createElement("label"); label.textContent = "创建新版本 JSON";
      const textarea = document.createElement("textarea"); textarea.className = "code-input"; textarea.rows = 8;
      textarea.value = JSON.stringify(item.current_version.content, null, 2);
      const submit = document.createElement("button"); submit.type = "submit"; submit.className = "button"; submit.textContent = "创建新版本";
      label.append(textarea); form.append(label, submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await api(`/question-items/${itemId}/versions`, { method: "POST", body: JSON.stringify({ content: JSON.parse(textarea.value) }) });
          setMessage("新版本已创建。"); await showQuestionDetail(itemId); await loadQuestionItems();
        } catch (error) { setMessage(error.message, true); }
      });
      detail.append(form);
    }
    const add = document.createElement("div"); add.className = "library-add";
    const surveySelect = document.createElement("select"); surveySelect.append(new Option("选择我的问卷", ""));
    for (const survey of surveys) if (survey.status !== "closed") surveySelect.append(new Option(survey.title, survey.survey_id));
    const versionSelect = document.createElement("select");
    for (const version of versions) versionSelect.append(new Option(`加入 v${version.version_number}`, version.version_id));
    const addButton = document.createElement("button"); addButton.type = "button"; addButton.className = "button"; addButton.textContent = "加入问卷草稿";
    addButton.addEventListener("click", async () => {
      if (!surveySelect.value) { setMessage("请先选择问卷。", true); return; }
      try {
        await api(`/surveys/${surveySelect.value}/questions/from-library`, { method: "POST", body: JSON.stringify({ question_item_id: itemId, question_version_id: versionSelect.value }) });
        setMessage("题目已复制到问卷草稿。"); await loadSurveys();
      } catch (error) { setMessage(error.message, true); }
    });
    add.append(surveySelect, versionSelect, addButton); detail.append(add);
  } catch (error) { setMessage(error.message, true); }
}

function showVersionContent(version) {
  const output = document.createElement("pre"); output.className = "detail-output";
  output.textContent = JSON.stringify(version.content, null, 2); $("questionDetail").append(output);
}

async function deriveQuestion(itemId, versionId = null) {
  try {
    const result = await api(`/question-items/${itemId}/derive`, { method: "POST", body: JSON.stringify({ version_id: versionId }) });
    setMessage(`已派生题目：${result.display_title}`); questionScope = "mine";
    await loadQuestionItems(); await showQuestionDetail(result.question_item_id);
  } catch (error) { setMessage(error.message, true); }
}

async function showQuestionUsage(itemId) {
  try {
    const result = await api(`/question-items/${itemId}/usage`);
    const output = document.createElement("div"); output.className = "detail-output";
    if (!result.usages.length) output.textContent = "尚未加入任何问卷版本。";
    else for (const usage of result.usages) {
      const row = document.createElement("div"); row.className = "usage-row";
      row.textContent = `${usage.survey_title} · 问卷 v${usage.survey_version} · 题目版本 ${usage.source_question_version_id}`;
      output.append(row);
    }
    $("questionDetail").append(output);
  } catch (error) { setMessage(error.message, true); }
}

async function showQuestionStatistics(item, versionId = null) {
  try {
    const selectedVersion = versionId || item.current_version_id;
    const result = await api(`/question-items/${item.question_item_id}/statistics?version_id=${encodeURIComponent(selectedVersion)}`);
    const output = document.createElement("div"); output.className = "detail-output stats-readable";
    const summary = document.createElement("strong");
    summary.textContent = `v${result.version_number} · ${result.survey_count} 份问卷 · ${result.valid_answer_count} 份有效作答`;
    output.append(summary);
    if (result.options) for (const option of result.options) {
      const row = document.createElement("div"); row.className = "usage-row";
      row.textContent = `${option.label}：${option.count} 次（${(option.ratio * 100).toFixed(1)}%）`;
      output.append(row);
    }
    if (result.type === "number_input") {
      const row = document.createElement("div"); row.className = "usage-row";
      row.textContent = `平均值 ${result.average ?? "无"} · 最小值 ${result.minimum ?? "无"} · 最大值 ${result.maximum ?? "无"}`;
      output.append(row);
    }
    if (result.type === "text_input") {
      const row = document.createElement("div"); row.className = "usage-row";
      row.textContent = `有效文本答卷：${result.text_answer_count}`; output.append(row);
    }
    $("questionDetail").append(output);
  } catch (error) { setMessage(error.message, true); }
}

function addAction(parent, label, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button secondary small";
  button.textContent = label;
  button.addEventListener("click", action);
  parent.append(button);
}

async function changeSurveyState(id, action) {
  try {
    await api(`/surveys/${id}/${action}`, { method: "POST" });
    setMessage(action === "publish" ? "问卷已发布。" : "问卷已关闭。");
    await loadSurveys();
  } catch (error) { setMessage(error.message, true); }
}

async function copyShare(slug) {
  const link = `${location.origin}/?share=${slug}`;
  try {
    await navigator.clipboard.writeText(link);
    setMessage("填写链接已复制。");
  } catch {
    $("shareSlug").value = slug;
    setMessage(`分享标识：${slug}`);
  }
}

async function showStatistics(id) {
  try {
    const row = [...document.querySelectorAll(".survey-row")].find((item) => item.dataset.surveyId === id);
    const target = row || $("surveyList");
    let panel = target.querySelector(".stats-panel");
    if (!panel) {
      const survey = await api(`/surveys/${id}`);
      panel = document.createElement("div");
      panel.className = "stats-panel";
      const toolbar = document.createElement("div");
      toolbar.className = "stats-toolbar";
      const label = document.createElement("label");
      label.textContent = "统计范围";
      const select = document.createElement("select");
      select.className = "version-select";
      select.append(new Option("全部版本", ""));
      for (const version of survey.versions || []) {
        if (version.state === "published") select.append(new Option(`v${version.version}（已发布）`, version.version));
      }
      const output = document.createElement("div");
      output.className = "stats-content";
      label.append(select);
      toolbar.append(label);
      panel.append(toolbar, output);
      target.append(panel);
      select.addEventListener("change", () => loadStatistics(id, select.value, output, survey));
      panel._survey = survey;
    }
    const select = panel.querySelector("select");
    await loadStatistics(id, select.value, panel.querySelector(".stats-content"), panel._survey);
  } catch (error) { setMessage(error.message, true); }
}

function questionTypeLabel(type) {
  return ({ single_choice: "单选题", multiple_choice: "多选题", text_input: "文本题", number_input: "数字题" }[type] || "题目");
}

function statisticDefinitions(survey, version) {
  const versions = survey.versions || [];
  const selected = version
    ? versions.find((item) => String(item.version) === String(version))
    : versions.find((item) => item.version === survey.published_version) || versions.find((item) => item.version === survey.current_version);
  return new Map((selected?.questions || []).map((question) => [question.question_id, question]));
}

function appendMetric(parent, value, label) {
  const metric = document.createElement("div");
  metric.className = "metric";
  const number = document.createElement("strong"); number.textContent = value;
  const caption = document.createElement("span"); caption.textContent = label;
  metric.append(number, caption); parent.append(metric);
}

function renderStatistics(data, survey, version, output) {
  output.replaceChildren();
  const entries = Object.entries(data.questions || {});
  const definitions = statisticDefinitions(survey, version);
  const answeredTotal = entries.reduce((sum, [, stat]) => sum + (stat.answered_count || 0), 0);
  const metrics = document.createElement("div");
  metrics.className = "metric-grid";
  appendMetric(metrics, data.response_count ?? 0, "答卷总数");
  appendMetric(metrics, entries.length, "统计题目");
  appendMetric(metrics, answeredTotal, "有效作答项");
  output.append(metrics);

  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<div><strong>暂无可统计题目</strong><span>发布问卷并收到答卷后，这里会显示结果。</span></div>";
    output.append(empty);
    return;
  }

  for (const [questionId, stat] of entries) {
    const definition = definitions.get(questionId) || {};
    const card = document.createElement("section");
    card.className = "question-stat";
    const header = document.createElement("div"); header.className = "question-stat-header";
    const title = document.createElement("h3"); title.className = "question-stat-title"; title.textContent = definition.title || questionId;
    const meta = document.createElement("span"); meta.className = "question-stat-meta";
    meta.textContent = `${questionTypeLabel(definition.type)} · ${stat.answered_count || 0} 份作答`;
    header.append(title, meta); card.append(header);

    if (stat.option_counts) {
      const labels = new Map((definition.options || []).map((option) => [option.option_id, option.label]));
      for (const [optionId, count] of Object.entries(stat.option_counts)) {
        const denominator = stat.answered_count || 0;
        const ratio = denominator ? count / denominator : 0;
        const row = document.createElement("div"); row.className = "option-stat";
        const label = document.createElement("span"); label.textContent = labels.get(optionId) || optionId;
        const bar = document.createElement("div"); bar.className = "option-bar";
        const fill = document.createElement("span"); fill.style.width = `${Math.min(100, ratio * 100)}%`; bar.append(fill);
        const value = document.createElement("span"); value.className = "option-value"; value.textContent = `${count} 次 · ${(ratio * 100).toFixed(1)}%`;
        row.append(label, bar, value); card.append(row);
      }
    } else if (definition.type === "number_input") {
      const row = document.createElement("div"); row.className = "metric-grid";
      appendMetric(row, stat.average ?? "--", "平均值");
      appendMetric(row, stat.answered_count || 0, "有效数字");
      appendMetric(row, data.response_count ? `${Math.round((stat.answered_count || 0) / data.response_count * 100)}%` : "0%", "作答率");
      card.append(row);
    } else if (definition.type === "text_input") {
      const count = document.createElement("p"); count.className = "status-line";
      count.textContent = `收到 ${stat.answered_count || 0} 条文本回答。`;
      card.append(count);
      if (Array.isArray(stat.answers) && stat.answers.length) {
        const details = document.createElement("details"); details.className = "text-answers";
        const summary = document.createElement("summary"); summary.textContent = "查看文本回答"; details.append(summary);
        for (const answerText of stat.answers) {
          const answerLine = document.createElement("p"); answerLine.className = "text-answer"; answerLine.textContent = answerText; details.append(answerLine);
        }
        card.append(details);
      }
    } else {
      const line = document.createElement("p"); line.className = "status-line"; line.textContent = `有效作答：${stat.answered_count || 0}`; card.append(line);
    }
    output.append(card);
  }
}

async function loadStatistics(id, version, output, survey) {
  const query = version ? `?version=${encodeURIComponent(version)}` : "";
  const data = await api(`/surveys/${id}/statistics${query}`);
  renderStatistics(data, survey, version, output);
}

async function showEditor(id) {
  try {
    const survey = await api(`/surveys/${id}`);
    const row = [...document.querySelectorAll(".survey-row")].find((item) => item.dataset.surveyId === id);
    const existing = row.querySelector(".survey-editor");
    if (existing) { existing.remove(); return; }
    const current = (survey.versions || []).find((item) => item.version === survey.current_version);
    const form = document.createElement("form");
    form.className = "form compact survey-editor";
    form.innerHTML = `
      <div class="editor-heading">编辑当前版本 v${survey.current_version}${survey.published_version === survey.current_version ? "（保存后创建新草稿版本）" : "（草稿）"}</div>
      <label>标题<input name="title" required></label>
      <label>描述<textarea name="description" rows="2"></textarea></label>
      <label>截止时间<input name="deadline" type="datetime-local"></label>
      <label>题目 JSON<textarea name="questions" class="code-input" rows="12"></textarea></label>
      <label class="check"><input name="anonymous" type="checkbox"> 对所有者隐藏填写者身份</label>
      <label class="check"><input name="multiple" type="checkbox"> 允许同一账号重复填写</label>
      <div class="actions"><button class="button" type="submit">保存为当前草稿</button><button class="button secondary" type="button" data-action="cancel">取消</button></div>`;
    form.elements.title.value = survey.title;
    form.elements.description.value = survey.description || "";
    form.elements.deadline.value = deadlineInputValue(survey.deadline_at);
    form.elements.questions.value = JSON.stringify(current?.questions || [], null, 2);
    form.elements.anonymous.checked = survey.allow_anonymous;
    form.elements.multiple.checked = survey.allow_multiple_submissions;
    form.querySelector('[data-action="cancel"]').addEventListener("click", () => form.remove());
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await api(`/surveys/${id}`, { method: "PATCH", body: JSON.stringify({
          title: form.elements.title.value,
          description: form.elements.description.value,
          deadline_at: deadlinePayload(form.elements.deadline.value),
          questions: JSON.parse(form.elements.questions.value),
          allow_anonymous: form.elements.anonymous.checked,
          allow_multiple_submissions: form.elements.multiple.checked
        }) });
        setMessage(survey.published_version ? "修改已保存为新草稿版本，请发布后生效。" : "草稿已保存。");
        await loadSurveys();
      } catch (error) { setMessage(error.message, true); }
    });
    row.append(form);
  } catch (error) { setMessage(error.message, true); }
}

$("shareForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadSharedSurvey($("shareSlug").value.trim());
});

async function loadSharedSurvey(slug) {
  try {
    currentSurvey = await api(`/surveys/share/${encodeURIComponent(slug)}`);
    currentAnswers = {};
    currentQuestionId = currentSurvey.questions.slice().sort((a, b) => a.order - b.order)[0]?.question_id;
    history.replaceState(null, "", `/?share=${encodeURIComponent(slug)}`);
    renderQuestion();
  } catch (error) { setMessage(error.message, true); }
}

function renderQuestion() {
  const area = $("fillArea");
  area.replaceChildren();
  if (!currentSurvey) { area.textContent = "尚未打开分享问卷。"; return; }
  area.classList.remove("empty");
  const question = currentSurvey.questions.find((item) => item.question_id === currentQuestionId);
  if (!question) {
    const done = document.createElement("div");
    done.innerHTML = `<h3>问卷填写完成</h3><p class="status-line">请提交答案完成保存。</p>`;
    const submit = document.createElement("button");
    submit.className = "button";
    submit.textContent = "提交问卷";
    submit.addEventListener("click", submitAnswers);
    area.append(done, submit);
    return;
  }
  const title = document.createElement("h3");
  title.className = "question-title";
  title.textContent = question.title;
  if (question.required) title.insertAdjacentHTML("beforeend", ' <span class="required-mark">*</span>');
  const description = document.createElement("p");
  description.className = "question-description";
  description.textContent = question.description || "";
  const control = document.createElement("div");
  control.className = "question-control";
  const prior = currentAnswers[question.question_id]?.value;
  if (["single_choice", "multiple_choice"].includes(question.type)) {
    const choices = document.createElement("div");
    choices.className = "choice-list";
    for (const option of question.options || []) {
      const label = document.createElement("label");
      label.className = "choice-item";
      const input = document.createElement("input");
      input.type = question.type === "multiple_choice" ? "checkbox" : "radio";
      input.name = question.question_id;
      input.value = option.option_id;
      input.checked = question.type === "multiple_choice" ? (prior || []).includes(option.option_id) : prior === option.option_id;
      const text = document.createElement("span");
      text.textContent = option.label;
      label.append(input, text);
      choices.append(label);
    }
    control.append(choices);
  } else {
    const input = document.createElement(question.type === "text_input" ? "textarea" : "input");
    input.id = "questionAnswer";
    input.className = "question-input";
    input.value = prior ?? "";
    if (question.type === "number_input") { input.type = "number"; input.step = question.validation?.integer_only ? "1" : "any"; }
    if (question.type === "text_input") { input.rows = 3; }
    control.append(input);
  }
  const buttons = document.createElement("div");
  buttons.className = "actions";
  const next = document.createElement("button");
  next.type = "button";
  next.className = "button";
  next.textContent = "保存并继续";
  next.addEventListener("click", () => advance(question));
  buttons.append(next);
  area.append(title, description, control, buttons);
}

function readCurrentValue(question) {
  if (question.type === "single_choice") return document.querySelector(`input[name="${CSS.escape(question.question_id)}"]:checked`)?.value;
  if (question.type === "multiple_choice") return [...document.querySelectorAll(`input[name="${CSS.escape(question.question_id)}"]:checked`)].map((item) => item.value);
  const raw = $("questionAnswer").value;
  if (question.type === "number_input") return raw === "" ? "" : Number(raw);
  return raw;
}

function hasAnswer(question, value) {
  if (question.type === "single_choice") return value !== undefined;
  if (question.type === "multiple_choice") return value.length > 0;
  return value !== "";
}

async function advance(question) {
  const value = readCurrentValue(question);
  const candidateAnswers = { ...currentAnswers };
  if (!hasAnswer(question, value)) {
    delete candidateAnswers[question.question_id];
    if (question.required) {
      setMessage("这道题必须回答后才能继续。", true);
      return;
    }
    currentAnswers = candidateAnswers;
    const ordered = currentSurvey.questions.slice().sort((a, b) => a.order - b.order);
    const index = ordered.findIndex((item) => item.question_id === question.question_id);
    currentQuestionId = ordered[index + 1]?.question_id ?? null;
    renderQuestion();
    return;
  }
  candidateAnswers[question.question_id] = answer(question, value);
  try {
    const result = await api(`/surveys/share/${encodeURIComponent(currentSurvey.share_slug)}/next`, {
      method: "POST", body: JSON.stringify({ question_id: question.question_id, answers: candidateAnswers })
    });
    if (result.action === "awaiting_answer") {
      setMessage("这道题必须回答后才能继续。", true);
      return;
    }
    currentAnswers = candidateAnswers;
    if (result.action === "end") currentQuestionId = null;
    else currentQuestionId = result.question_id;
    renderQuestion();
  } catch (error) { setMessage(error.message, true); }
}

async function submitAnswers() {
  try {
    const result = await api(`/surveys/share/${encodeURIComponent(currentSurvey.share_slug)}/submit`, {
      method: "POST", body: JSON.stringify({ answers: currentAnswers })
    });
    $("fillArea").textContent = `提交成功，答卷编号：${result.response_id}`;
    setMessage("答卷已保存。");
  } catch (error) { setMessage(error.message, true); }
}

updateSession();
const initialSlug = new URLSearchParams(location.search).get("share");
if (initialSlug) { $("shareSlug").value = initialSlug; loadSharedSurvey(initialSlug); }
loadSurveys();
loadQuestionItems();
