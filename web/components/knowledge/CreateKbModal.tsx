"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Plus } from "lucide-react";
import Modal from "@/components/common/Modal";
import type { KnowledgeUploadPolicy, RagProviderSummary } from "@/lib/knowledge-api";
import { validateFiles } from "@/lib/knowledge-helpers";
import FileDropZone from "./FileDropZone";

interface CreateKbModalProps {
  isOpen: boolean;
  onClose: () => void;
  providers: RagProviderSummary[];
  uploadPolicy: KnowledgeUploadPolicy;
  onCreate: (params: {
    name: string;
    provider: string;
    files: File[];
  }) => Promise<void>;
}

export default function CreateKbModal({
  isOpen,
  onClose,
  providers,
  uploadPolicy,
  onCreate,
}: CreateKbModalProps) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("llamaindex");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setName("");
      setFiles([]);
      setError(null);
      setProvider(providers[0]?.id || "llamaindex");
    }
  }, [isOpen, providers]);

  const selection = validateFiles(files, uploadPolicy, t);
  const trimmed = name.trim();
  const canSubmit =
    !submitting &&
    trimmed.length > 0 &&
    selection.validFiles.length > 0 &&
    selection.invalidFiles.length === 0;

  const handleCreate = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await onCreate({
        name: trimmed,
        provider,
        files: selection.validFiles,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={submitting ? () => {} : onClose}
      title={t("Create knowledge base")}
      titleIcon={<Plus size={16} />}
      width="lg"
      closeOnBackdrop={!submitting}
      closeOnEscape={!submitting}
      footer={
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md px-3 py-1.5 text-[12.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
          >
            {t("Cancel")}
          </button>
          <button
            type="button"
            onClick={() => void handleCreate()}
            disabled={!canSubmit}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus size={14} />
            )}
            {t("Create")}
          </button>
        </div>
      }
    >
      <div className="space-y-4 px-5 py-4">
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Knowledge base name")}
          </label>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoFocus
            disabled={submitting}
            placeholder={t("e.g. project-papers")}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
          />
        </div>

        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("RAG provider")}
          </label>
          <select
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
            disabled={submitting}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none disabled:opacity-50"
          >
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-2 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Initial documents")}
          </label>
          <FileDropZone
            files={files}
            onChange={setFiles}
            uploadPolicy={uploadPolicy}
            disabled={submitting}
          />
        </div>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
              {error}
            </pre>
          </div>
        )}
      </div>
    </Modal>
  );
}
