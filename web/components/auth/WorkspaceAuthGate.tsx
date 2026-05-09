"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

export function WorkspaceAuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, router, user]);

  if (loading || !user) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-[var(--background)] text-[var(--muted-foreground)]">
        <div className="inline-flex items-center gap-2 text-sm">
          <Loader2 size={16} className="animate-spin" />
          正在校验登录状态
        </div>
      </div>
    );
  }

  return <>{children}</>;
}