import type { TFunction } from "i18next";
import type { KnowledgeUploadPolicy } from "@/lib/knowledge-api";

export const DEFAULT_UPLOAD_POLICY: KnowledgeUploadPolicy = {
  extensions: [],
  accept: "",
  max_file_size_bytes: 100 * 1024 * 1024,
  max_pdf_size_bytes: 50 * 1024 * 1024,
};

export interface ProgressInfo {
  task_id?: string;
  stage?: string;
  message?: string;
  current?: number;
  total?: number;
  percent?: number;
  progress_percent?: number;
}

export interface IndexVersion {
  signature?: string;
  model?: string;
  dimension?: number;
  binding?: string;
  created_at?: string;
  ready?: boolean;
  legacy?: boolean;
}

export interface KnowledgeBase {
  name: string;
  is_default?: boolean;
  status?: string;
  path?: string;
  metadata?: {
    created_at?: string;
    last_updated?: string;
    rag_provider?: string;
    needs_reindex?: boolean;
    display_name?: string;
    short_name?: string;
    source_label?: string;
    source_summary?: string;
    source_type?: "knowledge" | "question" | string;
    source_id?: string;
    debug_name?: string;
    embedding_model?: string;
    embedding_dim?: number;
    embedding_mismatch?: boolean;
  };
  progress?: ProgressInfo;
  statistics?: {
    raw_documents?: number;
    images?: number;
    content_lists?: number;
    rag_provider?: string;
    rag_initialized?: boolean;
    needs_reindex?: boolean;
    status?: string;
    progress?: ProgressInfo;
    index_versions?: IndexVersion[];
    active_signature?: string | null;
    active_match?: boolean;
  };
}

export interface ValidatedSelectionFile {
  id: string;
  file: File;
  extension: string;
  sizeLabel: string;
  valid: boolean;
  error: string | null;
}

export interface ValidatedFileSelection {
  items: ValidatedSelectionFile[];
  validFiles: File[];
  invalidFiles: ValidatedSelectionFile[];
  totalBytes: number;
}

export const formatFileSize = (bytes: number): string => {
  if (bytes >= 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
};

export const getFileExtension = (filename: string): string => {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLowerCase() : "";
};

export const selectionFileId = (file: File): string =>
  `${file.name}:${file.size}:${file.lastModified}`;

export const mergeSelectedFiles = (existing: File[], incoming: File[]): File[] => {
  const merged = new Map<string, File>();
  [...existing, ...incoming].forEach((file) => {
    merged.set(selectionFileId(file), file);
  });
  return Array.from(merged.values());
};

const parseKnowledgeTimestamp = (value?: string): Date | null => {
  if (!value) return null;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

export const formatKnowledgeTimestamp = (value?: string): string | null => {
  const parsed = parseKnowledgeTimestamp(value);
  return parsed ? parsed.toLocaleString() : value || null;
};

type KnowledgeBaseLike = {
  name: string;
  metadata?: Record<string, unknown> | KnowledgeBase["metadata"] | null;
};

const metadataString = (value: unknown): string | null => {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
};

const KAOYAN_SEPARATOR = "\uff5c";
const QUESTION_LABEL = "\u9898\u76ee\u89e3\u6790";
const KNOWLEDGE_LABEL = "\u77e5\u8bc6\u70b9\u89e3\u6790";
const QUESTION_PREFIX = "\u9898\u76ee";
const KNOWLEDGE_PREFIX = "\u77e5\u8bc6\u70b9";

const GENERIC_KAOYAN_TEXT = new Set([
  "\u8003\u7814\u6570\u5b66",
  "\u6570\u5b66",
  "\u9ad8\u7b49\u6570\u5b66",
  "\u9ad8\u6570",
  "\u8003\u7814\u6570\u5b66\u9898",
  "\u9ad8\u6570\u77e5\u8bc6\u70b9",
]);

const normalizeDisplayText = (value: string | null): string | null => {
  if (!value) return null;
  return value.replace(/\s+/g, "").trim() || null;
};

const kaoyanScopedKind = (kb: KnowledgeBaseLike): "question" | "knowledge" | null => {
  const sourceType = metadataString(kb.metadata?.source_type);
  if (sourceType === "question" || sourceType === "knowledge") return sourceType;
  if (/^kaoyan_(?:.*_)?question_/.test(kb.name)) return "question";
  if (/^kaoyan_(?:.*_)?knowledge_/.test(kb.name)) return "knowledge";
  return null;
};

const kaoyanHashToken = (name: string): string | null => {
  const match = name.match(/^kaoyan_(?:.*_)?(?:question|knowledge)_([A-Za-z0-9]+)$/);
  return match?.[1]?.slice(0, 6) ?? null;
};

const isGenericKaoyanName = (value: string | null): boolean => {
  const normalized = normalizeDisplayText(value);
  if (!normalized) return true;
  const withoutPrefix = normalized
    .replace(new RegExp(`^${QUESTION_LABEL}${KAOYAN_SEPARATOR}?`), "")
    .replace(new RegExp(`^${KNOWLEDGE_LABEL}${KAOYAN_SEPARATOR}?`), "")
    .replace(new RegExp(`^${QUESTION_PREFIX}${KAOYAN_SEPARATOR}?`), "")
    .replace(new RegExp(`^${KNOWLEDGE_PREFIX}${KAOYAN_SEPARATOR}?`), "");
  return GENERIC_KAOYAN_TEXT.has(withoutPrefix) || GENERIC_KAOYAN_TEXT.has(normalized);
};

const compactSourceId = (sourceId: string | null): string | null => {
  if (!sourceId) return null;
  if (sourceId.length <= 18) return sourceId;
  return `${sourceId.slice(0, 10)}...${sourceId.slice(-4)}`;
};

const kaoyanFallbackDisplayName = (kb: KnowledgeBaseLike): string | null => {
  const kind = kaoyanScopedKind(kb);
  if (!kind) return null;

  const sourceId = compactSourceId(metadataString(kb.metadata?.source_id));
  const sourceSummary = metadataString(kb.metadata?.source_summary);
  const shortName = metadataString(kb.metadata?.short_name);
  const token = kaoyanHashToken(kb.name);
  const fallbackId = sourceId ?? (token ? `#${token}` : null);
  const summary = !isGenericKaoyanName(sourceSummary)
    ? sourceSummary
    : !isGenericKaoyanName(shortName)
      ? shortName
      : null;

  const parts = kind === "question" ? [QUESTION_LABEL] : [KNOWLEDGE_LABEL];
  if (fallbackId) parts.push(fallbackId);
  if (summary && summary !== fallbackId) parts.push(summary);
  return parts.join(KAOYAN_SEPARATOR);
};

export const getKnowledgeBaseDisplayName = (kb: KnowledgeBaseLike): string => {
  const displayName = metadataString(kb.metadata?.display_name);
  if (displayName && !isGenericKaoyanName(displayName)) return displayName;
  return kaoyanFallbackDisplayName(kb) ?? displayName ?? kb.name;
};

export const getKnowledgeBaseShortName = (kb: KnowledgeBaseLike): string => {
  const shortName = metadataString(kb.metadata?.short_name);
  if (shortName && !isGenericKaoyanName(shortName)) return shortName;
  return kaoyanFallbackDisplayName(kb) ?? getKnowledgeBaseDisplayName(kb);
};
export const getKnowledgeBaseDebugName = (kb: KnowledgeBaseLike): string | null => {
  const debug = metadataString(kb.metadata?.debug_name) ?? kb.name;
  const display = getKnowledgeBaseDisplayName(kb);
  return debug !== display ? debug : null;
};

export const resolveKbStatus = (kb: KnowledgeBase): string =>
  kb.status ?? kb.statistics?.status ?? "unknown";

export const kbNeedsReindex = (kb: KnowledgeBase): boolean =>
  Boolean(kb.statistics?.needs_reindex) ||
  resolveKbStatus(kb) === "needs_reindex";

export const kbIsUploadable = (kb: KnowledgeBase): boolean =>
  resolveKbStatus(kb) === "ready" && !kbNeedsReindex(kb);

const LIVE_PROGRESS_STAGES = new Set([
  "initializing",
  "starting",
  "processing_documents",
  "processing_file",
  "extracting_items",
]);

export const kbHasLiveProgress = (kb: KnowledgeBase): boolean => {
  const status = resolveKbStatus(kb);
  if (status === "ready" || status === "error" || status === "needs_reindex") {
    return false;
  }
  const stage = kb.progress?.stage;
  if (!stage) return false;
  if (stage === "completed" || stage === "error") return false;
  return LIVE_PROGRESS_STAGES.has(stage);
};

export const resolveProgressPercent = (progress?: ProgressInfo): number => {
  const directPercent = progress?.progress_percent ?? progress?.percent;
  if (typeof directPercent === "number") return directPercent;

  const current = progress?.current ?? 0;
  const total = progress?.total ?? 0;
  if (!current || !total) return 0;
  return Math.round((current / total) * 100);
};

export function validateFiles(
  files: File[],
  uploadPolicy: KnowledgeUploadPolicy,
  t: TFunction,
): ValidatedFileSelection {
  const allowedExtensions = new Set(
    uploadPolicy.extensions.map((ext) => ext.toLowerCase()),
  );

  const items = files.map((file) => {
    const extension = getFileExtension(file.name);
    let error: string | null = null;

    if (allowedExtensions.size > 0 && !allowedExtensions.has(extension)) {
      error = t("Unsupported file type");
    } else if (
      extension === ".pdf" &&
      file.size > uploadPolicy.max_pdf_size_bytes
    ) {
      error = t("PDF files must be smaller than {{size}}.", {
        size: formatFileSize(uploadPolicy.max_pdf_size_bytes),
      });
    } else if (file.size > uploadPolicy.max_file_size_bytes) {
      error = t("This file exceeds the maximum size of {{size}}.", {
        size: formatFileSize(uploadPolicy.max_file_size_bytes),
      });
    }

    return {
      id: selectionFileId(file),
      file,
      extension: extension || t("No extension"),
      sizeLabel: formatFileSize(file.size),
      valid: !error,
      error,
    };
  });

  return {
    items,
    validFiles: items.filter((item) => item.valid).map((item) => item.file),
    invalidFiles: items.filter((item) => !item.valid),
    totalBytes: files.reduce((total, file) => total + file.size, 0),
  };
}
