"use client";

import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { useTextSource } from "./useTextSource";

function normalizePreviewMarkdown(text: string): string {
  const escapedNewlineCount = (text.match(/\\n/g) || []).length;
  const looksLikeScopedKaoyanKb =
    text.includes("source_type:") &&
    (text.includes('"raw_markdown"') || text.includes("Kaoyan knowledge explanation") || text.includes("Kaoyan question explanation"));
  if (!looksLikeScopedKaoyanKb && escapedNewlineCount < 8) return text;
  return text
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t")
    .replace(/\\"/g, '"')
    .replace(/\\\\([A-Za-z])/g, "\\$1")
    .replace(/\\\\([()[\]{}])/g, "\\$1");
}
/**
 * Markdown preview that reuses the chat's main MarkdownRenderer (math,
 * tables, code highlight, mermaid all auto-detected).
 */
export default function MarkdownPreview({ url }: { url: string }) {
  const { t } = useTranslation();
  const state = useTextSource(url);

  if (state.kind === "loading") {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-[12px] text-[var(--muted-foreground)]">
        <Loader2 size={14} className="animate-spin" />
        <span>{t("Loading preview…")}</span>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-[12px] text-[var(--muted-foreground)]">
        {state.message}
      </div>
    );
  }

  return (
    <div className="px-6 py-5">
      <MarkdownRenderer content={normalizePreviewMarkdown(state.text)} variant="prose" enableMath />
    </div>
  );
}
