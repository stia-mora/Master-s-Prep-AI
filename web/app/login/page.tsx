"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { GraduationCap, Loader2, LogIn } from "lucide-react";
import { login } from "@/lib/auth-api";
import { useAuth } from "@/context/AuthContext";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const auth = useAuth();

  useEffect(() => {
    if (!auth.loading && auth.user) router.replace("/kaoyan");
  }, [auth.loading, auth.user, router]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await login(email, password);
      await auth.refresh();
      router.replace("/kaoyan");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--background)] px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)]"><GraduationCap size={21} /></div>
          <div><h1 className="text-xl font-semibold">DeepTutor 登录</h1><p className="text-sm text-[var(--muted-foreground)]">使用本地账号进入学习工作区</p></div>
        </div>
        {error ? <div className="mb-3 rounded-md border border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-3 py-2 text-sm text-[var(--destructive)]">{error}</div> : null}
        <label className="mb-3 block text-sm">邮箱<input className="mt-1 w-full rounded-lg border bg-transparent px-3 py-2" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label className="mb-4 block text-sm">密码<input className="mt-1 w-full rounded-lg border bg-transparent px-3 py-2" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        <button className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)]" disabled={loading}>{loading ? <Loader2 size={16} className="animate-spin" /> : <LogIn size={16} />} 登录</button>
      </form>
    </main>
  );
}