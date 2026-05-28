const {
  QUESTION_TYPE_LABELS,
  SUBJECT_PLAN_408,
  modulePercent
} = require("./constants");
const path = require("node:path");
const { clampNumber, groupBy, nowIso, shuffle, stableId } = require("./utils");

function sourceMatches(question, sourceScope) {
  if (sourceScope === "exam408") return question.sourceKind === "exam408";
  if (sourceScope === "practice") return question.sourceKind === "practice";
  return true;
}

function summarizeQuestions(questions) {
  const byModule = {};
  const byType = {};
  let totalPoints = 0;
  for (const question of questions) {
    const moduleName = question.moduleName || "未分类";
    const type = question.questionTypeLabel || QUESTION_TYPE_LABELS[question.questionType] || "题目";
    const points = Number(question.points || 0);
    byModule[moduleName] = {
      count: (byModule[moduleName]?.count || 0) + 1,
      points: (byModule[moduleName]?.points || 0) + points
    };
    byType[type] = (byType[type] || 0) + 1;
    totalPoints += points;
  }
  return {
    questionCount: questions.length,
    totalPoints,
    byModule,
    byType
  };
}

function takeRandom(candidates, count, warnings, label) {
  const selected = shuffle(candidates).slice(0, count);
  if (selected.length < count) {
    warnings.push(`${label} 需要 ${count} 题，当前可用 ${selected.length} 题。`);
  }
  return selected;
}

function distributePoints(total, count) {
  if (!count) return [];
  const base = Math.floor(total / count);
  const remainder = total % count;
  return Array.from({ length: count }, (_, index) => base + (index < remainder ? 1 : 0));
}

function apply408SlotPoints(subjectModule, choices, comprehensive) {
  const choiceQuestions = choices.map((question, index) => ({
    ...question,
    originalPoints: question.points,
    points: 2,
    paperSlot: `${subjectModule.shortName || subjectModule.name} 单选 ${index + 1}`,
    paperPointsSource: "408_template"
  }));
  const comprehensiveTotal = Math.max(0, subjectModule.points - subjectModule.choiceCount * 2);
  const comprehensivePoints = distributePoints(comprehensiveTotal, subjectModule.comprehensiveCount);
  const comprehensiveQuestions = comprehensive.map((question, index) => ({
    ...question,
    originalPoints: question.points,
    points: comprehensivePoints[index] || question.points || 10,
    paperSlot: `${subjectModule.shortName || subjectModule.name} 综合 ${index + 1}`,
    paperPointsSource: "408_template"
  }));
  return [...choiceQuestions, ...comprehensiveQuestions];
}

function normalized408PointFor(question) {
  if (question.questionType === "choice") return 2;
  const subjectModule = SUBJECT_PLAN_408.modules.find((item) => item.id === question.moduleId);
  if (!subjectModule) return Number(question.points || 10);
  const comprehensiveTotal = Math.max(0, subjectModule.points - subjectModule.choiceCount * 2);
  return Math.max(1, Math.round(comprehensiveTotal / Math.max(1, subjectModule.comprehensiveCount)));
}

function originalQuestionKey(question) {
  return [
    question.examYear,
    question.number,
    question.questionType,
    String(question.stem || question.rawText || "").replace(/\s+/g, "").slice(0, 80)
  ].join("|");
}

function uniqueOriginalQuestions(questions) {
  const seen = new Map();
  for (const question of questions) {
    const key = originalQuestionKey(question);
    if (!seen.has(key)) seen.set(key, question);
  }
  return [...seen.values()];
}

class PaperAssembler {
  constructor(questionBank, stateStore) {
    this.questionBank = questionBank;
    this.stateStore = stateStore;
  }

  assemble(payload = {}) {
    const mode = payload.paper_mode || payload.mode || "by_real_exam_format";
    if (mode === "by_real_exam_format") return this.assembleRealExamFormat(payload);
    if (mode === "by_wrong_full") return this.assembleWrongFull(payload);
    if (mode === "by_type") return this.assembleByType(payload);
    if (mode === "by_selected_wrong") return this.assembleSelectedWrong(payload);
    if (mode === "by_original_exam") return this.assembleOriginalExam(payload);
    if (mode === "by_uploaded_source") return this.assembleUploadedSource(payload);
    return this.assembleRealExamFormat(payload);
  }

  getQuestion(questionId) {
    return this.questionBank.questions.find((question) => question.id === questionId);
  }

  assembleRealExamFormat(payload = {}) {
    const warnings = [];
    const sourceScope = payload.source_scope || "all";
    const pool = this.questionBank.questions.filter((question) => sourceMatches(question, sourceScope));
    const selected = [];

    for (const subjectModule of SUBJECT_PLAN_408.modules) {
      const modulePool = pool.filter((question) => question.moduleId === subjectModule.id);
      const choices = takeRandom(
        modulePool.filter((question) => question.questionType === "choice"),
        subjectModule.choiceCount,
        warnings,
        `${subjectModule.name}单选`
      );
      const comprehensive = takeRandom(
        modulePool.filter((question) => question.questionType === "comprehensive"),
        subjectModule.comprehensiveCount,
        warnings,
        `${subjectModule.name}综合题`
      );
      selected.push(...apply408SlotPoints(subjectModule, choices, comprehensive));
    }

    return this.buildPaper({
      mode: "by_real_exam_format",
      title: "408 真题格式随机卷",
      description: "按 408 结构生成：40 道单选、7 道综合题，四个板块按真题比例组织。",
      questions: selected,
      warnings,
      target: {
        choiceTotal: SUBJECT_PLAN_408.choiceTotal,
        comprehensiveTotal: SUBJECT_PLAN_408.comprehensiveTotal,
        modulePlan: SUBJECT_PLAN_408.modules.map((subjectModule) => ({
          moduleId: subjectModule.id,
          moduleName: subjectModule.name,
          percent: modulePercent(subjectModule.id),
          points: subjectModule.points,
          choiceCount: subjectModule.choiceCount,
          comprehensiveCount: subjectModule.comprehensiveCount
        }))
      }
    });
  }

  assembleWrongFull(payload = {}) {
    const warnings = [];
    const userId = payload.user_id;
    const mode = payload.wrong_mode || "same_count";
    const wrongRecords = this.stateStore.getWrongQuestions(userId);
    const wrongQuestions = wrongRecords.map((record) => ({
      ...record.question,
      wrong_id: record.wrong_id,
      wrong_count: record.wrong_count,
      retry_count: record.retry_count,
      manual_wrong_reason: record.manual_wrong_reason
    }));

    if (!wrongQuestions.length) {
      warnings.push("错题库为空，请先在做题区一键加入错题。");
    }

    const selected = [];

    if (mode === "random_by_minutes") {
      const minutes = clampNumber(payload.minutes, 45, 5, SUBJECT_PLAN_408.totalMinutes);
      const targetPoints = Math.max(2, Math.round((minutes / SUBJECT_PLAN_408.totalMinutes) * SUBJECT_PLAN_408.totalPoints));
      for (const subjectModule of SUBJECT_PLAN_408.modules) {
        const moduleTarget = Math.max(2, Math.round(targetPoints * (subjectModule.points / SUBJECT_PLAN_408.totalPoints)));
        const modulePool = shuffle(wrongQuestions.filter((question) => question.moduleId === subjectModule.id));
        let points = 0;
        for (const question of modulePool) {
          if (points >= moduleTarget) break;
          const normalizedPoints = normalized408PointFor(question);
          selected.push({
            ...question,
            originalPoints: question.points,
            points: normalizedPoints,
            paperPointsSource: "408_time_conversion"
          });
          points += normalizedPoints;
        }
        if (points < moduleTarget) {
          warnings.push(`${subjectModule.name}错题目标约 ${moduleTarget} 分，当前只能组到 ${points} 分。`);
        }
      }
      return this.buildPaper({
        mode: "by_wrong_full",
        title: `${minutes} 分钟错题随机卷`,
        description: "按 408 板块分值占比换算预计时长，并从错题库随机抽取。",
        questions: selected,
        warnings,
        target: {
          minutes,
          targetPoints,
          conversion: "目标分值 = 预计分钟数 / 180 * 150"
        }
      });
    }

    for (const subjectModule of SUBJECT_PLAN_408.modules) {
      const modulePool = wrongQuestions.filter((question) => question.moduleId === subjectModule.id);
      const choices = takeRandom(
        modulePool.filter((question) => question.questionType === "choice"),
        subjectModule.choiceCount,
        warnings,
        `${subjectModule.name}错题单选`
      );
      const comprehensive = takeRandom(
        modulePool.filter((question) => question.questionType === "comprehensive"),
        subjectModule.comprehensiveCount,
        warnings,
        `${subjectModule.name}错题综合题`
      );
      selected.push(...apply408SlotPoints(subjectModule, choices, comprehensive));
    }

    return this.buildPaper({
      mode: "by_wrong_full",
      title: "408 完整错题卷",
      description: "按 408 真题题型数量抽取错题，要求各板块错题库都有对应题目。",
      questions: selected,
      warnings,
      target: {
        choiceTotal: SUBJECT_PLAN_408.choiceTotal,
        comprehensiveTotal: SUBJECT_PLAN_408.comprehensiveTotal
      }
    });
  }

  assembleByType(payload = {}) {
    const warnings = [];
    const moduleId = payload.module_id || "all";
    const questionType = payload.question_type || "choice";
    const sourceScope = payload.source_scope || "all";
    const knowledge = String(payload.knowledge || "").trim();
    const countMode = payload.count_mode || "template";

    let pool = this.questionBank.questions.filter((question) => sourceMatches(question, sourceScope));
    if (moduleId !== "all") pool = pool.filter((question) => question.moduleId === moduleId);
    if (questionType !== "all") pool = pool.filter((question) => question.questionType === questionType);
    if (knowledge) {
      pool = pool.filter((question) => {
        return String(question.knowledge || "").includes(knowledge) || String(question.stem || "").includes(knowledge);
      });
    }

    const targetCount = countMode === "custom"
      ? clampNumber(payload.limit, 8, 1, 80)
      : this.templateCountForType(moduleId, questionType);

    const selected = takeRandom(pool, targetCount, warnings, "题型组卷");
    return this.buildPaper({
      mode: "by_type",
      title: "按题型专项卷",
      description: "按模块、题型和关键词筛选，默认数量与 408 真题对应题型保持一致。",
      questions: selected,
      warnings,
      target: {
        moduleId,
        questionType,
        countMode,
        targetCount,
        knowledge
      }
    });
  }

  assembleSelectedWrong(payload = {}) {
    const warnings = [];
    const userId = payload.user_id;
    const ids = Array.isArray(payload.wrong_ids) ? payload.wrong_ids : [];
    const wrongRecords = this.stateStore.getWrongQuestions(userId);
    const selected = wrongRecords
      .filter((record) => ids.includes(record.wrong_id))
      .map((record) => ({
        ...record.question,
        wrong_id: record.wrong_id,
        wrong_count: record.wrong_count,
        retry_count: record.retry_count,
        manual_wrong_reason: record.manual_wrong_reason
      }));
    if (!selected.length) warnings.push("还没有勾选错题。");
    return this.buildPaper({
      mode: "by_selected_wrong",
      title: "勾选错题重刷卷",
      description: "由错题库中勾选的题目直接生成，适合当天复盘。",
      questions: selected,
      warnings,
      target: { selectedWrongCount: ids.length }
    });
  }

  assembleOriginalExam(payload = {}) {
    const warnings = [];
    const year = Number(payload.year);
    const selected = uniqueOriginalQuestions(this.questionBank.questions
      .filter((question) => question.sourceKind === "exam408" && Number(question.examYear) === year))
      .sort((left, right) => Number(left.number || 0) - Number(right.number || 0));

    if (!selected.length) {
      warnings.push(`${year || ""} 年原卷暂未解析出可练习题目。`);
    }
    const choiceCount = selected.filter((question) => question.questionType === "choice").length;
    const comprehensiveCount = selected.filter((question) => question.questionType === "comprehensive").length;
    const supplementalCount = selected.filter((question) => question.supplemental).length;
    const placeholderCount = selected.filter((question) => question.placeholder).length;
    if (selected.length && (choiceCount < SUBJECT_PLAN_408.choiceTotal || comprehensiveCount < SUBJECT_PLAN_408.comprehensiveTotal)) {
      warnings.push(`该年 Markdown 当前解析到 ${choiceCount} 道单选、${comprehensiveCount} 道综合题，可能不是完整原卷。`);
    }
    if (supplementalCount > 0) {
      warnings.push(`其中 ${supplementalCount} 道题由真题解析补录，原卷 PDF 的题干文字层仍需 OCR 才能完全恢复。`);
    }
    if (placeholderCount > 0) {
      warnings.push(`其中 ${placeholderCount} 道题没有可提取文字，已用 PDF/OCR 占位补齐题号。`);
    }

    return this.buildPaper({
      mode: "by_original_exam",
      title: `${year}年计算机408统考真题`,
      description: "来自 408 计算机原始真题 Markdown，按原题顺序进入做题。",
      questions: selected,
      warnings,
      target: {
        year,
        source: "2009-2025计算机408统考真题"
      }
    });
  }

  assembleUploadedSource(payload = {}) {
    const warnings = [];
    const sourcePath = String(payload.source_path || "").replace(/\\/g, "/");
    const selected = this.questionBank.questions
      .filter((question) => question.sourceKind === "upload" && question.sourcePath === sourcePath)
      .sort((left, right) => Number(left.number || 0) - Number(right.number || 0));

    if (!selected.length) {
      warnings.push("该上传资料暂未解析出可练习题目。PDF 需要先完成 OCR/解析。");
    }

    return this.buildPaper({
      mode: "by_uploaded_source",
      title: `${path.basename(sourcePath || "上传资料")} 练习卷`,
      description: "来自组卷页上传资料的题目，按解析顺序进入试卷生成。",
      questions: selected,
      warnings,
      target: { sourcePath }
    });
  }

  templateCountForType(moduleId, questionType) {
    if (moduleId === "all") {
      if (questionType === "choice") return SUBJECT_PLAN_408.choiceTotal;
      if (questionType === "comprehensive") return SUBJECT_PLAN_408.comprehensiveTotal;
      return SUBJECT_PLAN_408.choiceTotal + SUBJECT_PLAN_408.comprehensiveTotal;
    }
    const subjectModule = SUBJECT_PLAN_408.modules.find((item) => item.id === moduleId);
    if (!subjectModule) return 8;
    if (questionType === "choice") return subjectModule.choiceCount;
    if (questionType === "comprehensive") return subjectModule.comprehensiveCount;
    return subjectModule.choiceCount + subjectModule.comprehensiveCount;
  }

  buildPaper({ mode, title, description, questions, warnings, target }) {
    const normalized = questions.map((question, index) => ({
      ...question,
      order: index + 1
    }));
    const summary = summarizeQuestions(normalized);
    return {
      paper_id: stableId([mode, title, nowIso(), String(Math.random())]),
      mode,
      title,
      description,
      created_at: nowIso(),
      target,
      summary,
      warnings,
      modules: SUBJECT_PLAN_408.modules,
      questions: normalized
    };
  }

  questionTypeTree() {
    const grouped = groupBy(this.questionBank.questions, (question) => question.moduleId);
    return SUBJECT_PLAN_408.modules.map((subjectModule) => {
      const questions = grouped[subjectModule.id] || [];
      return {
        ...subjectModule,
        percent: modulePercent(subjectModule.id),
        counts: summarizeQuestions(questions),
        questionTypes: Object.entries(groupBy(questions, (question) => question.questionType)).map(([type, items]) => ({
          type,
          label: QUESTION_TYPE_LABELS[type] || type,
          count: items.length
        })),
        knowledgeSamples: [...new Set(questions.map((question) => question.knowledge).filter(Boolean))].slice(0, 12)
      };
    });
  }

  originalPapers() {
    const papers = new Map();
    for (const file of this.questionBank.files || []) {
      const match = path.basename(file).match(/(20\d{2})年计算机408统考真题\.md$/);
      if (!match) continue;
      const year = Number(match[1]);
      papers.set(year, {
        year,
        subjectId: "computer408",
        subjectName: "计算机 408",
        title: `${year}年计算机408统考真题`,
        sourcePath: path.relative(this.questionBank.dataRoot, file).replace(/\\/g, "/"),
        questionCount: 0,
        choiceCount: 0,
        comprehensiveCount: 0,
        supplementalCount: 0,
        placeholderCount: 0,
        totalPoints: 0,
        available: false,
        completeness: "未解析"
      });
    }

    for (const question of uniqueOriginalQuestions(this.questionBank.questions)) {
      if (question.sourceKind !== "exam408" || !question.examYear) continue;
      if (!papers.has(question.examYear)) {
        papers.set(question.examYear, {
          year: question.examYear,
          subjectId: "computer408",
          subjectName: "计算机 408",
          title: question.sourceTitle,
          sourcePath: question.sourcePath,
          questionCount: 0,
          choiceCount: 0,
          comprehensiveCount: 0,
          supplementalCount: 0,
          placeholderCount: 0,
          totalPoints: 0,
          available: false,
          completeness: "未解析"
        });
      }
      const paper = papers.get(question.examYear);
      paper.questionCount += 1;
      paper.totalPoints += Number(question.points || 0);
      if (question.questionType === "choice") paper.choiceCount += 1;
      if (question.questionType === "comprehensive") paper.comprehensiveCount += 1;
      if (question.supplemental) paper.supplementalCount += 1;
      if (question.placeholder) paper.placeholderCount += 1;
      paper.available = true;
    }

    return [...papers.values()].map((paper) => {
      const complete =
        paper.choiceCount >= SUBJECT_PLAN_408.choiceTotal &&
        paper.comprehensiveCount >= SUBJECT_PLAN_408.comprehensiveTotal;
      let completeness = "暂不可练习";
      if (complete && paper.placeholderCount > 0) {
        completeness = "已补齐题号，部分题干需 OCR/PDF";
      } else if (complete && paper.supplementalCount > 0) {
        completeness = "已补齐题号，部分题干来自解析";
      } else if (complete) {
        completeness = "可完整练习";
      } else if (paper.available) {
        completeness = "可练习，题目不完整";
      }
      return {
        ...paper,
        completeness
      };
    }).sort((left, right) => right.year - left.year);
  }
}

module.exports = {
  PaperAssembler,
  summarizeQuestions
};
