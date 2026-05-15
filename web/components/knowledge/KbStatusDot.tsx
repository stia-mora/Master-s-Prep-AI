"use client";

import {
  kbHasLiveProgress,
  kbNeedsReindex,
  resolveKbStatus,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";

interface KbStatusDotProps {
  kb: KnowledgeBase;
  isReindexingLocally?: boolean;
}

export default function KbStatusDot({
  kb,
  isReindexingLocally = false,
}: KbStatusDotProps) {
  const status = resolveKbStatus(kb);
  const needsReindex = kbNeedsReindex(kb);
  const isLive = kbHasLiveProgress(kb) || isReindexingLocally;
  const isError = status === "error";
  const isReady = status === "ready" && !needsReindex;

  const color = needsReindex
    ? "bg-amber-500"
    : isError
      ? "bg-red-500"
      : isLive
        ? "bg-sky-500 animate-pulse"
        : isReady
          ? "bg-emerald-500"
          : "bg-[var(--muted-foreground)]";

  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}
