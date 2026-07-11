const fs = require("node:fs");
const path = require("node:path");
const { DEFAULT_USER_ID } = require("./constants");
const { nowIso, stableId } = require("./utils");

const emptyState = () => ({ version: 1, users: {} });

class StateStore {
  constructor(filePath) {
    this.filePath = filePath;
    this.state = this.load();
  }

  load() {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
    if (!fs.existsSync(this.filePath)) {
      return emptyState();
    }

    try {
      const parsed = JSON.parse(fs.readFileSync(this.filePath, "utf8"));
      return parsed && parsed.users ? parsed : emptyState();
    } catch {
      return emptyState();
    }
  }

  save() {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
    fs.writeFileSync(this.filePath, JSON.stringify(this.state, null, 2), "utf8");
  }

  getUser(userId = DEFAULT_USER_ID) {
    if (!this.state.users[userId]) {
      this.state.users[userId] = {
        wrongQuestions: [],
        annotations: {},
        papers: []
      };
    }
    return this.state.users[userId];
  }

  getAnnotations(userId = DEFAULT_USER_ID) {
    return this.getUser(userId).annotations;
  }

  updateAnnotation(userId = DEFAULT_USER_ID, questionId, patch = {}) {
    const user = this.getUser(userId);
    const existing = user.annotations[questionId] || {};
    user.annotations[questionId] = {
      ...existing,
      ...patch,
      updatedAt: nowIso()
    };
    this.save();
    return user.annotations[questionId];
  }

  getWrongQuestions(userId = DEFAULT_USER_ID) {
    return [...this.getUser(userId).wrongQuestions].sort((a, b) => {
      return String(b.last_wrong_at || "").localeCompare(String(a.last_wrong_at || ""));
    });
  }

  addWrongQuestion(userId = DEFAULT_USER_ID, question, fields = {}) {
    const user = this.getUser(userId);
    const wrongId = stableId([userId, question.id]);
    const now = nowIso();
    const existing = user.wrongQuestions.find((item) => item.wrong_id === wrongId);
    const reason = fields.wrong_reason || fields.manual_wrong_reason || "待分析";

    if (existing) {
      existing.wrong_count = Number(existing.wrong_count || 1) + 1;
      existing.last_wrong_at = now;
      existing.manual_wrong_reason = reason;
      existing.is_focus = Boolean(fields.is_focus ?? existing.is_focus);
      existing.question = question;
      this.save();
      return existing;
    }

    const record = {
      wrong_id: wrongId,
      question_id: question.id,
      user_id: userId,
      wrong_count: 1,
      retry_count: 0,
      ai_wrong_reason: fields.ai_wrong_reason || "",
      manual_wrong_reason: reason,
      is_focus: Boolean(fields.is_focus),
      review_status: "未重刷",
      last_wrong_at: now,
      last_retry_at: "",
      last_result: "",
      question
    };
    user.wrongQuestions.push(record);
    this.save();
    return record;
  }

  updateWrongQuestion(userId = DEFAULT_USER_ID, wrongId, patch = {}) {
    const user = this.getUser(userId);
    const target = user.wrongQuestions.find((item) => item.wrong_id === wrongId);
    if (!target) return null;
    Object.assign(target, patch);
    this.save();
    return target;
  }

  recordRetry(userId = DEFAULT_USER_ID, wrongId) {
    const target = this.updateWrongQuestion(userId, wrongId, {});
    if (!target) return null;
    target.retry_count = Number(target.retry_count || 0) + 1;
    target.last_retry_at = nowIso();
    target.review_status = "已重刷";
    this.save();
    return target;
  }

  summarizeWrongQuestions(userId = DEFAULT_USER_ID) {
    const wrongQuestions = this.getWrongQuestions(userId);
    const byModule = {};
    const byType = {};
    const byReason = {};
    let focusCount = 0;

    for (const item of wrongQuestions) {
      const moduleName = item.question.moduleName || "未分类";
      const type = item.question.questionTypeLabel || "题目";
      const reason = item.manual_wrong_reason || item.ai_wrong_reason || "待分析";
      byModule[moduleName] = (byModule[moduleName] || 0) + 1;
      byType[type] = (byType[type] || 0) + 1;
      byReason[reason] = (byReason[reason] || 0) + 1;
      if (item.is_focus) focusCount += 1;
    }

    return {
      total: wrongQuestions.length,
      focusCount,
      unreviewedCount: wrongQuestions.filter((item) => item.review_status !== "已重刷").length,
      byModule,
      byType,
      byReason,
      repeatedTop: [...wrongQuestions]
        .sort((a, b) => Number(b.wrong_count || 0) - Number(a.wrong_count || 0))
        .slice(0, 10)
    };
  }
}

module.exports = { StateStore };
