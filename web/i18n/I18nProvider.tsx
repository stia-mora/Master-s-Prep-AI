"use client";

import { useEffect } from "react";
import i18n from "i18next";

import { initI18n, normalizeLanguage, type AppLanguage } from "./init";

// Initialize i18next at module load (before any React render) so that the
// `init()` call — which fires `initialized` / `languageChanged` events that
// trigger setState on subscribed components — never happens during another
// component's render phase. Calling `initI18n` from the render body would
// produce the React warning:
//   "Cannot update a component (`X`) while rendering a different component
//   (`I18nProvider`)."
initI18n();

export function I18nProvider({
  language,
  children,
}: {
  language: AppLanguage | string;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const nextLang = normalizeLanguage(language);
    if (i18n.language !== nextLang) {
      i18n.changeLanguage(nextLang);
    }

    // Keep <html lang="..."> in sync for accessibility & Intl defaults
    if (typeof document !== "undefined") {
      document.documentElement.lang = nextLang;
    }
  }, [language]);

  return children;
}
