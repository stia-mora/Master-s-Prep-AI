const fs = require("node:fs");
const path = require("node:path");
const {
  QUESTION_TYPE_LABELS,
  moduleFor408QuestionNumber
} = require("./constants");
const { normalizeWhitespace, stableId } = require("./utils");

const LEGACY_408_PREFIX_RE = /^408\u8ba1\u7b97\u673a\uff082009-2025\uff09\//;
const EXAM_QUESTION_DIR = "2009-2025\u8ba1\u7b97\u673a408\u7edf\u8003\u771f\u9898";
const EXAM_SOLUTION_DIR = "2009-2025\u8ba1\u7b97\u673a408\u771f\u9898\u89e3\u6790";
const SUBJECT_408 = "408\u8ba1\u7b97\u673a";
const SUBJECT_DATA_STRUCTURE = "\u6570\u636e\u7ed3\u6784";
const SUBJECT_UPLOAD = "\u7528\u6237\u4e0a\u4f20";
const SUBJECT_OTHER = "\u5176\u4ed6";
const SUPPLEMENT_PREFIX = "\u9898\u5e72\u672a\u80fd\u4ece\u539f\u5377 PDF \u6587\u5b57\u5c42\u63d0\u53d6\uff0c\u4ee5\u4e0b\u4e3a\u771f\u9898\u89e3\u6790\u8865\u5f55\uff1a";
const PLACEHOLDER_TEXT = "\u8be5\u9898\u7684\u9898\u5e72\u548c\u89e3\u6790\u5747\u672a\u80fd\u4ece\u5f53\u524d PDF \u6587\u5b57\u5c42\u63d0\u53d6\u3002\u8bf7\u67e5\u770b\u539f\u59cb PDF\uff0c\u6216\u5b89\u88c5 OCR/MinerU \u540e\u91cd\u65b0\u8f6c\u6362\u3002";

function listMarkdownFiles(rootDir) {
  const files = [];
  if (!fs.existsSync(rootDir)) return files;

  function walk(currentDir) {
    for (const entry of fs.readdirSync(currentDir, { withFileTypes: true })) {
      const fullPath = path.join(currentDir, entry.name);
      if (entry.isDirectory()) {
        if (["state", "logs", "__pycache__"].includes(entry.name)) continue;
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

function logicalRelativePath(filePath, dataRoot) {
  return normalizedRelativePath(filePath, dataRoot).replace(LEGACY_408_PREFIX_RE, "");
}

function preferCanonicalFiles(files, dataRoot) {
  const byLogicalPath = new Map();
  for (const file of files.sort((left, right) => {
    return normalizedRelativePath(left, dataRoot).localeCompare(
      normalizedRelativePath(right, dataRoot),
      "zh-Hans-CN"
    );
  })) {
    const key = logicalRelativePath(file, dataRoot);
    const existing = byLogicalPath.get(key);
    if (!existing) {
      byLogicalPath.set(key, file);
      continue;
    }
    const existingRel = normalizedRelativePath(existing, dataRoot);
    const currentRel = normalizedRelativePath(file, dataRoot);
    if (LEGACY_408_PREFIX_RE.test(existingRel) && !LEGACY_408_PREFIX_RE.test(currentRel)) {
      byLogicalPath.set(key, file);
    }
  }
  return [...byLogicalPath.values()];
}

function classifySource(filePath) {
  const normalized = filePath.replace(/\\/g, "/");
  const fileName = path.basename(filePath);
  const isExamQuestion =
    normalized.includes(EXAM_QUESTION_DIR) &&
    !normalized.includes(EXAM_SOLUTION_DIR) &&
    /^20\d{2}\u5e74\u8ba1\u7b97\u673a408\u7edf\u8003\u771f\u9898\.md$/.test(fileName);
  const isPracticeChoice = fileName.includes("\u9009\u62e9\u9898");
  const isPracticeComprehensive = fileName.includes("\u7efc\u5408\u9898");
  const isUserUpload = normalized.includes("/user_uploads/");

  if (isExamQuestion) {
    return {
      sourceKind: "exam408",
      subject: SUBJECT_408,
      defaultType: null
    };
  }
  if (isPracticeChoice || isPracticeComprehensive) {
    return {
      sourceKind: "practice",
      subject: SUBJECT_DATA_STRUCTURE,
      defaultType: isPracticeChoice ? "choice" : "comprehensive"
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
  if (/408|计算机|数据结构|组成原理|操作系统|计算机网络/.test(haystack)) return SUBJECT_408;
  if (/英语|english/.test(haystack)) return "英语";
  if (/数学|高等数学|线性代数|概率/.test(haystack)) return "数学";
  if (/政治|马克思|毛中特|史纲|思修/.test(haystack)) return "政治";
  return SUBJECT_UPLOAD;
}

function is408Subject(source) {
  const subject = String(source.subject || "");
  return subject.includes("408") || subject.includes("计算机");
}

function isExamSolutionFile(filePath) {
  const normalized = filePath.replace(/\\/g, "/");
  const fileName = path.basename(filePath);
  return normalized.includes(EXAM_SOLUTION_DIR) &&
    /^20\d{2}\u5e74\u8ba1\u7b97\u673a408\u7edf\u8003\u771f\u9898\u89e3\u6790\.md$/.test(fileName);
}

function shouldParseFile(filePath) {
  const source = classifySource(filePath);
  return source.sourceKind === "exam408" || source.sourceKind === "practice" || source.sourceKind === "upload";
}

function parseQuestionStart(line) {
  const match = line.match(/^\s*(?:\u3010\u7b54\u6848\s*P?\d+\u3011?\s*)?((?:0?\d{1,2})|4[Ll])\s*[.．、]\s*(?!\d)(.*)$/);
  if (!match) return null;
  const rawNumber = match[1].replace(/[Ll]/g, "1");
  return {
    number: Number(rawNumber),
    text: match[2] || ""
  };
}

function updateContext(line, context) {
  const chapter = line.match(/^\s*(\u7b2c[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\d]+[\u7ae0]\s+.+?)\s*$/);
  if (chapter) {
    context.chapter = chapter[1].trim();
  }

  const topic = line.match(/^\s*(\d+\.\d+\s+.+?)\s*$/);
  if (topic && !/\d+\.\d+\s+.+\s+\d+$/.test(topic[1])) {
    context.topic = topic[1].trim();
  }

  if (line.includes("\u5355\u9879\u9009\u62e9\u9898")) context.section = "choice";
  if (line.includes("\u7efc\u5408\u5e94\u7528\u9898")) context.section = "comprehensive";
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

function pointsForQuestion(source, number, rawText, questionType) {
  if (source.sourceKind === "exam408" || is408Subject(source)) {
    if (questionType === "choice") return 2;
    return 10;
  }
  return questionType === "choice" ? 2 : 10;
}

function inferQuestionType(source, number, section) {
  if (source.defaultType) return source.defaultType;
  if (section) return section;
  return Number(number) <= 40 ? "choice" : "comprehensive";
}

function inferModule(source, number) {
  if (source.sourceKind === "exam408" || is408Subject(source)) {
    return moduleFor408QuestionNumber(number);
  }
  if (source.subject === SUBJECT_DATA_STRUCTURE) {
    return {
      id: "data_structure",
      name: SUBJECT_DATA_STRUCTURE,
      shortName: SUBJECT_DATA_STRUCTURE
    };
  }
  return null;
}

function inferKnowledge(context, source, questionType) {
  if (context.topic) return context.topic;
  if (context.chapter) return context.chapter;
  if (source.sourceKind === "exam408" || is408Subject(source)) {
    return questionType === "choice" ? "408 \u5355\u9879\u9009\u62e9" : "408 \u7efc\u5408\u5e94\u7528";
  }
  return source.subject;
}

function getYearFromFile(filePath) {
  const match = path.basename(filePath).match(/(20\d{2})/);
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
    const questionType = inferQuestionType(source, current.number, current.section);
    const subjectModule = inferModule(source, current.number);
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
      moduleId: subjectModule ? subjectModule.id : "unknown",
      moduleName: subjectModule ? subjectModule.name : "\u672a\u5206\u7c7b",
      questionType,
      questionTypeLabel: QUESTION_TYPE_LABELS[questionType] || "\u9898\u76ee",
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
    if (/\u7b54\u6848\u901f\u67e5|\u8ba1\u7b97\u673a\u5b66\u79d1\u4e13\u4e1a\u57fa\u7840\u7efc\u5408\u8bd5\u9898\uff08\u7b54\u6848\u901f\u67e5\uff09/.test(line)) {
      finishCurrent();
      break;
    }

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

function parseSolutionStart(line) {
  const match = line.match(/^\s*([1-9]|[1-3]\s*[0-9]|4\s*[0-7]|[Ii])\s*[.．、:：]\s*(.*)$/);
  if (!match) return null;
  const rawNumber = match[1].replace(/\s+/g, "");
  const number = /^[Ii]$/.test(rawNumber) ? 1 : Number(rawNumber);
  const rest = match[2] || "";
  if (number <= 40 && !/[\u89e3\u6790\u89e3\u7b54\u7b54\u6848]/.test(rest)) return null;
  return { number, text: rest };
}

function parseSolutionSnippets(filePath) {
  const text = fs.readFileSync(filePath, "utf8");
  const lines = text.split(/\r?\n/);
  const starts = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (!line || /^<!--/.test(line)) continue;
    const start = parseSolutionStart(line);
    if (start) starts.push({ ...start, index });
  }

  const snippets = new Map();
  for (let i = 0; i < starts.length; i += 1) {
    const start = starts[i];
    if (snippets.has(start.number)) continue;
    const next = starts.slice(i + 1).find((item) => item.number !== start.number);
    const endIndex = next ? next.index : lines.length;
    const raw = lines.slice(start.index, endIndex)
      .filter((line) => !/^<!--/.test(line.trim()))
      .join("\n");
    const snippet = normalizeWhitespace(raw);
    if (snippet.length >= 8) snippets.set(start.number, snippet);
  }
  return snippets;
}

function chooseBetterQuestion(current, candidate) {
  if (!current) return candidate;
  if (current.supplemental && !candidate.supplemental) return candidate;
  if (!current.supplemental && candidate.supplemental) return current;
  const currentChoices = Array.isArray(current.choices) ? current.choices.length : 0;
  const candidateChoices = Array.isArray(candidate.choices) ? candidate.choices.length : 0;
  if (candidateChoices !== currentChoices) {
    return candidateChoices > currentChoices ? candidate : current;
  }
  const currentLength = String(current.rawText || current.stem || "").length;
  const candidateLength = String(candidate.rawText || candidate.stem || "").length;
  return candidateLength > currentLength ? candidate : current;
}

function dedupeExamQuestions(questions) {
  const byQuestion = new Map();
  const output = [];
  for (const question of questions) {
    if (question.parseError || question.sourceKind !== "exam408" || !question.examYear || !question.number) {
      output.push(question);
      continue;
    }
    const key = `${question.examYear}:${question.number}`;
    byQuestion.set(key, chooseBetterQuestion(byQuestion.get(key), question));
  }
  const seen = new Set();
  for (const question of questions) {
    if (question.parseError || question.sourceKind !== "exam408" || !question.examYear || !question.number) continue;
    const key = `${question.examYear}:${question.number}`;
    if (seen.has(key)) continue;
    output.push(byQuestion.get(key));
    seen.add(key);
  }
  return output;
}

function makeSupplementQuestion({ number, snippet, solutionFile, dataRoot }) {
  const relativePath = path.relative(dataRoot, solutionFile).replace(/\\/g, "/");
  const sourceTitle = path.basename(solutionFile, ".md");
  const source = {
    sourceKind: "exam408",
    subject: SUBJECT_408,
    defaultType: null
  };
  const questionType = inferQuestionType(source, number, null);
  const subjectModule = inferModule(source, number);
  const rawText = `${SUPPLEMENT_PREFIX}\n${snippet}`;
  return {
    id: stableId([relativePath, "solution-fallback", number, snippet.slice(0, 80)]),
    sourcePath: relativePath,
    sourceTitle,
    sourceKind: source.sourceKind,
    subject: source.subject,
    examYear: getYearFromFile(solutionFile),
    number,
    moduleId: subjectModule ? subjectModule.id : "unknown",
    moduleName: subjectModule ? subjectModule.name : "\u672a\u5206\u7c7b",
    questionType,
    questionTypeLabel: QUESTION_TYPE_LABELS[questionType] || "\u9898\u76ee",
    knowledge: questionType === "choice"
      ? "408 \u5355\u9879\u9009\u62e9\uff08\u89e3\u6790\u8865\u5f55\uff09"
      : "408 \u7efc\u5408\u5e94\u7528\uff08\u89e3\u6790\u8865\u5f55\uff09",
    stem: rawText,
    choices: [],
    rawText,
    points: pointsForQuestion(source, number, rawText, questionType),
    difficulty: questionType === "choice" ? "basic" : "medium",
    supplemental: true,
    extractionStatus: "solution_fallback"
  };
}

function makePlaceholderQuestion({ number, examFile, dataRoot }) {
  const relativePath = path.relative(dataRoot, examFile).replace(/\\/g, "/");
  const sourceTitle = path.basename(examFile, ".md");
  const source = {
    sourceKind: "exam408",
    subject: SUBJECT_408,
    defaultType: null
  };
  const questionType = inferQuestionType(source, number, null);
  const subjectModule = inferModule(source, number);
  const rawText = `${PLACEHOLDER_TEXT}\n\nPDF: ${relativePath.replace(/\.md$/i, ".pdf")}`;
  return {
    id: stableId([relativePath, "pdf-placeholder", number]),
    sourcePath: relativePath,
    sourceTitle,
    sourceKind: source.sourceKind,
    subject: source.subject,
    examYear: getYearFromFile(examFile),
    number,
    moduleId: subjectModule ? subjectModule.id : "unknown",
    moduleName: subjectModule ? subjectModule.name : "\u672a\u5206\u7c7b",
    questionType,
    questionTypeLabel: QUESTION_TYPE_LABELS[questionType] || "\u9898\u76ee",
    knowledge: questionType === "choice"
      ? "408 \u5355\u9879\u9009\u62e9\uff08PDF \u5360\u4f4d\uff09"
      : "408 \u7efc\u5408\u5e94\u7528\uff08PDF \u5360\u4f4d\uff09",
    stem: rawText,
    choices: [],
    rawText,
    points: pointsForQuestion(source, number, rawText, questionType),
    difficulty: questionType === "choice" ? "basic" : "medium",
    supplemental: true,
    placeholder: true,
    extractionStatus: "pdf_placeholder"
  };
}

function supplementMissingExamQuestions(questions, markdownFiles, solutionFiles, dataRoot) {
  const examFilesByYear = new Map();
  for (const file of markdownFiles) {
    if (classifySource(file).sourceKind !== "exam408") continue;
    const year = getYearFromFile(file);
    if (year) examFilesByYear.set(year, file);
  }
  const examYears = new Set(examFilesByYear.keys());
  const solutionByYear = new Map();
  for (const file of solutionFiles) {
    const year = getYearFromFile(file);
    if (year) solutionByYear.set(year, file);
  }

  const baseQuestions = dedupeExamQuestions(questions);
  const existing = new Set(
    baseQuestions
      .filter((question) => question.sourceKind === "exam408")
      .map((question) => `${question.examYear}:${question.number}`)
  );
  const supplemented = [...baseQuestions];
  for (const year of [...examYears].sort()) {
    const solutionFile = solutionByYear.get(year);
    const snippets = solutionFile ? parseSolutionSnippets(solutionFile) : new Map();
    for (let number = 1; number <= 47; number += 1) {
      const key = `${year}:${number}`;
      if (existing.has(key)) continue;
      if (snippets.has(number)) {
        supplemented.push(makeSupplementQuestion({
          number,
          snippet: snippets.get(number),
          solutionFile,
          dataRoot
        }));
      } else {
        supplemented.push(makePlaceholderQuestion({
          number,
          examFile: examFilesByYear.get(year),
          dataRoot
        }));
      }
      existing.add(key);
    }
  }
  return dedupeExamQuestions(supplemented);
}

function loadQuestionBank(dataRoot) {
  const allFiles = listMarkdownFiles(dataRoot);
  const files = preferCanonicalFiles(allFiles.filter(shouldParseFile), dataRoot);
  const solutionFiles = preferCanonicalFiles(allFiles.filter(isExamSolutionFile), dataRoot);
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
  const questions = supplementMissingExamQuestions(parsed, files, solutionFiles, dataRoot);

  return {
    dataRoot,
    files,
    questions: questions.filter((question) => !question.parseError),
    errors: questions.filter((question) => question.parseError)
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
