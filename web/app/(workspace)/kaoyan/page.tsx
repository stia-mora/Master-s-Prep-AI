"use client";

import { useCallback, useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { BarChart3, BookOpenCheck, Brain, CheckCircle2, ChevronDown, ChevronRight, ClipboardList, GraduationCap, Loader2, MessageCircleQuestion, PlayCircle, RefreshCw, RotateCcw, Sparkles, Target, Upload } from "lucide-react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { useUnifiedChat } from "@/context/UnifiedChatContext";
import { createDiagnosticSession, createKaoyanChatContext, createPracticeSession, generatePlan, getDashboardSummary, getDiagnosticReports, confirmDiagnosticReport, getKnowledgeDetail, getKnowledgeTree, getReviewsToday, getTodayTasks, getWrongQuestions, initProfile, submitDiagnostic, submitPractice, submitReview, updateTaskStatus } from "@/lib/kaoyan-api";
import type { ContentQuestion, DashboardSummary, DiagnosticReport, DiagnosticResult, KaoyanProfile, KnowledgeDetail, KnowledgeNode, PlanTask, PracticeResult, PracticeSession, ProfileDraft, ReviewItem, WrongQuestion } from "@/lib/kaoyan-types";

const DEFAULT_PROFILE: KaoyanProfile = { target_school: "", target_major: "", exam_date: "2026-12-20", daily_minutes: 180, target_score: 120, baseline_level: "待诊断", weak_modules: [] };
const tabs = [
  { id: "dashboard", label: "驾驶舱", icon: BarChart3 },
  { id: "knowledge", label: "知识库", icon: BookOpenCheck },
  { id: "practice", label: "练习", icon: PlayCircle },
  { id: "wrong", label: "错题", icon: RotateCcw },
  { id: "reports", label: "诊断报告", icon: ClipboardList },
  { id: "review", label: "复习", icon: ClipboardList },
] as const;

type TabId = (typeof tabs)[number]["id"];
type DiagnosticMode = "light" | "deep";
type ChatSourceType = "knowledge" | "question";
type TaskProgressStatus = "idle" | "running" | "success" | "error";
type TaskProgress = { status: TaskProgressStatus; label: string; stage: string; percent: number };
const IDLE_TASK_PROGRESS: TaskProgress = { status: "idle", label: "", stage: "", percent: 0 };

function pct(value: number | undefined): string { return `${Math.round((value || 0) * 100)}%`; }
function flattenKnowledge(nodes: KnowledgeNode[]): KnowledgeNode[] { const out: KnowledgeNode[] = []; const walk = (items: KnowledgeNode[]) => { for (const item of items) { out.push(item); if (item.children?.length) walk(item.children); } }; walk(nodes); return out; }
function isSelectableKnowledge(item: KnowledgeNode): boolean { return ["section", "subsection", "knowledge_point"].includes(item.node_type || "") || item.knowledge_id.includes("SEC"); }
function findFirstSelectable(nodes: KnowledgeNode[]): KnowledgeNode | undefined { return flattenKnowledge(nodes).find(isSelectableKnowledge); }
function isChoiceQuestion(question: ContentQuestion): boolean { return Boolean(question.is_choice || question.options?.length || question.question_type.includes("选择")); }
function splitTextList(value: string): string[] { return value.split(/[，,、\n]/).map((item) => item.trim()).filter(Boolean); }
function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) { return <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"><div className="text-xs text-[var(--muted-foreground)]">{label}</div><div className="mt-2 text-2xl font-semibold text-[var(--foreground)]">{value}</div>{sub ? <div className="mt-1 text-xs text-[var(--muted-foreground)]">{sub}</div> : null}</div>; }

export default function KaoyanPage() {
  const router = useRouter();
  const { setCapability, setTools, setKBs, setLanguage } = useUnifiedChat();
  const [activeTab, setActiveTab] = useState<TabId>("dashboard");
  const [profile, setProfile] = useState<KaoyanProfile>(DEFAULT_PROFILE);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [tasks, setTasks] = useState<PlanTask[]>([]);
  const [knowledgeTree, setKnowledgeTree] = useState<KnowledgeNode[]>([]);
  const [selectedKnowledgeId, setSelectedKnowledgeId] = useState("");
  const [knowledgeDetail, setKnowledgeDetail] = useState<KnowledgeDetail | null>(null);
  const [practice, setPractice] = useState<PracticeSession | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [imageAnswers, setImageAnswers] = useState<Record<string, string>>({});
  const [practiceResult, setPracticeResult] = useState<PracticeResult | null>(null);
  const [diagnostic, setDiagnostic] = useState<PracticeSession | null>(null);
  const [diagnosticAnswers, setDiagnosticAnswers] = useState<Record<string, string>>({});
  const [diagnosticImages, setDiagnosticImages] = useState<Record<string, string>>({});
  const [diagnosticResult, setDiagnosticResult] = useState<DiagnosticResult | null>(null);
  const [diagnosticReports, setDiagnosticReports] = useState<DiagnosticReport[]>([]);
  const [profileDraft, setProfileDraft] = useState<ProfileDraft | null>(null);
  const [wrongQuestions, setWrongQuestions] = useState<WrongQuestion[]>([]);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [taskProgress, setTaskProgress] = useState<TaskProgress>(IDLE_TASK_PROGRESS);
  const flatKnowledge = useMemo(() => flattenKnowledge(knowledgeTree), [knowledgeTree]);
  const startTaskProgress = (label: string, stage: string, percent = 20) => setTaskProgress({ status: "running", label, stage, percent });
  const updateTaskProgress = (stage: string, percent: number) => setTaskProgress((prev) => ({ ...prev, status: "running", stage, percent }));
  const finishTaskProgress = (stage = "\u5df2\u5b8c\u6210") => setTaskProgress((prev) => ({ ...prev, status: "success", stage, percent: 100 }));
  const failTaskProgress = (stage = "\u5904\u7406\u5931\u8d25") => setTaskProgress((prev) => ({ ...prev, status: "error", stage, percent: Math.max(prev.percent, 100) }));
  const refresh = useCallback(async () => {
    setError("");
    try {
      const reportsPromise = getDiagnosticReports().catch(() => ({ reports: [] as DiagnosticReport[] }));
      const [tree, dashboard, today, wrong, reviewItems, reportItems] = await Promise.all([getKnowledgeTree(), getDashboardSummary(), getTodayTasks(), getWrongQuestions(), getReviewsToday(), reportsPromise]);
      setKnowledgeTree(tree); setSummary(dashboard); setTasks(today); setWrongQuestions(wrong); setReviews(reviewItems); setDiagnosticReports(reportItems.reports || []);
      if (dashboard.profile) setProfile({ ...DEFAULT_PROFILE, ...dashboard.profile });
      if (!selectedKnowledgeId) { const first = findFirstSelectable(tree); if (first) setSelectedKnowledgeId(first.knowledge_id); }
    } catch (err) { setError(err instanceof Error ? err.message : "加载考研助手数据失败"); }
  }, [selectedKnowledgeId]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { if (!selectedKnowledgeId) return; getKnowledgeDetail(selectedKnowledgeId).then(setKnowledgeDetail).catch((err) => setError(err instanceof Error ? err.message : "加载知识点失败")); }, [selectedKnowledgeId]);

  async function handleProfileSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading("profile"); setError("");
    try { const saved = await initProfile(profile); setProfile({ ...DEFAULT_PROFILE, ...saved }); setNotice("画像已保存。建议完成诊断后再生成学习计划。"); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "保存画像失败"); }
    finally { setLoading(null); }
  }

  async function handleStartDiagnostic(mode: DiagnosticMode) {
    setLoading(`diagnostic-${mode}`); setError(""); setNotice(""); setDiagnosticResult(null); setProfileDraft(null);
    startTaskProgress("\u751f\u6210\u5165\u95e8\u8bca\u65ad", "\u6b63\u5728\u51c6\u5907\u8bca\u65ad\u9898\u96c6", 25);
    try {
      updateTaskProgress("\u6b63\u5728\u8c03\u7528\u9898\u5e93\u4e0e\u6a21\u578b", 60);
      const session = await createDiagnosticSession({ mode, profile });
      setDiagnostic(session); setDiagnosticAnswers({}); setDiagnosticImages({}); setActiveTab("dashboard");
      setNotice(mode === "light" ? "\u5df2\u751f\u6210 5 \u5206\u949f\u8f7b\u8bca\u65ad" : "\u5df2\u751f\u6210 30 \u5206\u949f\u6df1\u8bca\u65ad");
      finishTaskProgress("\u8bca\u65ad\u9898\u96c6\u5df2\u5c31\u7eea");
    }
    catch (err) { failTaskProgress(); setError(err instanceof Error ? err.message : "Diagnostic generation failed"); }
    finally { setLoading(null); }
  }
  async function handleSubmitDiagnostic() {
    if (!diagnostic) return; setLoading("submit-diagnostic"); setError("");
    startTaskProgress("\u63d0\u4ea4\u8bca\u65ad", "AI \u6b63\u5728\u5224\u5206\u5e76\u751f\u6210\u753b\u50cf\u8349\u6848", 45);
    try {
      updateTaskProgress("\u6b63\u5728\u7b49\u5f85\u6a21\u578b\u8bca\u65ad", 70);
      const result = await submitDiagnostic(diagnostic.session_id, diagnostic.questions.map((question) => ({ question_id: question.question_id, answer: diagnosticAnswers[question.question_id] || "", image_data_url: diagnosticImages[question.question_id] })));
      setDiagnosticResult(result); setProfileDraft(result.profile_draft); setNotice(result.ai_metadata?.message || "\u8bca\u65ad\u5b8c\u6210\uff0c\u5df2\u751f\u6210\u753b\u50cf\u8349\u6848"); finishTaskProgress("\u753b\u50cf\u8349\u6848\u5df2\u751f\u6210"); await refresh();
    } catch (err) { failTaskProgress(); setError(err instanceof Error ? err.message : "Diagnostic submit failed"); }
    finally { setLoading(null); }
  }
  async function handleConfirmDiagnosticProfile() {
    if (!profileDraft) return; setLoading("confirm-diagnostic"); setError("");
    startTaskProgress("\u786e\u8ba4\u753b\u50cf\u5e76\u751f\u6210\u8ba1\u5212", "\u6b63\u5728\u4fdd\u5b58\u753b\u50cf", 30);
    try {
      const nextProfile: KaoyanProfile = { ...profile, baseline_level: profileDraft.baseline_level || profile.baseline_level, weak_modules: profileDraft.weak_modules || [], daily_minutes: profileDraft.recommended_daily_minutes || profile.daily_minutes };
      const saved = await initProfile(nextProfile); setProfile({ ...DEFAULT_PROFILE, ...saved }); updateTaskProgress("AI \u6b63\u5728\u89c4\u5212\u4eca\u65e5\u4efb\u52a1", 70); const plan = await generatePlan(); setTasks(plan.tasks || []); setNotice("\u753b\u50cf\u5df2\u786e\u8ba4\uff0c\u5b66\u4e60\u8ba1\u5212\u5df2\u751f\u6210"); finishTaskProgress("\u5b66\u4e60\u8ba1\u5212\u5df2\u751f\u6210"); await refresh();
    } catch (err) { failTaskProgress(); setError(err instanceof Error ? err.message : "Profile confirmation failed"); }
    finally { setLoading(null); }
  }
  async function handleConfirmReport(reportId: string) {
    setLoading(`report-${reportId}`); setError(""); setNotice("");
    try {
      await confirmDiagnosticReport(reportId);
      const plan = await generatePlan();
      setTasks(plan.tasks || []);
      setNotice("诊断报告已确认，画像已更新并重新生成计划。");
      await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "确认诊断报告失败"); }
    finally { setLoading(null); }
  }
  async function handleGeneratePlan() {
    setLoading("plan"); setError("");
    startTaskProgress("\u751f\u6210\u5b66\u4e60\u8ba1\u5212", "AI \u6b63\u5728\u62c6\u89e3\u9636\u6bb5\u4efb\u52a1", 45);
    try { updateTaskProgress("\u6b63\u5728\u5199\u5165\u4eca\u65e5\u4efb\u52a1", 75); const plan = await generatePlan(); setTasks(plan.tasks || []); setNotice(plan.ai_metadata?.message || plan.ai_message || "\u8ba1\u5212\u5df2\u751f\u6210"); finishTaskProgress("\u8ba1\u5212\u5df2\u751f\u6210"); await refresh(); }
    catch (err) { failTaskProgress(); setError(err instanceof Error ? err.message : "Plan generation failed"); }
    finally { setLoading(null); }
  }
  async function handleTaskStatus(task: PlanTask, status: string) { setLoading(task.task_id); try { await updateTaskStatus(task.task_id, status); await refresh(); } catch (err) { setError(err instanceof Error ? err.message : "更新任务失败"); } finally { setLoading(null); } }

  async function handleCreatePractice(type: "special" | "wrong_retry" = "special") {
    setLoading("practice"); setError(""); setPracticeResult(null);
    try { const session = await createPracticeSession({ session_type: type, knowledge_id: type === "special" ? selectedKnowledgeId || undefined : undefined, limit: 5 }); setPractice(session); setAnswers({}); setImageAnswers({}); setActiveTab("practice"); }
    catch (err) { setError(err instanceof Error ? err.message : "创建练习失败"); }
    finally { setLoading(null); }
  }

  async function handleSubmitPractice() {
    if (!practice) return; setLoading("submit-practice"); setError("");
    startTaskProgress("\u63d0\u4ea4\u7ec3\u4e60", "AI \u6b63\u5728\u5224\u5206\u548c\u5206\u6790\u9519\u56e0", 55);
    try { updateTaskProgress("\u6b63\u5728\u5199\u5165\u9519\u9898\u4e0e\u590d\u4e60\u961f\u5217", 80); const result = await submitPractice(practice.session_id, practice.questions.map((question) => ({ question_id: question.question_id, answer: answers[question.question_id] || "", image_data_url: imageAnswers[question.question_id] }))); setPracticeResult(result); setNotice(result.ai_metadata?.message || "\u7ec3\u4e60\u5df2\u63d0\u4ea4\uff0c\u9519\u9898\u548c\u590d\u4e60\u961f\u5217\u5df2\u66f4\u65b0"); finishTaskProgress("\u7ec3\u4e60\u53cd\u9988\u5df2\u751f\u6210"); await refresh(); }
    catch (err) { failTaskProgress(); setError(err instanceof Error ? err.message : "Practice submit failed"); }
    finally { setLoading(null); }
  }
  function handleImageAnswer(questionId: string, event: ChangeEvent<HTMLInputElement>, target: "practice" | "diagnostic") {
    const file = event.target.files?.[0]; if (!file) return; const reader = new FileReader();
    reader.onload = () => { const value = typeof reader.result === "string" ? reader.result : ""; if (target === "diagnostic") setDiagnosticImages((prev) => ({ ...prev, [questionId]: value })); else setImageAnswers((prev) => ({ ...prev, [questionId]: value })); };
    reader.readAsDataURL(file);
  }

  async function handleReview(review: ReviewItem, status: "reviewed" | "mastered" | "failed") { setLoading(review.review_id); try { await submitReview(review.review_id, status); await refresh(); } catch (err) { setError(err instanceof Error ? err.message : "提交复习结果失败"); } finally { setLoading(null); } }

  async function handleAskAI(sourceType: ChatSourceType, sourceId: string, intent = "explain") {
    setLoading(`chat-${sourceId}`); setError("");
    startTaskProgress("AI \u89e3\u6790", sourceType === "question" ? "\u6b63\u5728\u6784\u5efa\u9898\u76ee RAG \u77e5\u8bc6\u5e93" : "\u6b63\u5728\u6784\u5efa\u77e5\u8bc6\u70b9 RAG \u77e5\u8bc6\u5e93", 35);
    try {
      const context = await createKaoyanChatContext({ source_type: sourceType, source_id: sourceId, intent });
      updateTaskProgress("\u6b63\u5728\u5199\u5165\u804a\u5929\u4e0a\u4e0b\u6587", 85);
      const rag = context.rag;
      const useRag = Boolean(rag?.ready && rag.kb_name);
      const selectedCapability = "deep_solve";
      const selectedTools = useRag ? ["rag", "reason"] : ["reason"];
      const selectedKBs = useRag && rag?.kb_name ? [rag.kb_name] : [];
      const requestConfig = useRag
        ? { kaoyan_title: context.title, kaoyan_rag: rag, kaoyan_question_entry: context.question_entry }
        : { kaoyan_context: context.context_payload, kaoyan_title: context.title, kaoyan_rag: rag, kaoyan_question_entry: context.question_entry };
      const autoChatPayload = {
        content: context.initial_message,
        capability: selectedCapability,
        enabledTools: selectedTools,
        knowledgeBases: selectedKBs,
        language: "zh",
        config: requestConfig,
      };
      if (typeof window !== "undefined") {
        window.sessionStorage.setItem("kaoyan:auto-chat", JSON.stringify(autoChatPayload));
      }
      setCapability(selectedCapability);
      setTools(selectedTools);
      setKBs(selectedKBs);
      setLanguage("zh");
      finishTaskProgress(useRag ? "RAG \u77e5\u8bc6\u5e93\u5df2\u9009\u4e2d" : "\u5df2\u4f7f\u7528\u5185\u5d4c\u4e0a\u4e0b\u6587\u515c\u5e95");
      router.push("/chat?kaoyanAuto=1");
    }
    catch (err) { failTaskProgress(); setError(err instanceof Error ? err.message : "AI context creation failed"); }
    finally { setLoading(null); }
  }
  return (
    <div className="flex h-full flex-col overflow-hidden bg-[var(--background)]" translate="no">
      <header className="border-b border-[var(--border)] bg-[var(--card)] px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)]"><GraduationCap size={22} /></div><div><h1 className="text-xl font-semibold text-[var(--foreground)]">AI 考研助手</h1><p className="text-sm text-[var(--muted-foreground)]">高数 MVP：画像、诊断、计划、练习、错题、复习、反馈闭环</p></div></div><button onClick={() => void refresh()} className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--foreground)] hover:bg-[var(--muted)]"><RefreshCw size={15} /> 刷新</button></div>
        <nav className="mt-4 flex flex-wrap gap-2">{tabs.map((tab) => { const Icon = tab.icon; const active = activeTab === tab.id; return <button key={tab.id} onClick={() => setActiveTab(tab.id)} className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors ${active ? "bg-[var(--foreground)] text-[var(--background)]" : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"}`}><Icon size={15} /> {tab.label}</button>; })}</nav>
      </header>
      <main className="flex-1 overflow-y-auto px-6 py-5">
        {notice ? <div className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-300">{notice}</div> : null}
        {error ? <div className="mb-4 rounded-lg border border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-4 py-3 text-sm text-[var(--destructive)]">{error}</div> : null}
        <KaoyanTaskProgress progress={taskProgress} />
        {activeTab === "dashboard" ? <div className="grid gap-5 xl:grid-cols-[420px_1fr]"><section className="space-y-4"><div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-5"><div className="mb-4 flex items-center gap-2 text-base font-semibold"><Target size={18} /> 学生画像</div><form onSubmit={handleProfileSubmit} className="space-y-3"><input className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm" placeholder="目标院校" value={profile.target_school} onChange={(e) => setProfile({ ...profile, target_school: e.target.value })} /><input className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm" placeholder="目标专业" value={profile.target_major} onChange={(e) => setProfile({ ...profile, target_major: e.target.value })} /><div className="grid grid-cols-2 gap-3"><label className="space-y-1 text-xs text-[var(--muted-foreground)]">考试日期<input className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm text-[var(--foreground)]" type="date" value={profile.exam_date} onChange={(e) => setProfile({ ...profile, exam_date: e.target.value })} /></label><label className="space-y-1 text-xs text-[var(--muted-foreground)]">每日分钟<input className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm text-[var(--foreground)]" type="number" min={30} value={profile.daily_minutes} onChange={(e) => setProfile({ ...profile, daily_minutes: Number(e.target.value) })} /></label></div><div className="grid grid-cols-2 gap-3"><label className="space-y-1 text-xs text-[var(--muted-foreground)]">目标分<input className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm text-[var(--foreground)]" type="number" value={profile.target_score} onChange={(e) => setProfile({ ...profile, target_score: Number(e.target.value) })} /></label><label className="space-y-1 text-xs text-[var(--muted-foreground)]">基础水平<select className="w-full rounded-lg border bg-[var(--card)] px-3 py-2 text-sm text-[var(--foreground)]" value={profile.baseline_level} onChange={(e) => setProfile({ ...profile, baseline_level: e.target.value })}><option>待诊断</option><option>基础薄弱</option><option>基础</option><option>中等</option><option>强化</option><option>冲刺</option></select></label></div><input className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm" placeholder="薄弱模块，可由诊断自动修正" value={profile.weak_modules.join("，")} onChange={(e) => setProfile({ ...profile, weak_modules: splitTextList(e.target.value) })} /><div className="flex gap-2"><button className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm font-medium text-[var(--primary-foreground)]" disabled={loading === "profile"}>{loading === "profile" ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />} 保存画像</button><button type="button" onClick={() => void handleGeneratePlan()} className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium" disabled={loading === "plan"}>{loading === "plan" ? <Loader2 size={15} className="animate-spin" /> : <Brain size={15} />} 生成计划</button></div></form></div><DiagnosticPanel session={diagnostic} answers={diagnosticAnswers} imageAnswers={diagnosticImages} result={diagnosticResult} draft={profileDraft} loading={loading} onStart={(mode) => void handleStartDiagnostic(mode)} onAnswer={(questionId, answer) => setDiagnosticAnswers((prev) => ({ ...prev, [questionId]: answer }))} onImage={(questionId, event) => handleImageAnswer(questionId, event, "diagnostic")} onSubmit={() => void handleSubmitDiagnostic()} onDraftChange={setProfileDraft} onConfirm={() => void handleConfirmDiagnosticProfile()} /></section><section className="space-y-5"><div className="grid gap-3 md:grid-cols-4"><Metric label="任务完成率" value={pct(summary?.completion_rate)} sub={`${summary?.task_completed || 0}/${summary?.task_total || 0} 个任务`} /><Metric label="练习正确率" value={pct(summary?.accuracy)} sub={`${summary?.practice_sessions || 0} 次练习`} /><Metric label="待复习" value={`${summary?.review_due_count || 0}`} sub="错题、公式、易错卡" /><Metric label="平均掌握度" value={`${Math.round(summary?.mastery_average || 0)}`} sub="0-100" /></div><TaskPanel tasks={tasks} loading={loading} onStatus={handleTaskStatus} onPractice={() => void handleCreatePractice("special")} /></section></div> : null}
        {activeTab === "knowledge" ? <div className="grid gap-5 xl:grid-cols-[360px_1fr]"><section className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"><div className="mb-3 font-semibold">高数知识树</div><div className="max-h-[68vh] overflow-y-auto pr-1"><KnowledgeTree nodes={knowledgeTree} selectedId={selectedKnowledgeId} onSelect={setSelectedKnowledgeId} /></div></section><KnowledgePanel detail={knowledgeDetail} loading={loading} onPractice={() => void handleCreatePractice("special")} onAskAI={(knowledgeId) => void handleAskAI("knowledge", knowledgeId, "explain")} /></div> : null}
        {activeTab === "practice" ? <PracticePanel practice={practice} answers={answers} imageAnswers={imageAnswers} result={practiceResult} loading={loading} onAnswer={(questionId, answer) => setAnswers((prev) => ({ ...prev, [questionId]: answer }))} onImage={(questionId, event) => handleImageAnswer(questionId, event, "practice")} onCreate={() => void handleCreatePractice("special")} onRetry={() => void handleCreatePractice("wrong_retry")} onSubmit={() => void handleSubmitPractice()} onAskAI={(questionId) => void handleAskAI("question", questionId, "solve")} /> : null}
        {activeTab === "wrong" ? <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">错题本</h2><button onClick={() => void handleCreatePractice("wrong_retry")} className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)]">错题二刷</button></div>{wrongQuestions.length === 0 ? <Empty text="还没有错题。完成一次练习后，这里会自动归档。" /> : wrongQuestions.map((item) => <WrongCard key={item.wrong_id} item={item} loading={loading} onAskAI={(questionId) => void handleAskAI("question", questionId, "wrong_question_review")} />)}</section> : null}
        {activeTab === "reports" ? <ReportsPanel reports={diagnosticReports} loading={loading} onConfirm={(reportId) => void handleConfirmReport(reportId)} /> : null}
        {activeTab === "review" ? <ReviewPanel reviews={reviews} onReview={handleReview} /> : null}
      </main>
    </div>
  );
}
function KaoyanTaskProgress({ progress }: { progress: TaskProgress }) {
  if (progress.status === "idle") return null;
  const tone = progress.status === "error" ? "bg-[var(--destructive)]" : progress.status === "success" ? "bg-emerald-500" : "bg-[var(--primary)]";
  const width = `${Math.max(8, Math.min(100, progress.percent))}%`;
  return <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm"><div className="mb-2 flex items-center justify-between gap-3"><div className="font-medium text-[var(--foreground)]">{progress.label}</div><div className="text-xs text-[var(--muted-foreground)]">{progress.stage}</div></div><div className="h-1.5 overflow-hidden rounded-full bg-[var(--muted)]"><div className={`h-full rounded-full transition-all duration-300 ${tone} ${progress.status === "running" ? "animate-pulse" : ""}`} style={{ width }} /></div></div>;
}
function DiagnosticPanel({ session, answers, imageAnswers, result, draft, loading, onStart, onAnswer, onImage, onSubmit, onDraftChange, onConfirm }: { session: PracticeSession | null; answers: Record<string, string>; imageAnswers: Record<string, string>; result: DiagnosticResult | null; draft: ProfileDraft | null; loading: string | null; onStart: (mode: DiagnosticMode) => void; onAnswer: (questionId: string, answer: string) => void; onImage: (questionId: string, event: ChangeEvent<HTMLInputElement>) => void; onSubmit: () => void; onDraftChange: (draft: ProfileDraft) => void; onConfirm: () => void }) {
  return <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-5"><div className="mb-4"><div className="flex items-center gap-2 font-semibold"><Sparkles size={17} /> 入门诊断</div><p className="mt-1 text-xs text-[var(--muted-foreground)]">诊断题会留在画像区域内完成，用于生成画像草案和计划种子。</p></div>{!session ? <div className="grid grid-cols-2 gap-2"><button type="button" onClick={() => onStart("light")} className="inline-flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium" disabled={loading === "diagnostic-light"}>{loading === "diagnostic-light" ? <Loader2 size={15} className="animate-spin" /> : <Brain size={15} />} 5 分钟轻诊断</button><button type="button" onClick={() => onStart("deep")} className="inline-flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium" disabled={loading === "diagnostic-deep"}>{loading === "diagnostic-deep" ? <Loader2 size={15} className="animate-spin" /> : <Brain size={15} />} 30 分钟深诊断</button></div> : null}{session && !result ? <div className="space-y-4"><div className="rounded-lg bg-[var(--muted)] px-3 py-2 text-sm font-medium">{session.title}</div>{session.questions.map((question, index) => <QuestionAnswer key={question.question_id} question={question} index={index} answer={answers[question.question_id] || ""} imageAnswer={imageAnswers[question.question_id]} onAnswer={(answer) => onAnswer(question.question_id, answer)} onImage={(event) => onImage(question.question_id, event)} />)}<button onClick={onSubmit} disabled={loading === "submit-diagnostic"} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm text-[var(--background)]">{loading === "submit-diagnostic" ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />} 提交诊断并生成画像草案</button></div> : null}{draft ? <div className="mt-4 space-y-4 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4"><div className="font-semibold">画像草案</div>{result?.summary ? <p className="text-sm text-[var(--muted-foreground)]">{result.summary}</p> : null}<div className="grid gap-3 md:grid-cols-2"><label className="space-y-1 text-xs text-[var(--muted-foreground)]">基础等级<input className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm text-[var(--foreground)]" value={draft.baseline_level} onChange={(e) => onDraftChange({ ...draft, baseline_level: e.target.value })} /></label><label className="space-y-1 text-xs text-[var(--muted-foreground)]">建议每日分钟<input className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm text-[var(--foreground)]" type="number" value={draft.recommended_daily_minutes} onChange={(e) => onDraftChange({ ...draft, recommended_daily_minutes: Number(e.target.value) })} /></label></div><label className="block space-y-1 text-xs text-[var(--muted-foreground)]">薄弱模块<input className="w-full rounded-lg border bg-transparent px-3 py-2 text-sm text-[var(--foreground)]" value={draft.weak_modules.join("，")} onChange={(e) => onDraftChange({ ...draft, weak_modules: splitTextList(e.target.value) })} /></label><DraftTags title="优势" items={draft.strengths} /><DraftTags title="风险" items={draft.risk_flags} /><DraftTags title="计划重点" items={draft.plan_focus} /><div className="grid gap-2 md:grid-cols-2">{Object.entries(draft.module_scores || {}).map(([name, score]) => <div key={name} className="rounded-md border border-[var(--border)] px-3 py-2 text-sm"><span className="text-[var(--muted-foreground)]">{name}</span><span className="float-right font-semibold">{score}</span></div>)}</div><MarkdownRenderer content={draft.reasoning_summary || "暂无诊断理由"} variant="compact" /><button onClick={onConfirm} disabled={loading === "confirm-diagnostic"} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)]">{loading === "confirm-diagnostic" ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />} 确认画像并生成计划</button></div> : null}</div>;
}

function DraftTags({ title, items }: { title: string; items: string[] }) { if (!items?.length) return null; return <div className="flex flex-wrap gap-2 text-xs"><span className="py-1 text-[var(--muted-foreground)]">{title}</span>{items.map((item) => <span key={item} className="rounded-full border border-[var(--border)] px-2 py-1">{item}</span>)}</div>; }

function QuestionAnswer({ question, index, answer, imageAnswer, onAnswer, onImage, onAskAI, loading }: { question: ContentQuestion; index: number; answer: string; imageAnswer?: string; onAnswer: (answer: string) => void; onImage: (event: ChangeEvent<HTMLInputElement>) => void; onAskAI?: () => void; loading?: string | null }) {
  const choice = isChoiceQuestion(question); const options = question.options || []; const content = choice && options.length ? question.stem_without_options || question.stem : question.stem;
  return <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"><div className="mb-3 flex flex-wrap items-start justify-between gap-2"><div className="text-sm text-[var(--muted-foreground)]">第 {index + 1} 题 · {question.question_type} · 难度 {question.difficulty_level}</div>{onAskAI ? <button onClick={onAskAI} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-[var(--muted)]" disabled={loading === `chat-${question.question_id}`}><MessageCircleQuestion size={13} /> AI解析本题</button> : null}</div><MarkdownRenderer content={content} variant="compact" />{choice && options.length ? <div className="mt-3 grid gap-2 md:grid-cols-2">{options.map((option) => { const active = answer === option.label; return <button key={option.label} type="button" onClick={() => onAnswer(option.label)} className={`rounded-lg border px-3 py-2 text-left text-sm transition-colors ${active ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]" : "hover:bg-[var(--muted)]"}`}><div className="flex gap-2"><span className="font-semibold">{option.label}.</span><MarkdownRenderer content={option.content} variant="compact" /></div></button>; })}</div> : <div className="mt-3 space-y-3"><textarea className="min-h-24 w-full rounded-lg border bg-transparent px-3 py-2 text-sm" placeholder="输入最终答案、关键步骤或解题思路" value={answer} onChange={(e) => onAnswer(e.target.value)} /><label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-[var(--muted)]"><Upload size={15} /> 上传手写图片<input className="hidden" type="file" accept="image/*" onChange={onImage} /></label>{imageAnswer ? <div className="text-xs text-emerald-600">已附加图片答案，提交时会一并送入判分请求。</div> : null}</div>}</div>;
}

function KnowledgeTree({ nodes, selectedId, onSelect, level = 0 }: { nodes: KnowledgeNode[]; selectedId: string; onSelect: (id: string) => void; level?: number }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  return <div className="space-y-1">{nodes.map((node) => { const hasChildren = Boolean(node.children?.length); const expanded = open[node.knowledge_id] ?? level < 2; const selectable = isSelectableKnowledge(node); const active = selectedId === node.knowledge_id; return <div key={node.knowledge_id}><div className="flex items-center gap-1" style={{ paddingLeft: `${level * 14}px` }}><button type="button" onClick={() => hasChildren && setOpen((prev) => ({ ...prev, [node.knowledge_id]: !expanded }))} className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--muted)]" aria-label={expanded ? "收起" : "展开"}>{hasChildren ? expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} /> : <span className="h-1.5 w-1.5 rounded-full bg-[var(--muted-foreground)]/50" />}</button><button type="button" onClick={() => selectable && onSelect(node.knowledge_id)} className={`min-w-0 flex-1 rounded-md px-2 py-2 text-left text-sm ${active ? "bg-[var(--foreground)] text-[var(--background)]" : selectable ? "hover:bg-[var(--muted)]" : "text-[var(--muted-foreground)]"}`}><div className="truncate font-medium">{node.knowledge_name}</div>{node.full_path ? <div className="truncate text-xs opacity-70">{node.section || node.node_type}</div> : null}</button></div>{hasChildren && expanded ? <KnowledgeTree nodes={node.children} selectedId={selectedId} onSelect={onSelect} level={level + 1} /> : null}</div>; })}</div>;
}
function TaskPanel({ tasks, loading, onStatus, onPractice }: { tasks: PlanTask[]; loading: string | null; onStatus: (task: PlanTask, status: string) => void; onPractice: () => void }) { return <section className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-5"><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold">今日任务</h2><button onClick={onPractice} className="rounded-lg border px-3 py-2 text-sm">开始专项练习</button></div>{tasks.length === 0 ? <Empty text="还没有任务。先完成诊断并确认画像，再生成计划。" /> : <div className="space-y-3">{tasks.map((task) => <div key={task.task_id} className="rounded-lg border border-[var(--border)]/70 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="font-medium">{task.title}</div><div className="mt-1 text-sm text-[var(--muted-foreground)]">{task.description}</div><div className="mt-2 text-xs text-[var(--muted-foreground)]">{task.task_type} · {task.estimated_minutes} 分钟 · {task.status}</div></div><button onClick={() => onStatus(task, task.status === "completed" ? "pending" : "completed")} className="inline-flex items-center gap-2 rounded-lg bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)]" disabled={loading === task.task_id}>{loading === task.task_id ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}{task.status === "completed" ? "重开" : "完成"}</button></div></div>)}</div>}</section>; }

function KnowledgePanel({ detail, loading, onPractice, onAskAI }: { detail: KnowledgeDetail | null; loading: string | null; onPractice: () => void; onAskAI: (knowledgeId: string) => void }) {
  if (!detail) return <Empty text="选择一个知识点查看内容。" />; const knowledgeId = detail.knowledge.knowledge_id;
  return <section className="space-y-4"><div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-5"><div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{detail.knowledge.knowledge_name}</h2><p className="text-sm text-[var(--muted-foreground)]">{detail.knowledge.full_path || detail.knowledge.section || detail.knowledge.chapter} · 重要度 {detail.knowledge.importance_level}</p></div><div className="flex flex-wrap gap-2"><button onClick={() => onAskAI(knowledgeId)} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm" disabled={loading === `chat-${knowledgeId}`}><MessageCircleQuestion size={15} /> AI解析</button><button onClick={onPractice} className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)]">练这个知识点</button></div></div>{detail.knowledge.raw_markdown ? <MarkdownRenderer content={detail.knowledge.raw_markdown} variant="compact" /> : null}</div><div className="grid gap-4 lg:grid-cols-2"><InfoList title="公式" items={detail.formulas.map((item) => `${item.formula_name}\n\n${item.formula_content}\n\n${item.usage_scene || ""}`)} /><InfoList title="易错点" items={detail.mistakes.map((item) => `${item.mistake_content}\n\n${item.correction_method || ""}`)} /></div>{detail.questions.length ? <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"><h3 className="mb-3 font-semibold">相关题型</h3><div className="space-y-3">{detail.questions.slice(0, 3).map((question, index) => <QuestionPreview key={question.question_id} question={question} index={index} onAskAI={() => onAskAI(knowledgeId)} />)}</div></div> : null}</section>;
}
function QuestionPreview({ question, index, onAskAI }: { question: ContentQuestion; index: number; onAskAI: () => void }) { return <div className="rounded-md border border-[var(--border)]/70 p-3"><div className="mb-2 flex items-center justify-between gap-2 text-sm text-[var(--muted-foreground)]"><span>样题 {index + 1} · {question.question_type}</span><button onClick={onAskAI} className="rounded-md border px-2 py-1 text-xs">AI解析知识点</button></div><MarkdownRenderer content={question.stem_without_options || question.stem} variant="compact" /></div>; }
function InfoList({ title, items }: { title: string; items: string[] }) { return <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"><h3 className="mb-3 font-semibold">{title}</h3>{items.length ? <div className="space-y-3">{items.slice(0, 5).map((item, index) => <MarkdownRenderer key={index} content={item} variant="compact" />)}</div> : <div className="text-sm text-[var(--muted-foreground)]">暂无内容</div>}</div>; }

function PracticePanel({ practice, answers, imageAnswers, result, loading, onAnswer, onImage, onCreate, onRetry, onSubmit, onAskAI }: { practice: PracticeSession | null; answers: Record<string, string>; imageAnswers: Record<string, string>; result: PracticeResult | null; loading: string | null; onAnswer: (questionId: string, answer: string) => void; onImage: (questionId: string, event: ChangeEvent<HTMLInputElement>) => void; onCreate: () => void; onRetry: () => void; onSubmit: () => void; onAskAI: (questionId: string) => void }) { return <section className="space-y-4"><div className="flex flex-wrap gap-2"><button onClick={onCreate} className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)]">新建专项练习</button><button onClick={onRetry} className="rounded-lg border px-3 py-2 text-sm">错题二刷</button></div>{!practice ? <Empty text="选择知识点后开始练习；选择题可点击选项，填空/解答题可输入文字或上传图片，提交后由 AI 辅助判分。" /> : <div className="space-y-4"><h2 className="text-lg font-semibold">{practice.title}</h2>{practice.questions.map((question, index) => <QuestionAnswer key={question.question_id} question={question} index={index} answer={answers[question.question_id] || ""} imageAnswer={imageAnswers[question.question_id]} onAnswer={(answer) => onAnswer(question.question_id, answer)} onImage={(event) => onImage(question.question_id, event)} onAskAI={() => onAskAI(question.question_id)} loading={loading} />)}<button onClick={onSubmit} disabled={loading === "submit-practice"} className="inline-flex items-center gap-2 rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm text-[var(--background)]">{loading === "submit-practice" ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />} 提交练习</button></div>}{result ? <PracticeResultPanel result={result} /> : null}</section>; }
function PracticeResultPanel({ result }: { result: PracticeResult }) { return <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-5"><h3 className="text-lg font-semibold">练习反馈：{result.correct_count}/{result.total_count}</h3><p className="mt-2 text-sm text-[var(--muted-foreground)]">正确率 {pct(result.accuracy)}</p><MarkdownRenderer content={result.analysis_summary} variant="compact" /><div className="mt-3 space-y-2">{result.answers.map((item) => <div key={item.question_id} className="rounded-md border border-[var(--border)]/70 p-3 text-sm"><div className={item.is_correct ? "text-emerald-600" : "text-[var(--destructive)]"}>{item.question_id} · {item.is_correct ? "正确" : "错误"} · {item.error_reason} · {item.grading_method || "graded"}</div><MarkdownRenderer content={item.ai_analysis} variant="compact" /></div>)}</div></div>; }
function WrongCard({ item, loading, onAskAI }: { item: WrongQuestion; loading: string | null; onAskAI: (questionId: string) => void }) { return <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"><div className="mb-2 flex flex-wrap items-center justify-between gap-2"><div className="font-medium">{item.question_id}</div><div className="flex items-center gap-2"><div className="text-xs text-[var(--muted-foreground)]">错 {item.wrong_count} 次 · {item.review_status}</div><button onClick={() => onAskAI(item.question_id)} disabled={loading === `chat-${item.question_id}`} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-[var(--muted)]"><MessageCircleQuestion size={13} /> AI解析</button></div></div>{item.question ? <MarkdownRenderer content={item.question.stem_without_options || item.question.stem} variant="compact" /> : null}<div className="mt-2 text-sm text-[var(--destructive)]">错因：{item.error_reason}</div></div>; }

function ReportsPanel({ reports, loading, onConfirm }: { reports: DiagnosticReport[]; loading: string | null; onConfirm: (reportId: string) => void }) {
  return <section className="space-y-3"><h2 className="text-lg font-semibold">诊断历史报告</h2>{reports.length === 0 ? <Empty text="暂无诊断报告。完成一次入门诊断后，这里会保存画像草案和模块分数。" /> : reports.map((report) => <div key={report.report_id} className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="font-medium">{report.mode === "deep" ? "30 分钟深诊断" : "5 分钟轻诊断"}</div><div className="mt-1 text-xs text-[var(--muted-foreground)]">{new Date(report.created_at).toLocaleString()} · {report.confirmed ? "已确认" : "未确认"}</div></div><div className="flex items-center gap-3"><div className="text-sm font-semibold">{Math.round((report.answer_summary?.accuracy || 0) * 100)}%</div>{!report.confirmed ? <button onClick={() => onConfirm(report.report_id)} disabled={loading === `report-${report.report_id}`} className="inline-flex items-center gap-2 rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs text-[var(--primary-foreground)]">{loading === `report-${report.report_id}` ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />} 确认画像</button> : null}</div></div><p className="mt-3 text-sm text-[var(--muted-foreground)]">{report.summary}</p><div className="mt-3 grid gap-2 md:grid-cols-2">{Object.entries(report.profile_draft?.module_scores || {}).map(([name, score]) => <div key={name} className="rounded-md border border-[var(--border)] px-3 py-2 text-sm"><span>{name}</span><span className="float-right font-semibold">{score}</span></div>)}</div><DraftTags title="薄弱模块" items={report.profile_draft?.weak_modules || []} /><DraftTags title="计划重点" items={report.profile_draft?.plan_focus || []} /></div>)}</section>;
}
function ReviewPanel({ reviews, onReview }: { reviews: ReviewItem[]; onReview: (review: ReviewItem, status: "reviewed" | "mastered" | "failed") => void }) { return <section className="space-y-3"><h2 className="text-lg font-semibold">今日复习队列</h2>{reviews.length === 0 ? <Empty text="暂无待复习项。错题和低掌握度知识点会自动进入队列。" /> : reviews.map((review) => <div key={review.review_id} className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="font-medium">{review.title}</div><div className="text-xs text-[var(--muted-foreground)]">优先级 {review.priority_score.toFixed(1)} · 已复习 {review.review_count} 次</div></div><div className="flex gap-2"><button onClick={() => onReview(review, "failed")} className="rounded-md border px-3 py-1.5 text-xs">仍不熟</button><button onClick={() => onReview(review, "reviewed")} className="rounded-md border px-3 py-1.5 text-xs">已复习</button><button onClick={() => onReview(review, "mastered")} className="rounded-md bg-[var(--foreground)] px-3 py-1.5 text-xs text-[var(--background)]">已掌握</button></div></div><div className="mt-3 grid gap-3 lg:grid-cols-2"><MarkdownRenderer content={review.prompt || "暂无正面内容"} variant="compact" /><MarkdownRenderer content={review.answer || "暂无背面内容"} variant="compact" /></div></div>)}</section>; }
function Empty({ text }: { text: string }) { return <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--card)] p-6 text-sm text-[var(--muted-foreground)]">{text}</div>; }