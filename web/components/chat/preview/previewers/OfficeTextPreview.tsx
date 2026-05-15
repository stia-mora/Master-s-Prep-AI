"use client";

import { Info } from "lucide-react";
import { useTranslation } from "react-i18next";
import FallbackPreview from "./FallbackPreview";

/**
 * DOCX / XLSX / PPTX preview using the backend-extracted plain text. Browsers
 * cannot natively render OOXML and we choose not to ship mammoth.js / sheetjs
 * to keep the bundle slim. Showing the extracted text doubles as "see what
 * the LLM read", which is itself useful in a study tool.
 */
export default function OfficeTextPreview({
  filename,
  extractedText,
  url,
}: {
  filename: string;
  extractedText: string | undefined;
  url: string | null;
}) {
  const { t } = useTranslation();

  if (!extractedText) {
    return <FallbackPreview filename={filename} url={url} />;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start gap-2 border-b border-[var(--border)] bg-[var(--muted)]/40 px-5 py-2.5 text-[11px] text-[var(--muted-foreground)]">
        <Info size={13} strokeWidth={1.6} className="mt-px shrink-0" />
        <p>
          {t(
            "Showing extracted text — the same content the assistant reads. Download the original to see full formatting.",
          )}
        </p>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <pre className="whitespace-pre-wrap break-words font-sans text-[13px] leading-relaxed text-[var(--foreground)]">
          {extractedText}
        </pre>
      </div>
    </div>
  );
}
