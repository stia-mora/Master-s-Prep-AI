import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";

export default function PaperAssemblyPage() {
  return (
    <main className="flex h-screen min-h-[720px] flex-col bg-[var(--background)] text-[var(--foreground)]">
      <div className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--card)] px-4">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/kaoyan"
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--secondary)] px-3 py-1.5 text-sm text-[var(--secondary-foreground)] hover:bg-[var(--muted)]"
          >
            <ArrowLeft size={15} />
            返回考研助手
          </Link>
          <div className="truncate text-sm font-semibold text-[var(--foreground)]">做题库</div>
        </div>
        <a
          href="/paper-assembly-agent/index.html"
          target="_blank"
          rel="noreferrer"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-sm text-[var(--primary-foreground)] hover:opacity-90"
        >
          <ExternalLink size={15} />
          新窗口打开
        </a>
      </div>
      <iframe
        src="/paper-assembly-agent/index.html"
        title="做题库"
        className="min-h-0 flex-1 border-0 bg-[var(--background)]"
      />
    </main>
  );
}
