"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { useKnowledgeBases } from "@/hooks/useKnowledgeBases";
import KnowledgeBaseList from "./KnowledgeBaseList";
import KnowledgeBaseDetail from "./KnowledgeBaseDetail";
import CreateKbModal from "./CreateKbModal";

export default function KnowledgePage() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialKb = searchParams.get("kb");

  const {
    kbs,
    providers,
    uploadPolicy,
    loading,
    error,
    setError,
    tasksByKb,
    historyByKb,
    clearHistory,
    refresh,
    createKb,
    uploadFiles,
    setDefault,
    reindex,
    deleteKb,
  } = useKnowledgeBases();

  const [explicitSelection, setExplicitSelection] = useState<string | null>(
    initialKb,
  );
  const [createOpen, setCreateOpen] = useState(false);

  // Derive the effective selection: respect the user's pick if it still
  // exists, otherwise fall back to the default KB (or the first one). No
  // useEffect chains — keeps state out of effects.
  const selectedKbName = useMemo<string | null>(() => {
    if (
      explicitSelection &&
      kbs.some((kb) => kb.name === explicitSelection)
    ) {
      return explicitSelection;
    }
    if (!kbs.length) return null;
    return kbs.find((kb) => kb.is_default)?.name ?? kbs[0].name;
  }, [explicitSelection, kbs]);

  const selectedKb = useMemo(
    () => kbs.find((kb) => kb.name === selectedKbName) ?? null,
    [kbs, selectedKbName],
  );

  // Keep ?kb=… in sync with the effective selection so deep links work.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const current = searchParams.get("kb");
    if (current === (selectedKbName ?? null)) return;
    const params = new URLSearchParams(Array.from(searchParams.entries()));
    if (selectedKbName) {
      params.set("kb", selectedKbName);
    } else {
      params.delete("kb");
    }
    const search = params.toString();
    router.replace(search ? `?${search}` : "?", { scroll: false });
  }, [router, searchParams, selectedKbName]);

  const handleCreate = useCallback(
    async (params: { name: string; provider: string; files: File[] }) => {
      try {
        await createKb(params);
        setExplicitSelection(params.name);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        throw err;
      }
    },
    [createKb, setError],
  );

  const handleSetDefault = useCallback(
    async (name: string) => {
      try {
        await setDefault(name);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [setDefault, setError],
  );

  const handleDelete = useCallback(
    async (name: string) => {
      if (
        !window.confirm(
          t('Delete knowledge base "{{name}}"?', { name }),
        )
      ) {
        return;
      }
      try {
        await deleteKb(name);
        if (explicitSelection === name) setExplicitSelection(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [deleteKb, explicitSelection, setError, t],
  );

  const handleUpload = useCallback(
    async (kbName: string, files: File[]) => {
      try {
        await uploadFiles(kbName, files);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        throw err;
      }
    },
    [setError, uploadFiles],
  );

  const handleReindex = useCallback(
    async (kbName: string) => {
      try {
        await reindex(kbName);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [reindex, setError],
  );

  return (
    <div className="flex h-full flex-col bg-[var(--background)]">
      {error && (
        <div className="flex items-center justify-between gap-3 border-b border-red-200 bg-red-50 px-4 py-2 text-[12.5px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          <span className="truncate">{error}</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void refresh({ force: true })}
              className="rounded-md border border-red-300 px-2 py-0.5 text-[11.5px] font-medium hover:bg-red-100 dark:border-red-900 dark:hover:bg-red-950/50"
            >
              {t("Retry")}
            </button>
            <button
              type="button"
              onClick={() => setError(null)}
              className="rounded-md px-2 py-0.5 text-[11.5px] font-medium hover:bg-red-100 dark:hover:bg-red-950/50"
            >
              {t("Dismiss")}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <KnowledgeBaseList
            kbs={kbs}
            selectedKbName={selectedKbName}
            onSelect={setExplicitSelection}
            onCreate={() => setCreateOpen(true)}
            onSetDefault={handleSetDefault}
            onDelete={handleDelete}
            tasksByKb={tasksByKb}
          />
          <KnowledgeBaseDetail
            kb={selectedKb}
            uploadPolicy={uploadPolicy}
            task={selectedKb ? tasksByKb[selectedKb.name] : undefined}
            history={selectedKb ? (historyByKb[selectedKb.name] ?? []) : []}
            onCreate={() => setCreateOpen(true)}
            onUpload={handleUpload}
            onReindex={handleReindex}
            onSetDefault={handleSetDefault}
            onDelete={handleDelete}
            onClearHistory={clearHistory}
          />
        </div>
      )}

      <CreateKbModal
        isOpen={createOpen}
        onClose={() => setCreateOpen(false)}
        providers={providers}
        uploadPolicy={uploadPolicy}
        onCreate={handleCreate}
      />
    </div>
  );
}
