"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  Brain,
  ClipboardList,
  LayoutGrid,
  NotebookPen,
  Wand2,
  type LucideIcon,
} from "lucide-react";

interface SpaceNavEntry {
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
}

const SPACE_NAV: SpaceNavEntry[] = [
  {
    href: "/space/notebooks",
    label: "Notebooks",
    description: "Organize saved outputs from chat, research, Co-Writer, and more.",
    icon: NotebookPen,
  },
  {
    href: "/space/questions",
    label: "Question Bank",
    description: "Review and organize quiz questions across sessions.",
    icon: ClipboardList,
  },
  {
    href: "/space/skills",
    label: "Skills",
    description: "Behavior playbooks that guide chat responses.",
    icon: Wand2,
  },
  {
    href: "/space/memory",
    label: "Memory",
    description: "Long-form memory the assistant carries across sessions.",
    icon: Brain,
  },
];

export default function SpaceMiniNav() {
  const pathname = usePathname();
  const { t } = useTranslation();

  return (
    <aside className="flex h-full w-[224px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--card)]">
      <div className="flex items-start gap-2.5 border-b border-[var(--border)]/60 px-4 pb-4 pt-5">
        <span
          aria-hidden
          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-[var(--border)]/70 bg-[var(--background)] text-[var(--foreground)]"
        >
          <LayoutGrid size={13} strokeWidth={1.6} />
        </span>
        <div className="min-w-0">
          <h1 className="text-[14.5px] font-semibold leading-tight tracking-tight text-[var(--foreground)]">
            {t("Space")}
          </h1>
          <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Your personal library of notebooks, questions, playbooks, and memory.",
            )}
          </p>
        </div>
      </div>

      <nav className="flex-1 space-y-1 px-2 py-3">
        {SPACE_NAV.map(({ href, label, description, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`group block rounded-xl px-2.5 py-2 transition-colors ${
                active
                  ? "bg-[var(--background)]/70 text-[var(--foreground)] shadow-sm ring-1 ring-[var(--border)]/80"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
              }`}
            >
              <div className="flex items-start gap-2.5">
                <span
                  className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border transition-colors ${
                    active
                      ? "border-[var(--border)] bg-[var(--card)] text-[var(--foreground)]"
                      : "border-[var(--border)]/50 bg-[var(--background)]/40 text-[var(--muted-foreground)] group-hover:border-[var(--border)]/80 group-hover:text-[var(--foreground)]"
                  }`}
                >
                  <Icon size={12} strokeWidth={active ? 1.9 : 1.5} />
                </span>
                <div className="min-w-0">
                  <div className="text-[12.5px] font-medium leading-tight tracking-tight">
                    {t(label)}
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-[10.5px] leading-snug text-[var(--muted-foreground)]/80">
                    {t(description)}
                  </p>
                </div>
              </div>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
