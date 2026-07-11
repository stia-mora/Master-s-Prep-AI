const fs = require("node:fs");
const path = require("node:path");
const {
  QUESTION_TYPE_LABELS,
  SUBJECT_PLAN_MATH,
  moduleForMathQuestionNumber
} = require("./constants");
const { normalizeWhitespace, stableId } = require("./utils");

const MATH_EXAM_DIR = "考研数学示例";
const MATH_REAL_EXAM_DIR = "真题_md";
const SUBJECT_MATH = "考研数学";
const SUBJECT_UPLOAD = "用户上传";
const SUBJECT_OTHER = "其他";

function listMarkdownFiles(rootDir) {
  const files = [];
  if (!fs.existsSync(rootDir)) return files;

  function walk(currentDir) {
    for (const entry of fs.readdirSync(currentDir, { withFileTypes: true })) {
      const fullPath = path.join(currentDir, entry.name);
      if (entry.isDirectory()) {
        if (["state", "logs", "work", "assets", "conversion-state", "__pycache__"].includes(entry.name)) continue;
        walk(fullPath);
        continue;
      }
      if (entry.isFile() && entry.name.toLowerCase().endsWith(".md")) {
        files.push(fullPath);
      }
    }
  }

  walk(rootDir);
  return files;
}

function normalizedRelativePath(filePath, dataRoot) {
  return path.relative(dataRoot, filePath).replace(/\\/g, "/");
}

function preferCanonicalFiles(files, dataRoot) {
  const byPath = new Map();
  for (const file of files.sort((left, right) => {
    return normalizedRelativePath(left, dataRoot).localeCompare(
      normalizedRelativePath(right, dataRoot),
      "zh-Hans-CN"
    );
  })) {
    byPath.set(normalizedRelativePath(file, dataRoot), file);
  }
  return [...byPath.values()];
}

function classifySource(filePath) {
  const normalized = filePath.replace(/\\/g, "/");
  const fileName = path.basename(filePath);
  const isUserUpload = normalized.includes("/user_uploads/");
  const isQuestionPack = normalized.includes("/data/knowledge_bases/") && /^question_.*\.md$/i.test(fileName);
  const isRealExamMarkdown = normalized.includes(`/${MATH_REAL_EXAM_DIR}/`) || /(19|20)\d{2}.*(数一|数学|真题|考研)/.test(fileName);
  const isMath = normalized.includes(MATH_EXAM_DIR) || normalized.includes(`/${MATH_REAL_EXAM_DIR}/`) || isQuestionPack || fileName.includes("数学") || /数一|数学|MATH/i.test(fileName);
  const isExamQuestion = isMath && (isRealExamMarkdown || /^20\d{2}年考研数学.*卷\.md$/.test(fileName));

  if (isExamQuestion || isQuestionPack) {
    return {
      sourceKind: "examMath",
      subject: SUBJECT_MATH,
      defaultType: null
    };
  }
  if (isMath) {
    return {
      sourceKind: "practice",
      subject: SUBJECT_MATH,
      defaultType: null
    };
  }
  if (isUserUpload) {
    return {
      sourceKind: "upload",
      subject: SUBJECT_UPLOAD,
      defaultType: null
    };
  }
  return {
    sourceKind: "misc",
    subject: SUBJECT_OTHER,
    defaultType: null
  };
}

function subjectFromUploadText(filePath, text) {
  const meta = String(text || "").match(/<!--\s*subject:\s*([^>]+?)\s*-->/i);
  if (meta) return meta[1].trim();
  const haystack = `${path.basename(filePath)}\n${text}`.toLowerCase();
  if (/数学|高等数学|线性代数|概率|导数|积分|矩阵|随机变量/.test(haystack)) return SUBJECT_MATH;
  return SUBJECT_UPLOAD;
}

function isMathSubject(source) {
  const subject = String(source.subject || "");
  return subject.includes("数学") || source.sourceKind === "examMath";
}

function isExamSolutionFile() {
  return false;
}

function shouldParseFile(filePath) {
  const source = classifySource(filePath);
  return source.sourceKind === "examMath" || source.sourceKind === "practice" || source.sourceKind === "upload";
}

function parseQuestionStart(line) {
  const match = line.match(/^\s*(?:【答案\s*P?\d+】?\s*)?([1-9]\d?)\s*[.．、]\s*(.*)$/);
  if (!match) return parseChineseQuestionStart(line);
  return {
    number: Number(match[1]),
    text: match[2] || ""
  };
}

function chineseNumberToArabic(value) {
  const digits = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10
  };
  if (digits[value]) return digits[value];
  if (value.startsWith("十")) return 10 + (digits[value.slice(1)] || 0);
  const tenMatch = value.match(/^([一二三四五六七八九])十([一二三四五六七八九])?$/);
  if (tenMatch) return digits[tenMatch[1]] * 10 + (digits[tenMatch[2]] || 0);
  return null;
}

function parseChineseQuestionStart(line) {
  const match = line.match(/^\s*#{0,6}\s*([一二三四五六七八九十]{1,3})[、.．]\s*(.*)$/);
  if (!match) return null;
  const number = chineseNumberToArabic(match[1]);
  if (!number) return null;
  const text = match[2] || "";
  if (/填空题|选择题|本题满分|解答|证明|计算|设|求|已知|试/.test(text)) {
    return { number, text };
  }
  return null;
}

function updateContext(line, context) {
  const chapter = line.match(/^\s*(第[一二三四五六七八九十\d]+[章节]\s*.+?)\s*$/);
  if (chapter) context.chapter = chapter[1].trim();

  const topic = line.match(/^\s*(\d+\.\d+\s+.+?)\s*$/);
  if (topic && !/\d+\.\d+\s+.+\s+\d+$/.test(topic[1])) {
    context.topic = topic[1].trim();
  }

  if (/选择题|单项选择题|客观题/.test(line)) context.section = "choice";
  if (/解答题|综合题|计算题|证明题/.test(line)) context.section = "comprehensive";
}

function extractChoices(rawText) {
  const text = normalizeWhitespace(rawText);
  const optionPattern = /(^|\n|\s)([A-D])\s*[.．、]\s*/g;
  const matches = [];
  let match;
  while ((match = optionPattern.exec(text))) {
    matches.push({
      label: match[2],
      markerStart: match.index,
      textStart: match.index + match[0].length
    });
  }

  if (matches.length < 2) {
    return {
      stem: text,
      choices: []
    };
  }

  const firstOptionIndex = matches[0].markerStart;
  const stem = normalizeWhitespace(text.slice(0, firstOptionIndex));
  const choices = matches.map((item, index) => {
    const next = matches[index + 1];
    const end = next ? next.markerStart : text.length;
    return {
      label: item.label,
      text: normalizeWhitespace(text.slice(item.textStart, end))
    };
  }).filter((choice) => choice.text);

  return { stem, choices };
}

function distributePoints(total, count) {
  if (!count) return [];
  const base = Math.floor(total / count);
  const remainder = total - base * count;
  return Array.from({ length: count }, (_, index) => base + (index < remainder ? 1 : 0));
}

function pointsForQuestion(source, number, rawText, questionType) {
  if (isMathSubject(source)) {
    if (questionType === "choice") return SUBJECT_PLAN_MATH.choicePoints;
    const module = moduleForMathQuestionNumber(number);
    if (!module) return 10;
    const choicePoints = module.choiceCount * SUBJECT_PLAN_MATH.choicePoints;
    const comprehensiveTotal = Math.max(0, module.points - choicePoints);
    const slotIndex = module.comprehensiveNumbers.indexOf(Number(number));
    const slotPoints = distributePoints(comprehensiveTotal, module.comprehensiveCount);
    return Math.max(1, slotPoints[slotIndex] || slotPoints[0] || 10);
  }
  return questionType === "choice" ? SUBJECT_PLAN_MATH.choicePoints : 10;
}

function inferQuestionType(source, number, section, rawText = "") {
  if (source.defaultType) return source.defaultType;
  if (section) return section;
  if (/(^|\n|\s)A\s*[.．、]\s*.+(^|\n|\s)B\s*[.．、]\s*/s.test(rawText)) return "choice";
  return Number(number) <= SUBJECT_PLAN_MATH.choiceTotal ? "choice" : "comprehensive";
}

function inferModuleByText(rawText) {
  if (/矩阵|行列式|向量|线性方程组|特征值|特征向量|二次型/.test(rawText)) {
    return SUBJECT_PLAN_MATH.modules.find((item) => item.id === "linear_algebra");
  }
  if (/概率|随机变量|分布|期望|方差|统计|参数估计/.test(rawText)) {
    return SUBJECT_PLAN_MATH.modules.find((item) => item.id === "probability");
  }
  if (/极限|导数|微分|积分|级数|函数|方程|曲线|曲面积分/.test(rawText)) {
    return SUBJECT_PLAN_MATH.modules.find((item) => item.id === "advanced_math");
  }
  return null;
}

function inferModule(source, number, rawText = "") {
  if (isMathSubject(source)) {
    return moduleForMathQuestionNumber(number) || inferModuleByText(rawText);
  }
  return inferModuleByText(rawText);
}

function inferKnowledge(context, source, questionType) {
  if (context.topic) return context.topic;
  if (context.chapter) return context.chapter;
  if (isMathSubject(source)) {
    return questionType === "choice" ? "数学选择题" : "数学解答题";
  }
  return source.subject;
}

function getYearFromFile(filePath) {
  const match = path.basename(filePath).match(/((?:19|20)\d{2})/);
  return match ? Number(match[1]) : null;
}

function parseMarkdownFile(filePath, dataRoot) {
  const source = classifySource(filePath);
  const relativePath = path.relative(dataRoot, filePath);
  const text = fs.readFileSync(filePath, "utf8");
  if (source.sourceKind === "upload") {
    source.subject = subjectFromUploadText(filePath, text);
  }
  const lines = text.split(/\r?\n/);
  const titleLine = lines.find((line) => line.startsWith("# "));
  const sourceTitle = titleLine ? titleLine.replace(/^#\s*/, "").trim() : path.basename(filePath, ".md");
  const questions = [];
  const context = {
    chapter: "",
    topic: "",
    section: source.defaultType
  };
  let current = null;

  function finishCurrent() {
    if (!current) return;
    const rawText = normalizeWhitespace(current.lines.join("\n"));
    if (!rawText || rawText.length < 8) {
      current = null;
      return;
    }
    const questionType = inferQuestionType(source, current.number, current.section, rawText);
    const module = inferModule(source, current.number, rawText);
    const { stem, choices } = extractChoices(rawText);
    const knowledge = inferKnowledge(current.context, source, questionType);
    const id = stableId([relativePath, current.number, stem.slice(0, 80)]);

    questions.push({
      id,
      sourcePath: relativePath.replace(/\\/g, "/"),
      sourceTitle,
      sourceKind: source.sourceKind,
      subject: source.subject,
      examYear: getYearFromFile(filePath),
      number: current.number,
      moduleId: module ? module.id : "unknown",
      moduleName: module ? module.name : "未分类",
      questionType,
      questionTypeLabel: QUESTION_TYPE_LABELS[questionType] || "题目",
      knowledge,
      stem,
      choices,
      rawText,
      points: pointsForQuestion(source, current.number, rawText, questionType),
      difficulty: questionType === "choice" ? "basic" : "medium"
    });
    current = null;
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      if (current) current.lines.push("");
      continue;
    }
    if (/^<!--/.test(line)) continue;

    updateContext(line, context);
    const start = parseQuestionStart(line);
    if (start) {
      finishCurrent();
      current = {
        number: start.number,
        section: context.section,
        context: { ...context },
        lines: [start.text]
      };
      continue;
    }
    if (current) current.lines.push(line);
  }
  finishCurrent();

  return questions;
}

function parseSolutionSnippets() {
  return new Map();
}

function loadQuestionBank(dataRoot) {
  const allFiles = listMarkdownFiles(dataRoot);
  const files = preferCanonicalFiles(allFiles.filter(shouldParseFile), dataRoot);
  const parsed = files.flatMap((file) => {
    try {
      return parseMarkdownFile(file, dataRoot);
    } catch (error) {
      return [{
        id: stableId([file, error.message]),
        parseError: error.message,
        sourcePath: path.relative(dataRoot, file).replace(/\\/g, "/")
      }];
    }
  });

  return {
    dataRoot,
    files,
    questions: parsed.filter((question) => !question.parseError),
    errors: parsed.filter((question) => question.parseError)
  };
}

module.exports = {
  classifySource,
  extractChoices,
  isExamSolutionFile,
  listMarkdownFiles,
  loadQuestionBank,
  parseMarkdownFile,
  parseSolutionSnippets,
  shouldParseFile
};
