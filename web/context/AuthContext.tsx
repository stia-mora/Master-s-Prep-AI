"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getBootstrap, getMe, logout as logoutRequest, type AuthUser } from "@/lib/auth-api";
import { resolveBase } from "@/lib/api";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function shouldPatchCredentials(input: RequestInfo | URL): boolean {
  const raw = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  if (!raw) return false;
  if (raw.startsWith("/api/")) return true;
  try {
    const target = new URL(raw, typeof window !== "undefined" ? window.location.href : undefined);
    const base = new URL(resolveBase());
    return target.origin === base.origin;
  } catch {
    return false;
  }
}

function patchFetchCredentials() {
  if (typeof window === "undefined") return;
  const marker = "__master_prep_aiAuthFetchPatched";
  const win = window as typeof window & { [marker]?: boolean; __master_prep_aiOriginalFetch?: typeof fetch };
  if (win[marker]) return;
  win[marker] = true;
  win.__master_prep_aiOriginalFetch = window.fetch.bind(window);
  window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (shouldPatchCredentials(input)) {
      return win.__master_prep_aiOriginalFetch!(input, { ...init, credentials: init?.credentials || "include" });
    }
    return win.__master_prep_aiOriginalFetch!(input, init);
  }) as typeof fetch;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    patchFetchCredentials();
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getMe();
      setUser(result.user);
    } catch {
      setUser(null);
      const bootstrap = await getBootstrap().catch(() => ({ has_users: true }));
      if (pathname !== "/login" && pathname !== "/setup") {
        router.replace(bootstrap.has_users ? "/login" : "/setup");
      }
    } finally {
      setLoading(false);
    }
  }, [pathname, router]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    await logoutRequest().catch(() => undefined);
    setUser(null);
    router.replace("/login");
  }, [router]);

  const value = useMemo(() => ({ user, loading, refresh, logout }), [user, loading, refresh, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}