import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";

type JsonRecord = Record<string, unknown>;
type UploadedFile = {
  filename: string;
  mimeType?: string;
  buffer: Buffer;
};

function resolveProjectRoot(): string {
  const configured = process.env.MASTER_PREP_AI_ROOT;
  const candidates = [
    configured ? path.resolve(configured) : "",
    process.cwd(),
    path.resolve(process.cwd(), ".."),
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (fs.existsSync(path.join(candidate, "pyproject.toml"))) return candidate;
  }
  return path.basename(process.cwd()).toLowerCase() === "web"
    ? path.resolve(process.cwd(), "..")
    : process.cwd();
}

const PROJECT_ROOT = resolveProjectRoot();
const AGENT_ROOT = path.join(PROJECT_ROOT, "web", "lib", "paper-assembly-agent");
const requireFromAgent = createRequire(path.join(AGENT_ROOT, "service.js"));
const {
  DEFAULT_USER_ID,
  SUBJECTS,
  SUBJECT_PLAN_MATH,
} = requireFromAgent("./src/constants.js");
const { loadQuestionBank } = requireFromAgent("./src/markdownParser.js");
const { PaperAssembler } = requireFromAgent("./src/paperAssembler.js");
const { StateStore } = requireFromAgent("./src/stateStore.js");
const DATA_ROOT = process.env.PAPER_ASSEMBLY_DATA_ROOT
  ? path.resolve(process.env.PAPER_ASSEMBLY_DATA_ROOT)
  : path.join(PROJECT_ROOT, "data");
const USER_DATA_DIR = path.join(DATA_ROOT, "user_uploads");
const UPLOAD_META_FILE = path.join(USER_DATA_DIR, "upload-meta.json");
const STATE_FILE = path.join(DATA_ROOT, "user", "paper-assembly-agent-state.json");
const UPLOAD_DIR = path.join(DATA_ROOT, "user", "paper-assembly-agent-uploads");
const PDF_EXTRACT_SCRIPT = path.join(
  AGENT_ROOT,
  "scripts",
  "extract_pdf_text.py",
);
const BUNDLED_PYTHON = path.join(
  os.homedir(),
  ".cache",
  "codex-runtimes",
  "codex-primary-runtime",
  "dependencies",
  "python",
  "python.exe",
);

const stateStore = new StateStore(STATE_FILE);
let questionBank = loadQuestionBank(DATA_ROOT);
let assembler = new PaperAssembler(questionBank, stateStore);

function reloadQuestionBank() {
  questionBank = loadQuestionBank(DATA_ROOT);
  assembler = new PaperAssembler(questionBank, stateStore);
  return questionBank;
}

function pythonExecutable(): string {
  return fs.existsSync(BUNDLED_PYTHON) ? BUNDLED_PYTHON : "python";
}

function extractPdfText(pdfPath: string): string {
  const result = spawnSync(pythonExecutable(), [PDF_EXTRACT_SCRIPT, pdfPath], {
    encoding: "utf8",
    maxBuffer: 40 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error((result.stderr || result.stdout || "PDF text extraction failed").trim());
  }
  return result.stdout || "";
}

function normalizeExtractedText(text: string): string {
  return String(text || "")
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{4,}/g, "\n\n\n")
    .trim();
}

function loadUploadMeta(): Record<string, JsonRecord> {
  if (!fs.existsSync(UPLOAD_META_FILE)) return {};
  try {
    return JSON.parse(fs.readFileSync(UPLOAD_META_FILE, "utf8")) as Record<string, JsonRecord>;
  } catch {
    return {};
  }
}

function saveUploadMeta(meta: Record<string, JsonRecord>) {
  fs.mkdirSync(USER_DATA_DIR, { recursive: true });
  fs.writeFileSync(UPLOAD_META_FILE, JSON.stringify(meta, null, 2), "utf8");
}

function cleanUploadMetaValue(value: unknown, maxLength = 180): string {
  return String(value || "").trim().slice(0, maxLength);
}

function applyUploadMeta(item: JsonRecord, meta: Record<string, JsonRecord>): JsonRecord {
  const ownMeta = meta[String(item.id || "")] || {};
  return {
    ...item,
    displayName: ownMeta.displayName || item.filename,
    subject: ownMeta.subject || "",
    note: ownMeta.note || "",
  };
}

function inferUploadSubject(filename: string, text: string): string {
  const haystack = `${filename}\n${text}`.toLowerCase();
  if (/408|计算机|数据结构|组成原理|操作系统|计算机网络/i.test(haystack)) return "408计算机";
  if (/英语|english/i.test(haystack)) return "英语";
  if (/数学|高等数学|线性代数|概率/i.test(haystack)) return "数学";
  if (/政治|马克思|毛中特|史纲|思修/i.test(haystack)) return "政治";
  return "用户上传";
}

function extractedMarkdownNameForPdf(storedPdfName: string): string {
  return `${path.basename(storedPdfName, path.extname(storedPdfName))}.extracted.md`;
}

function extractedMarkdownPathForPdf(storedPdfName: string): string {
  return path.join(USER_DATA_DIR, extractedMarkdownNameForPdf(storedPdfName));
}

function extractionStatusPathForPdf(storedPdfName: string): string {
  return path.join(
    USER_DATA_DIR,
    `${path.basename(storedPdfName, path.extname(storedPdfName))}.extract-status.json`,
  );
}

function resolveUserDataSourcePath(sourcePath: string): string {
  const normalized = String(sourcePath || "").replace(/\\/g, "/");
  const fullPath = path.resolve(DATA_ROOT, normalized);
  const userRoot = path.resolve(USER_DATA_DIR);
  if (!fullPath.startsWith(`${userRoot}${path.sep}`) && fullPath !== userRoot) {
    throw new Error("只能管理用户上传资料");
  }
  return fullPath;
}

function setHtmlComment(text: string, key: string, value: string): string {
  const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`<!--\\s*${escapedKey}:\\s*[^>]*?-->`, "i");
  const line = `<!-- ${key}: ${value} -->`;
  if (pattern.test(text)) return text.replace(pattern, line);
  const lines = text.split(/\r?\n/);
  const titleIndex = lines.findIndex((item) => item.startsWith("# "));
  lines.splice(titleIndex >= 0 ? titleIndex + 1 : 0, 0, line);
  return lines.join("\n");
}

function updateMarkdownMetadata(sourcePath: string, meta: JsonRecord) {
  if (!sourcePath || !sourcePath.toLowerCase().endsWith(".md")) return;
  const fullPath = resolveUserDataSourcePath(sourcePath);
  if (!fs.existsSync(fullPath)) return;
  let text = fs.readFileSync(fullPath, "utf8");
  if (meta.displayName) {
    const title = `# ${meta.displayName}`;
    text = /^# .+$/m.test(text) ? text.replace(/^# .+$/m, title) : `${title}\n\n${text}`;
  }
  if (meta.subject) {
    text = setHtmlComment(text, "subject", String(meta.subject));
  }
  fs.writeFileSync(fullPath, text, "utf8");
}

function writePdfExtractionStatus(storedPdfName: string, status: JsonRecord) {
  fs.mkdirSync(USER_DATA_DIR, { recursive: true });
  fs.writeFileSync(
    extractionStatusPathForPdf(storedPdfName),
    JSON.stringify(
      {
        originalPdf: storedPdfName,
        updatedAt: new Date().toISOString(),
        ...status,
      },
      null,
      2,
    ),
    "utf8",
  );
}

function markdownFromPdfText({
  filename,
  storedPdfName,
  text,
}: {
  filename: string;
  storedPdfName: string;
  text: string;
}): string {
  const title = path.basename(filename, path.extname(filename));
  const subject = inferUploadSubject(filename, text);
  return [
    `# ${title}`,
    "",
    "<!-- source: pdf -->",
    `<!-- original_pdf: ${storedPdfName} -->`,
    `<!-- subject: ${subject} -->`,
    "",
    text,
  ].join("\n");
}

function questionCountForSource(sourcePath: string): number {
  return questionBank.questions.filter((question: JsonRecord) => question.sourcePath === sourcePath).length;
}

function writeExtractedPdfMarkdown({
  filename,
  storedPdfName,
  pdfPath,
}: {
  filename: string;
  storedPdfName: string;
  pdfPath: string;
}) {
  fs.mkdirSync(USER_DATA_DIR, { recursive: true });
  const markdownPath = extractedMarkdownPathForPdf(storedPdfName);
  const sourcePath = path.relative(DATA_ROOT, markdownPath).replace(/\\/g, "/");
  let text = "";
  try {
    text = normalizeExtractedText(extractPdfText(pdfPath));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    writePdfExtractionStatus(storedPdfName, {
      ok: false,
      status: "PDF 文字层提取失败，需要 OCR",
      error: message,
    });
    return {
      ok: false,
      reloaded: false,
      sourcePath,
      questionCount: 0,
      error: `PDF 文字层提取失败：${message}`,
    };
  }

  if (text.length < 80) {
    writePdfExtractionStatus(storedPdfName, {
      ok: false,
      status: "PDF 没有可用文字层，需要 OCR",
      error: "PDF text layer is empty",
    });
    return {
      ok: false,
      reloaded: false,
      sourcePath,
      questionCount: 0,
      error: "PDF 没有可用文字层，需要先做 OCR 后再入库。",
    };
  }

  fs.writeFileSync(markdownPath, markdownFromPdfText({ filename, storedPdfName, text }), "utf8");
  writePdfExtractionStatus(storedPdfName, {
    ok: true,
    status: "PDF 已自动解析",
    sourcePath,
  });
  reloadQuestionBank();
  return {
    ok: true,
    reloaded: true,
    sourcePath,
    questionCount: questionCountForSource(sourcePath),
    markdownPath,
  };
}

function ensurePdfExtractions() {
  if (!fs.existsSync(UPLOAD_DIR)) return;
  for (const name of fs.readdirSync(UPLOAD_DIR)) {
    const pdfPath = path.join(UPLOAD_DIR, name);
    if (!fs.statSync(pdfPath).isFile()) continue;
    if (path.extname(name).toLowerCase() !== ".pdf") continue;
    const markdownPath = extractedMarkdownPathForPdf(name);
    if (fs.existsSync(markdownPath)) continue;
    if (fs.existsSync(extractionStatusPathForPdf(name))) continue;
    writeExtractedPdfMarkdown({ filename: name, storedPdfName: name, pdfPath });
  }
}

function getUploadSourceItems(): JsonRecord[] {
  ensurePdfExtractions();
  const uploadMeta = loadUploadMeta();

  const questionCounts = new Map<string, number>();
  for (const question of questionBank.questions as JsonRecord[]) {
    if (question.sourceKind !== "upload") continue;
    const sourcePath = String(question.sourcePath || "");
    questionCounts.set(sourcePath, (questionCounts.get(sourcePath) || 0) + 1);
  }

  const extractedByPdf = new Map<string, JsonRecord>();
  const statusByPdf = new Map<string, JsonRecord>();
  const items: JsonRecord[] = [];
  if (fs.existsSync(USER_DATA_DIR)) {
    for (const name of fs.readdirSync(USER_DATA_DIR)) {
      const fullPath = path.join(USER_DATA_DIR, name);
      if (!fs.statSync(fullPath).isFile()) continue;
      const ext = path.extname(name).toLowerCase();
      if (name.endsWith(".extract-status.json") || name === "upload-meta.json") {
        try {
          const status = JSON.parse(fs.readFileSync(fullPath, "utf8"));
          if (status.originalPdf) statusByPdf.set(status.originalPdf, status);
        } catch {
          // Ignore malformed extraction status files.
        }
        continue;
      }
      if (![".md", ".txt"].includes(ext)) continue;
      const sourcePath = path.relative(DATA_ROOT, fullPath).replace(/\\/g, "/");
      const questionCount = questionCounts.get(sourcePath) || 0;
      const text = ext === ".md" ? fs.readFileSync(fullPath, "utf8") : "";
      const originalPdfMatch = text.match(/<!--\s*original_pdf:\s*([^>]+?)\s*-->/i);
      if (originalPdfMatch) {
        extractedByPdf.set(originalPdfMatch[1].trim(), {
          sourcePath,
          questionCount,
        });
        continue;
      }
      items.push({
        id: sourcePath,
        filename: name,
        sourcePath,
        ext,
        kind: "text",
        questionCount,
        available: questionCount > 0,
        status: questionCount > 0 ? "已解析，可练习" : "已上传，等待题目解析",
      });
    }
  }
  if (fs.existsSync(UPLOAD_DIR)) {
    for (const name of fs.readdirSync(UPLOAD_DIR)) {
      const fullPath = path.join(UPLOAD_DIR, name);
      if (!fs.statSync(fullPath).isFile()) continue;
      if (path.extname(name).toLowerCase() !== ".pdf") continue;
      const extracted = extractedByPdf.get(name);
      const extractionStatus = statusByPdf.get(name);
      const questionCount = Number(extracted?.questionCount || 0);
      items.push({
        id: `pdf:${name}`,
        filename: name,
        sourcePath: String(extracted?.sourcePath || ""),
        ext: ".pdf",
        kind: "pdf",
        questionCount,
        available: questionCount > 0,
        status: extracted
          ? questionCount > 0
            ? "PDF 已自动解析"
            : "PDF 已提取文字，未识别到题目"
          : String(extractionStatus?.status || "PDF 待 OCR/解析"),
      });
    }
  }
  return items
    .map((item) => applyUploadMeta(item, uploadMeta))
    .sort((left, right) =>
      String(right.filename || "").localeCompare(String(left.filename || ""), "zh-Hans-CN"),
    );
}

function updateUploadedMaterial(payload: JsonRecord): JsonRecord | null {
  const id = String(payload.id || "").trim();
  if (!id) throw new Error("缺少资料 ID");
  const item = getUploadSourceItems().find((candidate) => candidate.id === id);
  if (!item) return null;

  const displayName = cleanUploadMetaValue(payload.displayName || payload.display_name, 160) || String(item.filename || "");
  const subject = cleanUploadMetaValue(payload.subject, 80);
  const note = cleanUploadMetaValue(payload.note, 500);
  const nextMeta = { displayName, subject, note };
  const uploadMeta = loadUploadMeta();
  uploadMeta[id] = nextMeta;
  saveUploadMeta(uploadMeta);

  if (item.sourcePath) {
    updateMarkdownMetadata(String(item.sourcePath), nextMeta);
    reloadQuestionBank();
  }

  return getUploadSourceItems().find((candidate) => candidate.id === id) || null;
}

function deleteUploadedMaterial(payload: JsonRecord): JsonRecord | null {
  const id = String(payload.id || "").trim();
  if (!id) throw new Error("缺少资料 ID");
  const item = getUploadSourceItems().find((candidate) => candidate.id === id);
  if (!item) return null;

  const uploadMeta = loadUploadMeta();
  delete uploadMeta[id];

  if (id.startsWith("pdf:")) {
    const filename = id.slice(4);
    if (path.basename(filename) !== filename) throw new Error("资料 ID 不合法");
    const pdfPath = path.resolve(UPLOAD_DIR, filename);
    const uploadRoot = path.resolve(UPLOAD_DIR);
    if (!pdfPath.startsWith(`${uploadRoot}${path.sep}`)) throw new Error("资料路径不合法");
    if (fs.existsSync(pdfPath)) fs.unlinkSync(pdfPath);
    const markdownPath = extractedMarkdownPathForPdf(filename);
    if (fs.existsSync(markdownPath)) fs.unlinkSync(markdownPath);
    const statusPath = extractionStatusPathForPdf(filename);
    if (fs.existsSync(statusPath)) fs.unlinkSync(statusPath);
    if (item.sourcePath) delete uploadMeta[String(item.sourcePath)];
  } else {
    const fullPath = resolveUserDataSourcePath(id);
    if (fs.existsSync(fullPath)) fs.unlinkSync(fullPath);
  }

  saveUploadMeta(uploadMeta);
  reloadQuestionBank();
  return { id };
}

function listAnnotationItems(userId: string) {
  const annotations = stateStore.getAnnotations(userId);
  return Object.entries(annotations)
    .filter(([, annotation]) => {
      const item = annotation as JsonRecord;
      return (
        item &&
        (item.highlight ||
          item.underline ||
          item.star ||
          String(item.note || "").trim())
      );
    })
    .map(([questionId, annotation]) => ({
      question_id: questionId,
      annotation,
      question: assembler.getQuestion(questionId),
    }))
    .sort((left, right) =>
      String((right.annotation as JsonRecord).updatedAt || "").localeCompare(
        String((left.annotation as JsonRecord).updatedAt || ""),
      ),
    );
}

export const paperAssemblyService = {
  defaultUserId: DEFAULT_USER_ID as string,

  health() {
    return {
      ok: true,
      dataRoot: DATA_ROOT,
      parsedFiles: questionBank.files.length,
      questionCount: questionBank.questions.length,
      parseErrors: questionBank.errors,
      stateFile: STATE_FILE,
    };
  },

  modules() {
    return { modules: SUBJECT_PLAN_MATH.modules, plan: SUBJECT_PLAN_MATH };
  },

  subjects() {
    return { items: SUBJECTS };
  },

  questionTypes() {
    return { modules: assembler.questionTypeTree() };
  },

  originalPapers() {
    return { items: assembler.originalPapers() };
  },

  uploads() {
    return { items: getUploadSourceItems() };
  },

  conversionStatus() {
    return {
      ok: true,
      status: "ready",
      runtime: {
        ok: true,
        status: "ready",
        engine: process.env.OPENAI_API_KEY ? "markitdown-ocr" : "markitdown",
        message: "PDF uploads are converted automatically.",
      },
      system: {
        status: "not_configured",
        conversionStatus: "not_configured",
        message: "System PDF batch conversion is not configured in the integrated app.",
      },
      pendingSystemPdfCount: 0,
      lastLog: "",
    };
  },

  convertSystemExams() {
    return {
      ok: false,
      status: "not_configured",
      conversionStatus: "not_configured",
      message: "System PDF batch conversion is not configured in the integrated app.",
    };
  },

  updateUploadedMaterial(payload: JsonRecord) {
    return updateUploadedMaterial(payload);
  },

  deleteUploadedMaterial(payload: JsonRecord) {
    return deleteUploadedMaterial(payload);
  },

  saveUploadedMaterial(file: UploadedFile) {
    if (!file.filename) throw new Error("请选择文件");
    const ext = path.extname(file.filename).toLowerCase();
    const allowed = new Set([".pdf", ".md", ".txt"]);
    if (!allowed.has(ext)) throw new Error("仅支持 PDF、Markdown 或 TXT 文件");

    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const safeName = file.filename.replace(/[^\w.\-\u4e00-\u9fa5]/g, "_");
    const targetDir = ext === ".pdf" ? UPLOAD_DIR : USER_DATA_DIR;
    fs.mkdirSync(targetDir, { recursive: true });
    const storedName = `${stamp}-${safeName}`;
    const targetPath = path.join(targetDir, storedName);
    fs.writeFileSync(targetPath, file.buffer);

    if (ext === ".pdf") {
      const parsed = writeExtractedPdfMarkdown({
        filename: file.filename,
        storedPdfName: storedName,
        pdfPath: targetPath,
      });
      return {
        filename: file.filename,
        storedPath: targetPath,
        sourcePath: parsed.sourcePath || "",
        questionCount: parsed.questionCount || 0,
        reloaded: parsed.reloaded,
        message: parsed.ok
          ? `已上传 ${file.filename}，并自动提取文字入库；当前识别到 ${parsed.questionCount || 0} 道题。`
          : `已上传 ${file.filename}，但${parsed.error}`,
      };
    }

    reloadQuestionBank();
    return {
      filename: file.filename,
      storedPath: targetPath,
      sourcePath: path.relative(DATA_ROOT, targetPath).replace(/\\/g, "/"),
      reloaded: true,
      message: `已上传 ${file.filename}，并自动并入用户题库。`,
    };
  },

  assemble(payload: JsonRecord, userId: string) {
    return assembler.assemble({ ...payload, user_id: String(payload.user_id || userId) });
  },

  wrongQuestions(userId: string) {
    return { items: stateStore.getWrongQuestions(userId) };
  },

  wrongQuestionSummary(userId: string) {
    return stateStore.summarizeWrongQuestions(userId);
  },

  addWrongQuestion(payload: JsonRecord, userId: string) {
    const question = payload.question_id
      ? assembler.getQuestion(String(payload.question_id))
      : payload.question;
    if (!question) return null;
    const owner = String(payload.user_id || userId);
    const item = stateStore.addWrongQuestion(owner, question, payload);
    return { item, summary: stateStore.summarizeWrongQuestions(owner) };
  },

  updateWrongReason(wrongId: string, payload: JsonRecord, userId: string) {
    return stateStore.updateWrongQuestion(String(payload.user_id || userId), wrongId, {
      manual_wrong_reason: payload.manual_wrong_reason || payload.wrong_reason || "待分析",
    });
  },

  recordRetry(wrongId: string, payload: JsonRecord, userId: string) {
    return stateStore.recordRetry(String(payload.user_id || userId), wrongId);
  },

  updateAnnotation(questionId: string, payload: JsonRecord, userId: string) {
    return {
      annotation: stateStore.updateAnnotation(
        String(payload.user_id || userId),
        questionId,
        (payload.annotation as JsonRecord) || {},
      ),
    };
  },

  annotations(userId: string) {
    return { annotations: stateStore.getAnnotations(userId) };
  },

  annotationItems(userId: string) {
    return {
      annotations: stateStore.getAnnotations(userId),
      items: listAnnotationItems(userId),
    };
  },
};
