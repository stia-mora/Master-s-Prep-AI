"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  normalizeVersionTag,
  parseBuild,
  type ParsedBuild,
} from "@/lib/version";

interface LatestVersionPayload {
  tag: string | null;
  name: string | null;
  url: string | null;
  publishedAt: string | null;
  source: "github" | "fallback";
}

interface CurrentVersionPayload extends ParsedBuild {
  source: "git" | "env" | "unknown";
  detectedAt: string;
}

interface VersionPayload extends LatestVersionPayload {
  current?: CurrentVersionPayload;
  latest?: LatestVersionPayload;
}

interface VersionBadgeProps {
  /** Render the compact variant for the collapsed sidebar (currently hidden). */
  collapsed?: boolean;
}

let _cache: VersionPayload | null = null;
let _cacheAt = 0;
let _inflight: Promise<VersionPayload | null> | null = null;
const CACHE_TTL_MS = 60_000;

async function loadVersion(): Promise<VersionPayload | null> {
  if (_cache && Date.now() - _cacheAt < CACHE_TTL_MS) return _cache;
  if (_inflight) return _inflight;
  _inflight = (async () => {
    try {
      const res = await fetch("/api/version", { cache: "no-store" });
      if (!res.ok) return null;
      const data = (await res.json()) as VersionPayload;
      _cache = data;
      _cacheAt = Date.now();
      return data;
    } catch {
      return null;
    } finally {
      _inflight = null;
    }
  })();
  return _inflight;
}

type Status = "latest" | "outdated" | "dev" | "unknown";

export function VersionBadge({ collapsed = false }: VersionBadgeProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<VersionPayload | null>(_cache);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      loadVersion().then((v) => {
        if (!cancelled) setData(v);
      });
    };
    refresh();
    const interval = window.setInterval(refresh, CACHE_TTL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  const fallbackBuild = parseBuild(process.env.NEXT_PUBLIC_APP_VERSION || "");
  const build = data?.current?.raw ? data.current : fallbackBuild;
  const latest = data?.latest ?? data;
  const latestNorm = normalizeVersionTag(latest?.tag);

  const { status, displayTag, href, tooltip } = useMemo(() => {
    let status: Status = "unknown";
    if (build?.tag && latestNorm) {
      status =
        build.tag === latestNorm
          ? build.isDev
            ? "dev"
            : "latest"
          : "outdated";
    } else if (build?.isDev) {
      status = "dev";
    }

    // Display: prefer the running build (most accurate), fall back to the
    // latest GitHub release as an informational placeholder.
    const displayTag = build?.display ?? latestNorm ?? null;

    const href =
      latest?.url ??
      (latestNorm
        ? `https://github.com/3171381144/Master-s-Prep-AI/releases/tag/${latestNorm}`
        : "https://github.com/3171381144/Master-s-Prep-AI/releases");

    let tooltip: string;
    if (status === "latest" && displayTag) {
      tooltip = `${displayTag} · ${t("Up to date")}`;
    } else if (status === "outdated" && displayTag && latestNorm) {
      tooltip = `${displayTag} · ${t("Update available")}: ${latestNorm}`;
    } else if (status === "dev") {
      const base = `${t("Development build")}: ${build?.raw ?? ""}`;
      tooltip = latestNorm
        ? `${base} · ${t("Latest release")}: ${latestNorm}`
        : base;
    } else if (displayTag) {
      tooltip = `${t("Latest release")}: ${displayTag}`;
    } else {
      tooltip = t("Loading...");
    }

    return { status, displayTag, href, tooltip };
  }, [build, latestNorm, latest?.url, t]);

  // Keep the collapsed sidebar entirely free of version chrome.
  if (collapsed) return null;

  const dotClass =
    status === "latest"
      ? "bg-emerald-500/45"
      : status === "outdated"
        ? "bg-amber-500/55"
        : status === "dev"
          ? "bg-sky-500/45"
          : "bg-[var(--muted-foreground)]/25";

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      title={tooltip}
      className="group/ver flex min-w-0 flex-1 items-center gap-2 rounded-lg px-3 py-1.5 text-[11px] font-mono tabular-nums tracking-tight text-[var(--muted-foreground)]/55 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--muted-foreground)]"
    >
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full transition-colors ${dotClass}`}
        aria-hidden="true"
      />
      <span className="truncate leading-none decoration-[var(--muted-foreground)]/40 decoration-dotted underline-offset-[3px] group-hover/ver:underline">
        {displayTag ?? "—"}
      </span>
    </a>
  );
}
