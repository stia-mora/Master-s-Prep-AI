"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Upload } from "lucide-react";
import type { KnowledgeUploadPolicy } from "@/lib/knowledge-api";
import {
  kbIsUploadable,
  kbNeedsReindex,
  resolveKbStatus,
  resolveProgressPercent,
  validateFiles,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";
import type { TaskState } from "@/hooks/useKnowledgeProgress";
import type { HistoryEntry } from "@/hooks/useKnowledgeHistory";
import FileDropZone from "./FileDropZone";
import KbUpdateHistory from "./KbUpdateHistory";

const ProcessLogs = dynamic(() => import("@/components/common/ProcessLogs"), {
  ssr: false,
});

interface KbDocumentsSectionProps {
  kb: KnowledgeBase;
  uploadPolicy: KnowledgeUploadPolicy;
  task?: TaskState;
  history: HistoryEntry[];
  onClearHistory: () => void;
  onUpload: (files: File[]) => Promise<void>;
}

/**
 * The "Add documents" tab. Focused on the incremental-upload flow: drop
 * zone, upload button, live process logs while a task runs, and a list of
 * past update events. The file list and preview live under the separate
 * "Files" tab to keep each surface single-purpose.
 */
export default function KbDocumentsSection({
  kb,
  uploadPolicy,
  task,
  history,
  onClearHistory,
  onUpload,
}: KbDocumentsSectionProps) {
  const { t } = useTranslation();
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const uploadable = kbIsUploadable(kb);
  const needsReindex = kbNeedsReindex(kb);
  const status = resolveKbStatus(kb);

  const blockedReason = !uploadable
    ? needsReindex
      ? t(
          "This knowledge base is in legacy index format and needs reindex before upload.",
        )
      : status !== "ready"
        ? t(
            "This knowledge base is currently {{status}} and cannot accept uploads yet.",
            { status: status.replaceAll("_", " ") },
          )
        : null
    : null;

  const selection = validateFiles(files, uploadPolicy, t);
  const isUploadingHere = task?.kind === "upload" && task.executing;
  const canSubmit =
    uploadable &&
    selection.validFiles.length > 0 &&
    selection.invalidFiles.length === 0 &&
    !submitting &&
    !isUploadingHere;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await onUpload(selection.validFiles);
      setFiles([]);
    } finally {
      setSubmitting(false);
    }
  };

  const percent = resolveProgressPercent(kb.progress);

  return (
    <div className="space-y-5">
      <div>
        <div className="text-[13px] font-medium text-[var(--foreground)]">
          {t("Add documents")}
        </div>
        <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
          {t(
            "Drop files here to add them to this knowledge base. New files are indexed against the active embedding model.",
          )}
        </p>
      </div>

      {blockedReason && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
          {blockedReason}
        </div>
      )}

      <FileDropZone
        files={files}
        onChange={setFiles}
        uploadPolicy={uploadPolicy}
        disabled={!uploadable || isUploadingHere}
      />

      <div className="flex items-center justify-end">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting || isUploadingHere ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Upload size={14} />
          )}
          {t("Upload")}
        </button>
      </div>

      {(task?.kind === "upload" || task?.kind === "create") &&
        (task.taskId || task.logs.length > 0 || task.executing) && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[11px] text-[var(--muted-foreground)]">
              <span>
                {task.label}
                {task.taskId ? ` · ${task.taskId}` : ""}
              </span>
              {task.executing && percent > 0 && (
                <span className="font-medium text-[var(--foreground)]">
                  {percent}%
                </span>
              )}
            </div>
            <ProcessLogs
              logs={task.logs}
              executing={task.executing}
              title={
                task.kind === "create"
                  ? t("Create Process")
                  : t("Upload Process")
              }
            />
            {task.executing && (
              <div className="h-1.5 overflow-hidden rounded-full bg-[var(--border)]/70">
                <div
                  className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
                  style={{ width: `${Math.max(percent, 4)}%` }}
                />
              </div>
            )}
            {task.error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
                  {task.error}
                </pre>
              </div>
            )}
          </div>
        )}

      <KbUpdateHistory entries={history} onClear={onClearHistory} />
    </div>
  );
}
