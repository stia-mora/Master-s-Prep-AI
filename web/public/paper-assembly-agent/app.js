const state = {
  health: null,
  subjects: [],
  selectedSubjectId: null,
  collapsedAssemblySubjects: {},
  selectedOriginalSubjectId: null,
  collapsedOriginalSubjects: {},
  modules: [],
  typeTree: [],
  conversion: null,
  originalPapers: [],
  uploadedOriginals: [],
  originalSearch: "",
  editingUploadId: null,
  annotations: {},
  annotationItems: [],
  currentPaper: null,
  currentPaperSourceView: "view-original",
  currentPaperSourceLabel: "返回题库",
  paperSummaryCollapsed: false,
  wrongSearch: "",
  wrongSubjectFilter: "all",
  wrongItems: []
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const API_BASE = "/api/paper-assembly";

const SUBJECT_TYPE_CONFIG = {
  mathKaoyan: {
    modules: "math",
    questionTypes: [
      { value: "choice", label: "选择题" },
      { value: "comprehensive", label: "解答题" },
      { value: "all", label: "全部数学题型" }
    ]
  }
};

async function api(path, options = {}) {
  const response = await fetch(apiPath(path), {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

function apiPath(path) {
  return path.startsWith("/api/") ? `${API_BASE}${path.slice(4)}` : path;
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("is-visible");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.remove("is-visible"), 2400);
}

function showView(id) {
  $$(".view").forEach((view) => view.classList.toggle("is-visible", view.id === id));
  $$(".nav-button").forEach((button) => button.classList.toggle("is-active", button.dataset.view === id));
}

function showAssembleStep(id) {
  ["assembleEntryView", "systemAssembleView", "uploadAssembleView"].forEach((stepId) => {
    $(`#${stepId}`)?.classList.toggle("is-visible", stepId === id);
  });
}

function showBankStep(id) {
  ["bankEntryView", "systemBankView", "uploadedBankView"].forEach((stepId) => {
    $(`#${stepId}`)?.classList.toggle("is-visible", stepId === id);
  });
}

function formData(form) {
  const data = new FormData(form);
  return Object.fromEntries(data.entries());
}

function originalPaperCountsBySubject() {
  return state.originalPapers.reduce((counts, paper) => {
    counts[paper.subjectId] = (counts[paper.subjectId] || 0) + 1;
    return counts;
  }, {});
}

function selectedSubjectConfig() {
  return SUBJECT_TYPE_CONFIG[state.selectedSubjectId] || SUBJECT_TYPE_CONFIG.mathKaoyan;
}

function renderTypeControls() {
  const config = selectedSubjectConfig();
  const moduleSelect = $("#moduleSelect");
  if (moduleSelect) {
    const options = config.modules === "math" ? state.modules : [];
    moduleSelect.innerHTML = `
      <option value="all">全部板块</option>
      ${options.map((module) => `<option value="${module.id}">${module.name}</option>`).join("")}
    `;
  }

  const questionTypeSelect = $("#questionTypeSelect");
  if (questionTypeSelect) {
    const current = questionTypeSelect.value || "choice";
    questionTypeSelect.innerHTML = config.questionTypes
      .map((type) => `<option value="${type.value}">${type.label}</option>`)
      .join("");
    questionTypeSelect.value = config.questionTypes.some((type) => type.value === current)
      ? current
      : config.questionTypes[0]?.value || "all";
  }

  const countMode = $("#realExamForm [name='count_mode']")?.value || "template";
  const customCountField = $("#customCountField");
  if (customCountField) {
    customCountField.hidden = countMode !== "custom";
  }
}

function renderSubjects() {
  const grid = $("#subjectGrid");
  if (!grid) return;
  const originalCounts = originalPaperCountsBySubject();
  grid.innerHTML = state.subjects.map((subject) => `
    <article class="subject-card assembly-subject-card ${subject.id === state.selectedSubjectId ? "is-selected" : ""}">
      <label class="subject-card-pick">
        <input class="subject-input" type="checkbox" data-subject-id="${subject.id}" ${subject.id === state.selectedSubjectId ? "checked" : ""}>
        <span class="subject-content">
          <strong>${subject.name}</strong>
          <span>${subject.description}</span>
          <small>${originalCounts[subject.id] || 0} 套原卷 · 当前可组卷</small>
        </span>
      </label>
      ${subject.id === state.selectedSubjectId ? `
        <button class="card-collapse-button" type="button" data-action="toggle-assembly-subject-card" data-subject-id="${subject.id}">
          ${state.collapsedAssemblySubjects[subject.id] ? "展开" : "收起"}
        </button>
      ` : ""}
    </article>
  `).join("");
  renderAssemblyGate();
  renderTypeControls();
}

function renderOriginalSubjects() {
  const grid = $("#originalSubjectGrid");
  if (!grid) return;
  const originalCounts = originalPaperCountsBySubject();
  grid.innerHTML = state.subjects.map((subject) => `
    <article class="subject-card original-subject-card ${subject.id === state.selectedOriginalSubjectId ? "is-selected" : ""}">
      <label class="subject-card-pick">
        <input class="subject-input" type="checkbox" data-original-subject-id="${subject.id}" ${subject.id === state.selectedOriginalSubjectId ? "checked" : ""}>
        <span class="subject-content">
          <strong>${subject.name}</strong>
          <span>${subject.description}</span>
          <small>${originalCounts[subject.id] || 0} 套原卷 · 可浏览</small>
        </span>
      </label>
      ${subject.id === state.selectedOriginalSubjectId ? `
        <button class="card-collapse-button" type="button" data-action="toggle-original-subject-card" data-subject-id="${subject.id}">
          ${state.collapsedOriginalSubjects[subject.id] ? "展开" : "收起"}
        </button>
      ` : ""}
    </article>
  `).join("");
}

function renderAssemblyGate() {
  const hasSubject = Boolean(state.selectedSubjectId);
  const collapsed = hasSubject && state.collapsedAssemblySubjects[state.selectedSubjectId];
  const gate = $("#assemblyGate");
  const options = $("#assemblyOptions");
  if (gate) gate.hidden = hasSubject;
  if (options) options.hidden = !hasSubject || collapsed;
}

function renderOriginalGate() {
  const hasSubject = Boolean(state.selectedOriginalSubjectId);
  const gate = $("#originalGate");
  if (gate) gate.hidden = hasSubject;
}

function renderHealth() {
  if (!state.health) return;
  $("#sidebarStat").innerHTML = `
    <span>题库 ${state.health.questionCount} 题</span>
    <span>Markdown ${state.health.parsedFiles} 个</span>
    <span>标注 ${state.annotationItems.length} 条</span>
    <span>错题 ${state.wrongItems.length} 题</span>
  `;
}

function annotationTags(annotation = {}) {
  return [
    annotation.star ? "重点" : "",
    annotation.highlight ? "标黄" : "",
    annotation.underline ? "下划线" : "",
    String(annotation.note || "").trim() ? "备注" : ""
  ].filter(Boolean);
}

function renderAnnotationList() {
  const list = $("#annotationList");
  if (!list) return;
  const count = state.annotationItems.length;
  const summary = $("#annotationSummaryText");
  if (summary) {
    summary.textContent = count
      ? `共 ${count} 条标注。备注、重点、标黄和下划线会保存在这里，不等于错题。`
      : "备注、重点、标黄和下划线会保存在这里，不等于错题。";
  }
  if (!count) {
    list.innerHTML = `<div class="empty"><h3>还没有标注</h3><p>在当前试卷里写备注、标黄、下划线或设为重点后，会出现在这里。</p></div>`;
    return;
  }
  list.innerHTML = state.annotationItems.map((item) => {
    const question = item.question || {};
    const annotation = item.annotation || {};
    const tags = annotationTags(annotation);
    const body = question.stem || question.rawText || item.question_id;
    const note = String(annotation.note || "").trim();
    return `
      <article class="annotation-row" data-question-id="${escapeHtml(item.question_id)}">
        <div>
          <div class="tag-row">
            ${tags.map((tag) => `<span class="tag">${tag}</span>`).join("")}
            ${question.moduleName ? `<span class="tag">${question.moduleName}</span>` : ""}
            ${question.questionTypeLabel ? `<span class="tag">${question.questionTypeLabel}</span>` : ""}
            ${question.sourceTitle ? `<span class="tag">${question.sourceTitle}</span>` : ""}
          </div>
          <h4>${escapeHtml(body).slice(0, 120)}</h4>
          ${note ? `<p class="annotation-note">${escapeHtml(note)}</p>` : ""}
        </div>
        <button class="secondary-button" data-action="annotation-add-wrong" ${question.id ? "" : "disabled"}>加入错题</button>
      </article>
    `;
  }).join("");
}

function renderTypeTree() {
  if (!$("#typeTree")) return;
  $("#typeTree").innerHTML = state.typeTree.map((module) => `
    <article class="type-node">
      <h4>${module.name}</h4>
      <p>${module.explanation}</p>
      <div class="tag-row">
        <span class="tag">${module.percent}%</span>
        ${(module.questionTypes || []).map((type) => `<span class="tag">${type.label}: ${type.count}</span>`).join("")}
      </div>
      <p>${(module.knowledgeSamples || []).slice(0, 5).join(" / ")}</p>
    </article>
  `).join("");
}

function renderOriginalPapers() {
  const list = $("#originalList");
  if (!list) return;
  renderOriginalGate();
  if (!state.selectedOriginalSubjectId) {
    list.innerHTML = "";
    return;
  }
  const keyword = state.originalSearch.trim().toLowerCase();
  const filtered = state.originalPapers.filter((paper) => {
    const text = [
      paper.title,
      paper.subjectName,
      paper.sourcePath,
      String(paper.year)
    ].join(" ").toLowerCase();
    return paper.subjectId === state.selectedOriginalSubjectId && (!keyword || text.includes(keyword));
  });
  if (!filtered.length) {
    list.innerHTML = `<div class="empty"><h3>没有找到原卷</h3><p>换一个关键词，或确认该科目的 Markdown 原卷已经放入 data。</p></div>`;
    return;
  }
  if (state.collapsedOriginalSubjects[state.selectedOriginalSubjectId]) {
    list.innerHTML = "";
    return;
  }
  list.innerHTML = `
    <div class="original-card-grid">
      ${filtered.map((paper) => `
        <article class="original-card ${paper.available ? "" : "is-disabled"}">
          <div>
            <h4>${paper.title}</h4>
            <p>${paper.sourcePath}</p>
            <div class="tag-row">
              <span class="tag">${paper.completeness}</span>
              <span class="tag">${paper.questionCount} 题</span>
              <span class="tag">${paper.choiceCount} 单选</span>
              <span class="tag">${paper.comprehensiveCount} 综合</span>
              ${paper.supplementalCount ? `<span class="tag">解析补录 ${paper.supplementalCount}</span>` : ""}
              ${paper.placeholderCount ? `<span class="tag">OCR/PDF 占位 ${paper.placeholderCount}</span>` : ""}
              <span class="tag">${paper.totalPoints} 分</span>
            </div>
          </div>
          <button class="primary-button" data-action="start-original" data-year="${paper.year || ""}" data-source-path="${escapeHtml(paper.sourcePath || "")}" ${paper.available ? "" : "disabled"}>
            开始做题
          </button>
        </article>
      `).join("")}
    </div>
  `;
}

function renderConversionPanel() {
  const panel = $("#conversionPanel");
  if (!panel) return;
  const conversion = state.conversion;
  if (!conversion) {
    panel.innerHTML = `<p class="upload-status">正在读取 PDF 转换环境...</p>`;
    return;
  }
  const runtime = conversion.runtime || {};
  const system = conversion.system || {};
  const ready = Boolean(runtime.ok);
  const running = system.conversionStatus === "running" || system.status === "running";
  panel.innerHTML = `
    <div class="conversion-copy">
      <h4>真题 PDF 转 Markdown</h4>
      <p>${escapeHtml(runtime.message || "检测转换环境中")}</p>
      <div class="tag-row">
        <span class="tag">${ready ? "环境就绪" : "缺少环境"}</span>
        <span class="tag">PDF ${conversion.pendingSystemPdfCount || 0} 个</span>
        <span class="tag">${escapeHtml(system.message || "尚未转换")}</span>
      </div>
      ${conversion.lastLog ? `<p class="upload-note">${escapeHtml(conversion.lastLog)}</p>` : ""}
    </div>
    <button class="primary-button" type="button" data-action="convert-system-exams" ${ready && !running ? "" : "disabled"}>
      ${running ? "转换中" : "转换系统真题"}
    </button>
  `;
}

function renderUploadedOriginals() {
  const list = $("#uploadedOriginalList");
  if (!list) return;
  if (!state.uploadedOriginals.length) {
    list.innerHTML = `<div class="empty"><h3>还没有上传资料</h3><p>从“组卷”的上传资料入口上传 PDF、Markdown 或 TXT 后，会显示在这里。</p></div>`;
    return;
  }
  list.innerHTML = `
    <div class="original-card-grid">
      ${state.uploadedOriginals.map((item) => `
        <article class="original-card upload-material-card ${item.available ? "" : "is-unavailable"}">
          <div>
            <h4>${escapeHtml(item.displayName || item.filename)}</h4>
            <p>${item.kind === "pdf" ? escapeHtml(item.sourcePath || "未生成可练习题库") : escapeHtml(item.sourcePath)}</p>
            <div class="tag-row">
              ${item.subject ? `<span class="tag">${escapeHtml(item.subject)}</span>` : ""}
              <span class="tag">${escapeHtml(item.message || item.status || "")}</span>
              ${item.conversionStatus ? `<span class="tag">${escapeHtml(item.conversionStatus)}</span>` : ""}
              <span class="tag">${escapeHtml(item.ext || "")}</span>
              <span class="tag">${item.questionCount || 0} 题</span>
            </div>
            ${item.note ? `<p class="upload-note">${escapeHtml(item.note)}</p>` : ""}
          </div>
          <div class="original-card-actions">
            <button class="primary-button" data-action="start-uploaded" data-source-path="${escapeHtml(item.sourcePath || "")}" ${item.available ? "" : "disabled"}>
              开始做题
            </button>
            <div class="upload-card-tools">
              <button class="mini-button" type="button" data-action="edit-upload" data-upload-id="${escapeHtml(item.id)}">编辑</button>
              <button class="mini-button danger-button" type="button" data-action="delete-upload" data-upload-id="${escapeHtml(item.id)}">删除</button>
            </div>
          </div>
          ${state.editingUploadId === item.id ? `
            <form class="upload-edit-form" data-upload-id="${escapeHtml(item.id)}">
              <label>
                显示名称
                <input name="displayName" value="${escapeHtml(item.displayName || item.filename)}">
              </label>
              <label>
                科目/分类
                <input name="subject" value="${escapeHtml(item.subject || "")}" placeholder="例如 考研数学、英语、政治">
              </label>
              <label>
                备注
                <textarea name="note" rows="2" placeholder="写一点资料来源、用途或解析说明">${escapeHtml(item.note || "")}</textarea>
              </label>
              <div class="upload-edit-actions">
                <button class="primary-button mini-submit" type="submit">保存</button>
                <button class="secondary-button mini-submit" type="button" data-action="cancel-upload-edit">取消</button>
              </div>
            </form>
          ` : ""}
        </article>
      `).join("")}
    </div>
  `;
}

function selectedSubjectPayload() {
  const subject = state.subjects.find((item) => item.id === state.selectedSubjectId) || state.subjects[0];
  return {
    subject_id: subject?.id || state.selectedSubjectId,
    subject_name: subject?.name || "考研数学"
  };
}

function bindSubjectEvents() {
  $("#subjectGrid")?.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-action='toggle-assembly-subject-card']");
    if (!toggle) return;
    event.preventDefault();
    const subjectId = toggle.dataset.subjectId;
    state.collapsedAssemblySubjects[subjectId] = !state.collapsedAssemblySubjects[subjectId];
    renderSubjects();
  });

  $("#subjectGrid")?.addEventListener("change", (event) => {
    const input = event.target.closest("[data-subject-id]");
    if (!input) return;
    state.selectedSubjectId = input.checked ? input.dataset.subjectId : null;
    if (state.selectedSubjectId) {
      state.collapsedAssemblySubjects[state.selectedSubjectId] = false;
    }
    renderSubjects();
  });
}

function bindOriginalSubjectEvents() {
  $("#originalSubjectGrid")?.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-action='toggle-original-subject-card']");
    if (!toggle) return;
    event.preventDefault();
    const subjectId = toggle.dataset.subjectId;
    state.collapsedOriginalSubjects[subjectId] = !state.collapsedOriginalSubjects[subjectId];
    renderOriginalSubjects();
    renderOriginalPapers();
  });

  $("#originalSubjectGrid")?.addEventListener("change", (event) => {
    const input = event.target.closest("[data-original-subject-id]");
    if (!input) return;
    state.selectedOriginalSubjectId = input.checked ? input.dataset.originalSubjectId : null;
    if (state.selectedOriginalSubjectId) {
      state.collapsedOriginalSubjects[state.selectedOriginalSubjectId] = false;
    }
    renderOriginalSubjects();
    renderOriginalPapers();
  });
}

function paperSourceLabel() {
  if (state.currentPaperSourceView === "view-assemble") return "返回组卷";
  if (state.currentPaperSourceView === "view-wrong") return "返回错题库";
  return "返回题库";
}

function renderPaper(paper) {
  state.currentPaper = paper;
  state.currentPaperSourceLabel = paperSourceLabel();
  $("#paperEmpty").style.display = "none";
  const warningHtml = paper.warnings && paper.warnings.length
    ? `<div class="warning-list">${paper.warnings.map((item) => `<div>${item}</div>`).join("")}</div>`
    : "";
  const moduleSummary = Object.entries(paper.summary.byModule || {}).map(([name, item]) => `
    <div class="summary-item"><strong>${item.count}</strong><span>${name} / ${item.points} 分</span></div>
  `).join("");

  $("#paperView").innerHTML = `
    <section class="paper-head ${state.paperSummaryCollapsed ? "is-collapsed" : ""}">
      <div class="paper-head-top">
        <button class="secondary-button compact-button" type="button" data-action="paper-return-source">${state.currentPaperSourceLabel}</button>
        <button class="mini-button" type="button" data-action="paper-toggle-summary">${state.paperSummaryCollapsed ? "展开概览" : "收起概览"}</button>
      </div>
      <div class="paper-head-main">
        <p class="paper-kicker">当前试卷会保留上一次打开或生成的卷子</p>
        <h3>${paper.title}</h3>
        <p>${paper.description}</p>
        <div class="summary-grid">
          <div class="summary-item"><strong>${paper.summary.questionCount}</strong><span>题目数</span></div>
          <div class="summary-item"><strong>${paper.summary.totalPoints}</strong><span>当前分值</span></div>
          <div class="summary-item"><strong>${paper.summary.byType["单项选择题"] || 0}</strong><span>单项选择</span></div>
          <div class="summary-item"><strong>${paper.summary.byType["综合应用题"] || 0}</strong><span>综合应用</span></div>
          ${moduleSummary}
        </div>
        ${warningHtml}
      </div>
    </section>
    ${paper.questions.map(renderQuestion).join("")}
  `;
  applyAnnotations();
  showView("view-paper");
}

function renderQuestion(question) {
  const annotation = state.annotations[question.id] || {};
  const choices = question.choices && question.choices.length
    ? `<ul class="choice-list">${question.choices.map((choice) => `<li><strong>${choice.label}.</strong> ${renderRichText(choice.text)}</li>`).join("")}</ul>`
    : "";
  const body = question.choices && question.choices.length ? question.stem : question.rawText;
  const starText = annotation.star ? "取消重点" : "重点";

  return `
    <article class="question" data-question-id="${question.id}">
      <div class="question-title">
        <h4>${question.order}. ${question.questionTypeLabel} · ${question.points} 分</h4>
        <div class="tag-row">
          <span class="tag">${question.moduleName}</span>
          ${question.paperSlot ? `<span class="tag">${question.paperSlot}</span>` : ""}
          <span class="tag">${question.knowledge || "未标注知识点"}</span>
          <span class="tag">${question.sourceTitle}</span>
        </div>
      </div>
      <div class="question-body">${renderRichText(body)}</div>
      ${choices}
      <div class="question-actions">
        <button class="mini-button" data-action="highlight">标黄</button>
        <button class="mini-button" data-action="underline">下划线</button>
        <button class="mini-button" data-action="star">${starText}</button>
      </div>
      <div class="question-foot">
        <label>
          错因
          <select data-role="wrong-reason">
            <option value="待分析">待分析</option>
            <option value="概念混淆">概念混淆</option>
            <option value="公式误用">公式误用</option>
            <option value="题型识别错误">题型识别错误</option>
            <option value="计算失误">计算失误</option>
            <option value="时间不足">时间不足</option>
          </select>
        </label>
        <label>
          备注
          <textarea data-role="note" placeholder="写下本题备注；不加入错题也会保存到我的标注">${escapeHtml(annotation.note || "")}</textarea>
        </label>
        <div class="note-save-box">
          <button class="secondary-button" type="button" data-action="save-note">保存备注</button>
          <span data-role="note-status">${annotation.note ? "已保存到我的标注" : "未保存备注"}</span>
        </div>
        <button class="primary-button" data-action="add-wrong">加入错题</button>
      </div>
    </article>
  `;
}

function applyAnnotations() {
  $$(".question").forEach((node) => {
    const id = node.dataset.questionId;
    const annotation = state.annotations[id] || {};
    node.classList.toggle("is-highlighted", Boolean(annotation.highlight));
    node.classList.toggle("is-underlined", Boolean(annotation.underline));
    node.classList.toggle("is-starred", Boolean(annotation.star));
    $("[data-action='highlight']", node)?.classList.toggle("is-active", Boolean(annotation.highlight));
    $("[data-action='underline']", node)?.classList.toggle("is-active", Boolean(annotation.underline));
    $("[data-action='star']", node)?.classList.toggle("is-active", Boolean(annotation.star));
  });
}

function findQuestion(questionId) {
  return state.currentPaper?.questions.find((question) => question.id === questionId);
}

async function refreshAnnotations() {
  const bundle = await api("/api/annotations/items");
  state.annotations = bundle.annotations || {};
  state.annotationItems = bundle.items || [];
  renderAnnotationList();
  renderHealth();
}

async function saveAnnotation(questionId, patch, message = "") {
  const current = state.annotations[questionId] || {};
  state.annotations[questionId] = { ...current, ...patch };
  applyAnnotations();
  await api(`/api/questions/${questionId}/annotation`, {
    method: "POST",
    body: JSON.stringify({ annotation: state.annotations[questionId] })
  });
  await refreshAnnotations();
  if (message) toast(message);
}

async function refreshWrong() {
  const [wrong, summary] = await Promise.all([
    api("/api/wrong-questions"),
    api("/api/wrong-questions/summary")
  ]);
  state.wrongItems = wrong.items || [];
  $("#wrongSummaryText").textContent = `共 ${summary.total} 题，未重刷 ${summary.unreviewedCount} 题，重点 ${summary.focusCount} 题。`;
  renderWrongList();
  renderHealth();
}

function wrongSubjectInfo(item) {
  const question = item.question || {};
  const subjectName = question.subject || question.subjectName || question.subject_name || "";
  const sourceKind = question.sourceKind || "";
  const sourceTitle = question.sourceTitle || "";
  if (subjectName.includes("数学") || sourceKind === "examMath") {
    return { id: "mathKaoyan", name: "考研数学" };
  }
  if (sourceKind === "upload") {
    return { id: "upload", name: subjectName && subjectName !== "用户上传" ? subjectName : "我的上传" };
  }
  if (subjectName) {
    return {
      id: stableDomId(subjectName),
      name: subjectName
    };
  }
  if (sourceTitle) {
    return {
      id: stableDomId(sourceTitle),
      name: sourceTitle
    };
  }
  return { id: "uncategorized", name: "未分科目" };
}

function stableDomId(value) {
  return String(value || "item").trim().toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "-")
    .replace(/^-|-$/g, "") || "item";
}

function wrongSearchText(item) {
  const question = item.question || {};
  const annotation = state.annotations[question.id] || {};
  const subject = wrongSubjectInfo(item);
  return [
    subject.name,
    question.subject,
    question.sourceTitle,
    question.sourcePath,
    question.moduleName,
    question.questionTypeLabel,
    question.knowledge,
    question.stem,
    question.rawText,
    item.manual_wrong_reason,
    item.ai_wrong_reason,
    annotation.note,
    annotation.star ? "重点" : "",
    annotation.highlight ? "标黄" : "",
    annotation.underline ? "下划线" : ""
  ].filter(Boolean).join(" ").toLowerCase();
}

function filteredWrongItems() {
  const keyword = state.wrongSearch.trim().toLowerCase();
  return state.wrongItems.filter((item) => {
    const subject = wrongSubjectInfo(item);
    const subjectMatched = state.wrongSubjectFilter === "all" || subject.id === state.wrongSubjectFilter;
    const searchMatched = !keyword || wrongSearchText(item).includes(keyword);
    return subjectMatched && searchMatched;
  });
}

function wrongSubjects() {
  const subjects = new Map();
  for (const item of state.wrongItems) {
    const subject = wrongSubjectInfo(item);
    subjects.set(subject.id, {
      ...subject,
      count: (subjects.get(subject.id)?.count || 0) + 1
    });
  }
  return [...subjects.values()].sort((left, right) => {
    if (left.id === "mathKaoyan") return -1;
    if (right.id === "mathKaoyan") return 1;
    return left.name.localeCompare(right.name, "zh-Hans-CN");
  });
}

function renderWrongSubjectFilter() {
  const node = $("#wrongSubjectFilter");
  if (!node) return;
  const subjects = wrongSubjects();
  const valid = new Set(["all", ...subjects.map((subject) => subject.id)]);
  if (!valid.has(state.wrongSubjectFilter)) state.wrongSubjectFilter = "all";
  node.innerHTML = `
    <button class="filter-chip ${state.wrongSubjectFilter === "all" ? "is-active" : ""}" type="button" data-wrong-subject="all">
      全部 ${state.wrongItems.length}
    </button>
    ${subjects.map((subject) => `
      <button class="filter-chip ${state.wrongSubjectFilter === subject.id ? "is-active" : ""}" type="button" data-wrong-subject="${escapeHtml(subject.id)}">
        ${escapeHtml(subject.name)} ${subject.count}
      </button>
    `).join("")}
  `;
}

function renderWrongList() {
  const list = $("#wrongList");
  renderWrongSubjectFilter();
  if (!state.wrongItems.length) {
    list.innerHTML = `<div class="empty"><h3>错题库为空</h3><p>做题区点击“加入错题”后会出现在这里。</p></div>`;
    return;
  }
  const filtered = filteredWrongItems();
  if (!filtered.length) {
    list.innerHTML = `<div class="empty"><h3>没有匹配的错题</h3><p>换一个关键词，或切回全部科目。</p></div>`;
    return;
  }
  const grouped = new Map();
  for (const item of filtered) {
    const subject = wrongSubjectInfo(item);
    if (!grouped.has(subject.id)) grouped.set(subject.id, { subject, items: [] });
    grouped.get(subject.id).items.push(item);
  }
  list.innerHTML = [...grouped.values()].map((group) => `
    <section class="wrong-subject-group">
      <div class="wrong-subject-head">
        <h4>${escapeHtml(group.subject.name)}</h4>
        <span>${group.items.length} 题</span>
      </div>
      ${group.items.map(renderWrongRow).join("")}
    </section>
  `).join("");
}

function renderWrongRow(item) {
  const question = item.question || {};
  const annotation = state.annotations[question.id] || {};
  const note = String(annotation.note || "").trim();
  const tags = [
    question.moduleName,
    question.questionTypeLabel,
    question.knowledge,
    question.sourceTitle,
    annotation.star ? "重点" : "",
    annotation.highlight ? "标黄" : "",
    annotation.underline ? "下划线" : ""
  ].filter(Boolean);
  return `
    <article class="wrong-row" data-wrong-id="${item.wrong_id}">
      <input type="checkbox" data-role="wrong-check" value="${item.wrong_id}">
      <div>
        <h4>${escapeHtml((question.stem || question.rawText || "").slice(0, 110))}</h4>
        <div class="tag-row">
          ${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}
          <span class="tag">错 ${item.wrong_count} 次</span>
          <span class="tag">重刷 ${item.retry_count} 次</span>
        </div>
        ${note ? `<p class="wrong-note">备注：${escapeHtml(note)}</p>` : ""}
      </div>
      <input data-role="reason-edit" value="${escapeHtml(item.manual_wrong_reason || item.ai_wrong_reason || "待分析")}">
      <button class="secondary-button" data-action="save-reason">保存错因</button>
    </article>
  `;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderRichText(value) {
  const source = String(value || "");
  const blocks = [];
  let text = source
    .replace(/\r\n/g, "\n")
    .replace(/\\\[((?:.|\n)*?)\\\]/g, (_, formula) => {
      blocks.push(`<div class="math-block">${renderFormula(formula)}</div>`);
      return `@@MATH_BLOCK_${blocks.length - 1}@@`;
    })
    .replace(/\$\$((?:.|\n)*?)\$\$/g, (_, formula) => {
      blocks.push(`<div class="math-block">${renderFormula(formula)}</div>`);
      return `@@MATH_BLOCK_${blocks.length - 1}@@`;
    });
  let html = escapeHtml(text)
    .replace(/\$([^$\n]+?)\$/g, (_, formula) => `<span class="math-inline">${renderFormula(formula)}</span>`)
    .replace(/\n{2,}/g, "<br><br>")
    .replace(/\n/g, "<br>");
  blocks.forEach((block, index) => {
    html = html.replace(`@@MATH_BLOCK_${index}@@`, block);
  });
  return html;
}

function renderFormula(value) {
  let formula = escapeHtml(value).replace(/\s+/g, " ").trim();
  formula = formula
    .replace(/\\displaystyle\s*/g, "")
    .replace(/\\scriptstyle\s*/g, "")
    .replace(/\\operatorname\*\s*\{\s*lim\s*\}/g, "lim")
    .replace(/\\operatorname\s*\{\s*([^}]+)\s*\}/g, "$1")
    .replace(/\\mathrm\s*\{\s*([^}]+)\s*\}/g, "$1")
    .replace(/\\vec\s*\{\s*([^}]+)\s*\}/g, "<span class=\"over-arrow\">$1</span>")
    .replace(/\\underline\s*\{\s*([^{}]+)\s*\}/g, "<u>$1</u>")
    .replace(/\\underbrace\s*\{\s*([^{}]+)\s*\}/g, "<span class=\"underbrace\">$1</span>")
    .replace(/\\sqrt\s*\{\s*([^{}]+)\s*\}/g, "√($1)")
    .replace(/\\frac\s*\{\s*([^{}]+)\s*\}\s*\{\s*([^{}]+)\s*\}/g, "<span class=\"fraction\"><span>$1</span><span>$2</span></span>")
    .replace(/\\begin\s*\{array\}\s*\{[^}]*\}/g, "<span class=\"matrix\">")
    .replace(/\\end\s*\{array\}/g, "</span>")
    .replace(/\\\\/g, "<br>")
    .replace(/&amp;/g, " ")
    .replace(/\\iint/g, "∬")
    .replace(/\\int/g, "∫")
    .replace(/\\sum/g, "∑")
    .replace(/\\lim/g, "lim")
    .replace(/\\to/g, "→")
    .replace(/\\infty/g, "∞")
    .replace(/\\cdots/g, "⋯")
    .replace(/\\ln/g, "ln")
    .replace(/\\sin/g, "sin")
    .replace(/\\cos/g, "cos")
    .replace(/\\pi/g, "π")
    .replace(/\\nu/g, "ν")
    .replace(/\\prime/g, "′")
    .replace(/\\quad/g, " ")
    .replace(/\\left|\\right/g, "")
    .replace(/\\[a-zA-Z]+/g, "");
  return formula
    .replace(/\^\s*\{\s*([^{}]+)\s*\}/g, "<sup>$1</sup>")
    .replace(/_\s*\{\s*([^{}]+)\s*\}/g, "<sub>$1</sub>")
    .replace(/\^\s*([A-Za-z0-9+-])/g, "<sup>$1</sup>")
    .replace(/_\s*([A-Za-z0-9+-])/g, "<sub>$1</sub>");
}

async function assemble(payload, successMessage = "试卷已生成", sourceView = "view-assemble") {
  const paper = await api("/api/paper/assemble", {
    method: "POST",
    body: JSON.stringify({ ...selectedSubjectPayload(), ...payload })
  });
  state.currentPaperSourceView = sourceView;
  state.currentPaperSourceLabel = paperSourceLabel();
  state.paperSummaryCollapsed = false;
  renderPaper(paper);
  toast(successMessage);
}

async function uploadMaterial(form) {
  const status = $("#uploadStatus");
  const file = $("#uploadFile")?.files?.[0];
  if (!file) {
    if (status) status.textContent = "请先选择一个 PDF、Markdown 或 TXT 文件。";
    return;
  }
  if (status) status.textContent = "正在上传并整理资料...";
  const body = new FormData(form);
  const response = await fetch(apiPath("/api/uploads"), {
    method: "POST",
    body
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.error || "上传失败");
  }
  if (status) status.textContent = result.message;
  form.reset();
  if (result.reloaded) {
    await init();
  } else {
    const uploaded = await api("/api/uploads");
    state.uploadedOriginals = uploaded.items || [];
    renderUploadedOriginals();
  }
  toast("资料已上传");
}

async function refreshUploadedOriginals() {
  const uploaded = await api("/api/uploads");
  state.uploadedOriginals = uploaded.items || [];
  renderUploadedOriginals();
}

async function refreshConversionStatus() {
  state.conversion = await api("/api/conversion/status");
  renderConversionPanel();
}

async function convertSystemExams() {
  const result = await api("/api/conversion/system-exams", { method: "POST", body: "{}" });
  await refreshConversionStatus();
  if (result.status === "missing_runtime") {
    toast("缺少 MinerU");
    return;
  }
  toast("系统真题转换已开始");
}

async function saveUploadEdit(form) {
  const uploadId = form.dataset.uploadId;
  const data = formData(form);
  await api("/api/uploads", {
    method: "PATCH",
    body: JSON.stringify({
      id: uploadId,
      displayName: data.displayName,
      subject: data.subject,
      note: data.note
    })
  });
  state.editingUploadId = null;
  await refreshUploadedOriginals();
  toast("资料信息已保存");
}

async function deleteUploadedOriginal(uploadId) {
  const item = state.uploadedOriginals.find((candidate) => candidate.id === uploadId);
  if (!item) return;
  const name = item.displayName || item.filename;
  const confirmed = window.confirm(`确定删除“${name}”吗？相关解析结果也会一起移除。`);
  if (!confirmed) return;
  await api("/api/uploads", {
    method: "DELETE",
    body: JSON.stringify({ id: uploadId })
  });
  state.editingUploadId = null;
  await init();
  showView("view-original");
  showBankStep("uploadedBankView");
  toast("资料已删除");
}

function renderRealModePanels(mode) {
  $$(".real-mode-panel").forEach((panel) => {
    panel.classList.toggle("is-visible", panel.dataset.realPanel === mode);
  });
  const button = $("#realExamSubmit");
  if (button) {
    button.textContent = mode === "type" ? "生成题型专项卷" : "生成真题格式卷";
  }
  renderTypeControls();
}

function bindEvents() {
  $$(".nav-button").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });

  $("#refreshButton").addEventListener("click", init);
  bindSubjectEvents();
  bindOriginalSubjectEvents();

  $("#view-original")?.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    if (button.dataset.action === "open-system-bank") {
      showBankStep("systemBankView");
      await refreshConversionStatus();
    }
    if (button.dataset.action === "open-uploaded-bank") {
      showBankStep("uploadedBankView");
      await refreshUploadedOriginals();
    }
    if (button.dataset.action === "back-bank-home") {
      showBankStep("bankEntryView");
    }
    if (button.dataset.action === "edit-upload") {
      state.editingUploadId = button.dataset.uploadId;
      renderUploadedOriginals();
    }
    if (button.dataset.action === "cancel-upload-edit") {
      state.editingUploadId = null;
      renderUploadedOriginals();
    }
    if (button.dataset.action === "delete-upload") {
      await deleteUploadedOriginal(button.dataset.uploadId);
    }
    if (button.dataset.action === "convert-system-exams") {
      await convertSystemExams();
    }
    if (button.dataset.action === "start-uploaded") {
      if (!button.dataset.sourcePath || button.disabled) return;
      await assemble({ paper_mode: "by_uploaded_source", source_path: button.dataset.sourcePath }, "已打开上传资料试卷", "view-original");
    }
  });

  $("#view-original")?.addEventListener("submit", async (event) => {
    const form = event.target.closest(".upload-edit-form");
    if (!form) return;
    event.preventDefault();
    await saveUploadEdit(form);
  });

  $("#view-assemble")?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    if (button.dataset.action === "open-system-assemble") {
      showAssembleStep("systemAssembleView");
    }
    if (button.dataset.action === "open-upload-assemble") {
      showAssembleStep("uploadAssembleView");
    }
    if (button.dataset.action === "back-assemble-home") {
      showAssembleStep("assembleEntryView");
    }
  });

  $("#originalSearch")?.addEventListener("input", (event) => {
    state.originalSearch = event.target.value;
    renderOriginalPapers();
  });

  $$(".assemble-choice").forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.assemblePanel;
      $$(".assemble-choice").forEach((item) => {
        item.classList.toggle("is-active", item === button);
      });
      $$(".assemble-panel").forEach((panel) => {
        panel.classList.toggle("is-visible", panel.dataset.panel === target);
      });
    });
  });

  $("#realExamForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = formData(event.currentTarget);
    if (data.real_mode === "type") {
      const payload = {
        paper_mode: "by_type",
        source_scope: data.source_scope,
        module_id: data.module_id,
        question_type: data.question_type,
        count_mode: data.count_mode,
        knowledge: data.knowledge
      };
      if (data.count_mode === "custom") payload.limit = data.limit;
      await assemble(payload);
      return;
    }
    await assemble({ paper_mode: "by_real_exam_format", source_scope: data.source_scope });
  });

  $("#realExamForm")?.addEventListener("change", (event) => {
    if (event.target.name === "real_mode") {
      renderRealModePanels(event.target.value);
    }
    if (event.target.name === "count_mode") {
      renderTypeControls();
    }
  });

  $("#wrongPaperForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await assemble({ paper_mode: "by_wrong_full", ...formData(event.currentTarget) });
  });

  $("#uploadForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await uploadMaterial(event.currentTarget);
    } catch (error) {
      $("#uploadStatus").textContent = error.message;
      toast("上传失败");
    }
  });

  $("#paperView").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.action === "paper-return-source") {
      showView(state.currentPaperSourceView || "view-original");
      return;
    }
    if (button.dataset.action === "paper-toggle-summary") {
      state.paperSummaryCollapsed = !state.paperSummaryCollapsed;
      if (state.currentPaper) renderPaper(state.currentPaper);
      return;
    }
    const questionNode = event.target.closest(".question");
    if (!questionNode) return;
    const questionId = questionNode.dataset.questionId;
    const action = button.dataset.action;
    const annotation = state.annotations[questionId] || {};

    if (action === "highlight") await saveAnnotation(questionId, { highlight: !annotation.highlight });
    if (action === "underline") await saveAnnotation(questionId, { underline: !annotation.underline });
    if (action === "star") await saveAnnotation(questionId, { star: !annotation.star });
    if (action === "save-note") {
      const status = $("[data-role='note-status']", questionNode);
      if (status) status.textContent = "保存中...";
      await saveAnnotation(questionId, { note: $("[data-role='note']", questionNode).value }, "备注已保存到我的标注");
      const updatedNode = $(`.question[data-question-id="${CSS.escape(questionId)}"]`);
      const updatedStatus = updatedNode ? $("[data-role='note-status']", updatedNode) : status;
      if (updatedStatus) updatedStatus.textContent = "已保存到我的标注";
    }
    if (action === "add-wrong") {
      const question = findQuestion(questionId);
      const reason = $("[data-role='wrong-reason']", questionNode).value;
      await api("/api/wrong-questions/add", {
        method: "POST",
        body: JSON.stringify({ question, wrong_reason: reason })
      });
      await refreshWrong();
      toast("已加入错题库");
    }
  });

  $("#paperView").addEventListener("input", (event) => {
    if (!event.target.matches("[data-role='note']")) return;
    const questionNode = event.target.closest(".question");
    const status = $("[data-role='note-status']", questionNode);
    if (status) status.textContent = "备注未保存";
  });

  $("#annotationList")?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action='annotation-add-wrong']");
    if (!button || button.disabled) return;
    const row = event.target.closest("[data-question-id]");
    const item = state.annotationItems.find((entry) => entry.question_id === row.dataset.questionId);
    if (!item?.question) return;
    await api("/api/wrong-questions/add", {
      method: "POST",
      body: JSON.stringify({ question: item.question, wrong_reason: "从我的标注加入" })
    });
    await refreshWrong();
    toast("已加入错题库");
  });

  $("#wrongList").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button || button.dataset.action !== "save-reason") return;
    const row = event.target.closest(".wrong-row");
    const value = $("[data-role='reason-edit']", row).value;
    await api(`/api/wrong-questions/${row.dataset.wrongId}/reason`, {
      method: "POST",
      body: JSON.stringify({ wrong_reason: value })
    });
    await refreshWrong();
    toast("错因已保存");
  });

  $("#wrongSearch")?.addEventListener("input", (event) => {
    state.wrongSearch = event.target.value;
    renderWrongList();
  });

  $("#wrongSubjectFilter")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-wrong-subject]");
    if (!button) return;
    state.wrongSubjectFilter = button.dataset.wrongSubject || "all";
    renderWrongList();
  });

  $("#selectedWrongPaperButton").addEventListener("click", async () => {
    const ids = $$("[data-role='wrong-check']:checked").map((node) => node.value);
    await assemble({ paper_mode: "by_selected_wrong", wrong_ids: ids }, "已打开勾选错题卷", "view-wrong");
  });

  $("#originalList").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action='start-original']");
    if (!button || button.disabled) return;
    await assemble({
      paper_mode: "by_original_exam",
      year: button.dataset.year,
      source_path: button.dataset.sourcePath
    }, "已打开原题试卷", "view-original");
  });
}

async function init() {
  try {
    const [health, subjects, modules, tree, originalPapers, uploadedOriginals, conversion, annotationBundle] = await Promise.all([
      api("/api/health"),
      api("/api/subjects"),
      api("/api/modules"),
      api("/api/paper/question-types"),
      api("/api/papers/original"),
      api("/api/uploads"),
      api("/api/conversion/status"),
      api("/api/annotations/items")
    ]);
    state.health = health;
    state.subjects = subjects.items || [];
    state.modules = modules.modules || [];
    state.typeTree = tree.modules || [];
    state.originalPapers = originalPapers.items || [];
    state.uploadedOriginals = uploadedOriginals.items || [];
    state.conversion = conversion;
    state.annotations = annotationBundle.annotations || {};
    state.annotationItems = annotationBundle.items || [];
    if (state.selectedSubjectId && !state.subjects.some((subject) => subject.id === state.selectedSubjectId)) {
      state.selectedSubjectId = null;
    }
    if (state.selectedOriginalSubjectId && !state.subjects.some((subject) => subject.id === state.selectedOriginalSubjectId)) {
      state.selectedOriginalSubjectId = null;
    }
    renderSubjects();
    renderOriginalSubjects();
    renderTypeTree();
    renderOriginalPapers();
    renderConversionPanel();
    renderUploadedOriginals();
    renderAnnotationList();
    await refreshWrong();
    renderHealth();
  } catch (error) {
    toast(`读取失败：${error.message}`);
  }
}

bindEvents();
init();
