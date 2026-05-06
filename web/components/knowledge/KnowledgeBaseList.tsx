"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Database,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Star,
} from "lucide-react";
import {
  getKnowledgeBaseDisplayName,
  getKnowledgeBaseShortName,
  kbHasLiveProgress,
  kbNeedsReindex,
  resolveKbStatus,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";
import type { TaskState } from "@/hooks/useKnowledgeProgress";
import { useCollapsiblePanel } from "@/hooks/useCollapsiblePanel";
import KnowledgeBaseListItem from "./KnowledgeBaseListItem";

interface KnowledgeBaseListProps {
  kbs: KnowledgeBase[];
  selectedKbName: string | null;
  onSelect: (name: string) => void;
  onCreate: () => void;
  onSetDefault: (name: string) => void;
  onDelete: (name: string) => void;
  tasksByKb: Record<string, TaskState>;
}

export default function KnowledgeBaseList({
  kbs,
  selectedKbName,
  onSelect,
  onCreate,
  onSetDefault,
  onDelete,
  tasksByKb,
}: KnowledgeBaseListProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const { collapsed, toggle } = useCollapsiblePanel("knowledge-kb-list");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return kbs;
    return kbs.filter((kb) =>
      `${kb.name} ${getKnowledgeBaseDisplayName(kb)} ${getKnowledgeBaseShortName(kb)}`
        .toLowerCase()
        .includes(q),
    );
  }, [kbs, query]);

  if (collapsed) {
    return (
      <aside className="flex h-full w-[48px] shrink-0 flex-col items-center gap-1 border-r border-[var(--border)] bg-[var(--card)] py-2">
        <button
          type="button"
          onClick={toggle}
          title={t("Expand")}
          aria-label={t("Expand")}
          className="flex h-8 w-8 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <PanelLeftOpen size={14} strokeWidth={1.7} />
        </button>

        <button
          type="button"
          onClick={onCreate}
          title={t("New knowledge base")}
          aria-label={t("New knowledge base")}
          className="mb-1 flex h-8 w-8 items-center justify-center rounded-md bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
        >
          <Plus size={14} strokeWidth={2} />
        </button>

        <div className="my-1 h-px w-6 bg-[var(--border)]/60" />

        <div className="flex w-full flex-1 flex-col items-center gap-0.5 overflow-y-auto px-1 pb-2">
          {kbs.map((kb) => (
            <CollapsedKbDot
              key={kb.name}
              kb={kb}
              selected={selectedKbName === kb.name}
              isReindexingLocally={
                tasksByKb[kb.name]?.kind === "reindex" &&
                tasksByKb[kb.name]?.executing === true
              }
              onSelect={() => onSelect(kb.name)}
            />
          ))}
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex h-full w-[260px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--card)]">
      <div className="space-y-2.5 px-3 pb-2 pt-3">
        <div className="flex items-center justify-between gap-2 px-1">
          <div className="flex items-center gap-2">
            <h2 className="text-[13px] font-semibold text-[var(--foreground)]">
              {t("Knowledge Bases")}
            </h2>
            <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
              {kbs.length}
            </span>
          </div>
          <button
            type="button"
            onClick={toggle}
            title={t("Collapse")}
            aria-label={t("Collapse")}
            className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <PanelLeftClose size={13} strokeWidth={1.7} />
          </button>
        </div>

        <button
          type="button"
          onClick={onCreate}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
        >
          <Plus size={13} />
          {t("New knowledge base")}
        </button>

        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]"
            aria-hidden
          />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("Search knowledge bases…")}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] py-1.5 pl-8 pr-3 text-[12px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)] focus:border-[var(--foreground)]/25"
          />
        </div>
      </div>

      <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {filtered.map((kb) => {
          const isReindexingLocally =
            tasksByKb[kb.name]?.kind === "reindex" &&
            tasksByKb[kb.name]?.executing === true;
          return (
            <KnowledgeBaseListItem
              key={kb.name}
              kb={kb}
              selected={selectedKbName === kb.name}
              onSelect={() => onSelect(kb.name)}
              onSetDefault={() => onSetDefault(kb.name)}
              onDelete={() => onDelete(kb.name)}
              isReindexingLocally={isReindexingLocally}
            />
          );
        })}

        {!filtered.length && kbs.length > 0 && (
          <div className="py-6 text-center text-[12px] text-[var(--muted-foreground)]">
            {t("No matches")}
          </div>
        )}

        {!kbs.length && (
          <div className="rounded-xl border border-dashed border-[var(--border)] px-4 py-8 text-center">
            <Database className="mx-auto mb-2 h-5 w-5 text-[var(--muted-foreground)]" />
            <div className="text-[12.5px] font-medium text-[var(--foreground)]">
              {t("No knowledge bases yet")}
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
              {t("Create one to get started.")}
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}

function CollapsedKbDot({
  kb,
  selected,
  isReindexingLocally,
  onSelect,
}: {
  kb: KnowledgeBase;
  selected: boolean;
  isReindexingLocally: boolean;
  onSelect: () => void;
}) {
  const status = resolveKbStatus(kb);
  const displayName = getKnowledgeBaseDisplayName(kb);
  const needsReindex = kbNeedsReindex(kb);
  const isLive = kbHasLiveProgress(kb) || isReindexingLocally;
  const isError = status === "error";
  const isReady = status === "ready" && !needsReindex;

  const tone = needsReindex
    ? "bg-amber-500"
    : isError
      ? "bg-red-500"
      : isLive
        ? "bg-sky-500 animate-pulse"
        : isReady
          ? "bg-emerald-500"
          : "bg-[var(--muted-foreground)]";

  return (
    <button
      type="button"
      onClick={onSelect}
      title={displayName === kb.name ? kb.name : `${displayName} (${kb.name})`}
      aria-label={displayName}
      className={`relative flex h-9 w-9 items-center justify-center rounded-lg text-[10px] font-medium transition-colors ${
        selected
          ? "bg-[var(--primary)]/12 text-[var(--foreground)] ring-1 ring-[var(--primary)]/40"
          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
      }`}
    >
      {selected && (
        <span className="absolute -left-1 top-1/2 h-4 w-[2.5px] -translate-y-1/2 rounded-full bg-[var(--primary)]" />
      )}
      {kb.is_default ? (
        <Star className="h-3 w-3 text-amber-500" fill="currentColor" />
      ) : (
        <span className="uppercase tracking-tight">
          {getKnowledgeBaseShortName(kb).slice(0, 2)}
        </span>
      )}
      <span
        className={`absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border border-[var(--card)] ${tone}`}
      />
    </button>
  );
}
