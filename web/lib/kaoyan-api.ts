import { apiUrl } from "@/lib/api";
import type {
  DashboardSummary,
  DiagnosticResult,
  DiagnosticReport,
  KaoyanChatContext,
  RagQueryResult,
  PlanReorderResult,
  MaterialParseTask,
  MasteryRecord,
  ExamSubmitResult,
  ExamSimulation,
  KaoyanProfile,
  KnowledgeDetail,
  KnowledgeNode,
  PlanTask,
  PracticeResult,
  PracticeSession,
  ReviewItem,
  StudyPlan,
  WrongQuestion,
} from "@/lib/kaoyan-types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getKnowledgeTree(): Promise<KnowledgeNode[]> {
  return request<KnowledgeNode[]>("/api/v1/kaoyan/content/knowledge-tree");
}

export function getKnowledgeDetail(knowledgeId: string): Promise<KnowledgeDetail> {
  return request<KnowledgeDetail>(`/api/v1/kaoyan/content/knowledge/${knowledgeId}`);
}

export function initProfile(profile: KaoyanProfile): Promise<KaoyanProfile> {
  return request<KaoyanProfile>("/api/v1/kaoyan/profile/init", {
    method: "POST",
    body: JSON.stringify(profile),
  });
}

export function getDashboardSummary(): Promise<DashboardSummary> {
  return request<DashboardSummary>("/api/v1/kaoyan/dashboard/summary");
}

export function generatePlan(): Promise<StudyPlan> {
  return request<StudyPlan>("/api/v1/kaoyan/plans/generate", { method: "POST" });
}


export function reorderPlan(input: {
  trigger_reason?: string;
  completion_rate?: number;
  mastery_scores?: Record<string, number>;
  remaining_days?: number;
} = {}): Promise<PlanReorderResult> {
  return request<PlanReorderResult>("/api/v1/kaoyan/plans/reorder", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
export function getTodayTasks(): Promise<PlanTask[]> {
  return request<PlanTask[]>("/api/v1/kaoyan/tasks/today");
}

export function updateTaskStatus(taskId: string, status: string): Promise<PlanTask> {
  return request<PlanTask>(`/api/v1/kaoyan/tasks/${taskId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function createDiagnosticSession(input: {
  mode: "light" | "deep";
  profile?: Partial<KaoyanProfile>;
}): Promise<PracticeSession> {
  return request<PracticeSession>("/api/v1/kaoyan/diagnostic/session", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function submitDiagnostic(
  sessionId: string,
  answers: Array<{ question_id: string; answer: string; image_data_url?: string }>,
): Promise<DiagnosticResult> {
  return request<DiagnosticResult>(`/api/v1/kaoyan/diagnostic/${sessionId}/submit`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  });
}

export function createKaoyanChatContext(input: {
  source_type: "knowledge" | "question";
  source_id: string;
  intent?: string;
}): Promise<KaoyanChatContext> {
  return request<KaoyanChatContext>("/api/v1/kaoyan/chat-context", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createPracticeSession(input: {
  session_type?: "special" | "wrong_retry" | "similar";
  knowledge_id?: string;
  source_question_id?: string;
  question_type?: string;
  difficulty_level?: number;
  limit?: number;
}): Promise<PracticeSession> {
  return request<PracticeSession>("/api/v1/kaoyan/practice/session", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function submitPractice(
  sessionId: string,
  answers: Array<{ question_id: string; answer: string; image_data_url?: string }>,
): Promise<PracticeResult> {
  return request<PracticeResult>(`/api/v1/kaoyan/practice/${sessionId}/submit`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  });
}

export function getWrongQuestions(): Promise<WrongQuestion[]> {
  return request<WrongQuestion[]>("/api/v1/kaoyan/wrong-questions");
}

export function getReviewsToday(): Promise<ReviewItem[]> {
  return request<ReviewItem[]>("/api/v1/kaoyan/reviews/today");
}

export function submitReview(reviewId: string, status: "reviewed" | "mastered" | "failed"): Promise<ReviewItem> {
  return request<ReviewItem>(`/api/v1/kaoyan/reviews/${reviewId}/submit`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
}

export function createMaterialParseTask(input: { filename: string; content_type?: string }): Promise<MaterialParseTask> {
  return request<MaterialParseTask>("/api/v1/kaoyan/materials/parse", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getMaterialParseTask(taskId: string): Promise<MaterialParseTask> {
  return request<MaterialParseTask>(`/api/v1/kaoyan/materials/tasks/${taskId}`);
}

export function queryKaoyanRag(input: { kb_name: string; query: string }): Promise<RagQueryResult> {
  return request<RagQueryResult>("/api/v1/kaoyan/rag/query", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createExamSimulation(input: {
  subject?: string;
  year?: number;
  module?: string;
  knowledge_id?: string;
  question_type?: string;
  difficulty_level?: number;
  time_limit_minutes?: number;
  limit?: number;
}): Promise<ExamSimulation> {
  return request<ExamSimulation>("/api/v1/kaoyan/exam/simulation", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function submitExamSimulation(
  simulationId: string,
  answers: Array<{ question_id: string; answer: string; image_data_url?: string }>,
  elapsed_seconds?: number,
): Promise<ExamSubmitResult> {
  return request<ExamSubmitResult>(`/api/v1/kaoyan/exam/${simulationId}/submit`, {
    method: "POST",
    body: JSON.stringify({ answers, elapsed_seconds }),
  });
}

export function getMasteryRecords(input: {
  knowledge_id?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<{ records: MasteryRecord[]; limit: number; offset: number }> {
  const params = new URLSearchParams();
  if (input.knowledge_id) params.set("knowledge_id", input.knowledge_id);
  if (input.limit) params.set("limit", String(input.limit));
  if (input.offset) params.set("offset", String(input.offset));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<{ records: MasteryRecord[]; limit: number; offset: number }>(`/api/v1/kaoyan/mastery/records${suffix}`);
}
export function getDiagnosticReports(limit = 50, offset = 0): Promise<{ reports: DiagnosticReport[] }> {
  return request<{ reports: DiagnosticReport[] }>(`/api/v1/kaoyan/diagnostic/reports?limit=${limit}&offset=${offset}`);
}

export function getDiagnosticReport(reportId: string): Promise<DiagnosticReport> {
  return request<DiagnosticReport>(`/api/v1/kaoyan/diagnostic/reports/${reportId}`);
}

export function confirmDiagnosticReport(reportId: string): Promise<DiagnosticReport> {
  return request<DiagnosticReport>(`/api/v1/kaoyan/diagnostic/reports/${reportId}/confirm`, { method: "PATCH" });
}