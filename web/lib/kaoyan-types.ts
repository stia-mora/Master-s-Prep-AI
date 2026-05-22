export interface KaoyanProfile {
  user_id?: string;
  target_school: string;
  target_major: string;
  exam_date: string;
  daily_minutes: number;
  target_score: number;
  baseline_level: string;
  weak_modules: string[];
  subjects?: string[];
  stage?: string;
  preferences?: Record<string, unknown>;
}

export interface KnowledgeNode {
  knowledge_id: string;
  subject: string;
  module: string;
  chapter?: string;
  section?: string;
  knowledge_name: string;
  parent_id?: string | null;
  importance_level: number;
  is_core: number;
  raw_markdown?: string;
  node_type?: string;
  full_path?: string;
  children: KnowledgeNode[];
}

export interface ChoiceOption {
  label: string;
  content: string;
}

export interface ContentQuestion {
  question_id: string;
  knowledge_id: string;
  question_type: string;
  difficulty_level: number;
  stem: string;
  stem_without_options?: string;
  options?: ChoiceOption[];
  is_choice?: boolean;
  answer?: string;
  analysis?: string;
  source?: string;
  source_type?: string;
  year?: number | null;
  diagnostic_signal?: string;
  estimated_seconds?: number;
}

export interface KnowledgeDetail {
  knowledge: Omit<KnowledgeNode, "children">;
  questions: ContentQuestion[];
  formulas: Array<{
    formula_id: string;
    formula_name: string;
    formula_content: string;
    usage_scene?: string;
    common_mistake?: string;
  }>;
  mistakes: Array<{
    mistake_id: string;
    mistake_content: string;
    trigger_condition?: string;
    correction_method?: string;
  }>;
  review_cards: Array<{
    card_id: string;
    card_type: string;
    front_content: string;
    back_content: string;
    review_interval?: number;
  }>;
}

export interface PlanTask {
  task_id: string;
  plan_id: string;
  task_type: "study" | "practice" | "review" | string;
  title: string;
  description: string;
  estimated_minutes: number;
  due_at: string;
  due_date?: string;
  status: "pending" | "in_progress" | "completed" | "skipped" | string;
  priority_score: number;
  priority?: number;
  related_knowledge_ids: string[];
  knowledge_ids?: string[];
}

export interface StudyPlan {
  plan_id: string;
  title: string;
  start_date: string;
  end_date: string;
  status: string;
  ai_status: string;
  ai_message: string;
  tasks: PlanTask[];
  ai_metadata?: { ai_used?: boolean; status?: string; message?: string };
}

export interface DashboardSummary {
  task_total: number;
  task_completed: number;
  completion_rate: number;
  practice_sessions: number;
  accuracy: number;
  wrong_count: number;
  review_due_count: number;
  mastery_average: number;
  mastery_distribution: { low: number; medium: number; high: number };
  profile?: KaoyanProfile | null;
  today_tasks?: PlanTask[];
  weak_modules?: string[];
  weak_knowledge_ids?: string[];
  recent_diagnostic_report?: DiagnosticReport | null;
  active_plan?: Omit<StudyPlan, "tasks"> | null;
  portrait_summary?: Record<string, unknown>;
  current_stage?: LearningStage | null;
  learning_path_status?: string;
}

export interface PracticeSession {
  session_id: string;
  title: string;
  session_type: string;
  knowledge_id: string;
  question_ids: string[];
  questions: ContentQuestion[];
  ai_metadata?: Record<string, unknown>;
}

export interface StageProgress {
  user_id: string;
  stage_id: string;
  mastery_score: number;
  passed: boolean;
  unlocked: boolean;
  attempt_count: number;
  last_reason: {
    summary?: string;
    blockers?: string[];
    metrics?: Record<string, number>;
    threshold?: number;
  };
  next_action: string;
  evidence: Array<Record<string, unknown>>;
  updated_at?: string;
}

export interface LearningStage {
  id: string;
  stage_id: string;
  path_id: string;
  user_id: string;
  knowledge_ids: string[];
  title: string;
  order_index: number;
  unlock_rule: Record<string, unknown>;
  pass_threshold: number;
  context: {
    stage_context?: Record<string, unknown>;
    weakness_tags?: string[];
    portrait_summary?: Record<string, unknown>;
  };
  progress: StageProgress;
  created_at?: string;
  updated_at?: string;
}

export interface LearningPath {
  id: string;
  path_id: string;
  user_id: string;
  status: string;
  goal: string;
  source_snapshot_id: string;
  portrait_summary: Record<string, unknown>;
  evidence: Array<Record<string, unknown>>;
  stages: LearningStage[];
  current_stage?: LearningStage | null;
  unlocked_stages?: LearningStage[];
  created_at?: string;
  updated_at?: string;
}

export interface StageStartResult {
  stage: LearningStage;
  practice_session: PracticeSession;
}

export interface StageSubmitResult {
  stage_id: string;
  mastery_score: number;
  passed: boolean;
  unlock_next_stage: boolean;
  next_action: string;
  reason: StageProgress["last_reason"];
  evidence: Array<Record<string, unknown>>;
  practice_result?: PracticeResult | null;
}

export type QuestionFamily = "choice" | "free_response";

export interface PracticePdfRequest {
  session_type?: "special" | "wrong_retry" | "similar";
  knowledge_id?: string;
  source_question_id?: string;
  question_ids?: string[];
  difficulty_level?: number;
  limit?: number;
}

export interface PracticePdfPayload {
  title: string;
  filename: string;
  questions: ContentQuestion[];
  session_type?: string;
  knowledge_id?: string;
  question_family?: QuestionFamily;
}

export interface PracticeAnswerResult {
  question_id: string;
  knowledge_id: string;
  user_answer: string;
  correct_answer: string;
  is_correct: boolean;
  ai_analysis: string;
  error_reason: string;
  grading_method?: string;
  has_image_answer?: boolean;
}

export interface PracticeResult {
  record_id: string;
  practice_id: string;
  total_count: number;
  correct_count: number;
  accuracy: number;
  analysis_summary: string;
  next_actions: string[];
  wrong_question_ids: string[];
  ai_metadata?: { ai_used?: boolean; message?: string };
  answers: PracticeAnswerResult[];
}

export interface ProfileDraft {
  baseline_level: string;
  weak_modules: string[];
  module_scores: Record<string, number>;
  strengths: string[];
  risk_flags: string[];
  recommended_daily_minutes: number;
  plan_focus: string[];
  reasoning_summary: string;
}

export interface DiagnosticResult {
  session_id: string;
  record_id: string;
  summary: string;
  profile_draft: ProfileDraft;
  answers: PracticeAnswerResult[];
  mastery_updates: Array<{ knowledge_id: string; mastery_score?: number; is_correct?: boolean }>;
  ai_metadata?: { ai_used?: boolean; status?: string; message?: string };
  report?: DiagnosticReport;
}


export interface DiagnosticReport {
  report_id: string;
  user_id: string;
  session_id: string;
  subject?: string;
  mode: "light" | "deep" | string;
  profile_snapshot: Partial<KaoyanProfile>;
  answer_summary: {
    total?: number;
    correct?: number;
    accuracy?: number;
    answers?: PracticeAnswerResult[];
  };
  profile_draft: ProfileDraft;
  weak_knowledge_ids?: string[];
  score_summary?: {
    total?: number;
    correct?: number;
    wrong?: number;
    accuracy?: number;
  };
  recommendations?: string[];
  summary: string;
  confirmed: boolean;
  created_at: string;
  updated_at: string;
}
export interface KaoyanChatContext {
  title: string;
  initial_message: string;
  context_payload: Record<string, unknown>;
  question_entry?: { id?: number | string; question_id?: string };
  rag?: {
    ready: boolean;
    kb_name: string;
    status: string;
    message: string;
  };
}

export interface WrongQuestion {
  wrong_id: string;
  question_id: string;
  knowledge_id: string;
  question_type?: string;
  error_reason: string;
  wrong_reason?: string;
  wrong_count: number;
  retry_count?: number;
  manual_wrong_reason?: string;
  ai_wrong_reason?: string;
  is_focus?: boolean;
  last_retry_at?: string | null;
  last_result?: string;
  review_status: string;
  wrong_status?: string;
  selected_supported?: boolean;
  last_wrong_at: string;
  next_review_at: string;
  question?: ContentQuestion | null;
}

export interface WrongQuestionDistributionItem {
  key: string;
  count: number;
}

export interface WrongQuestionSummary {
  total: number;
  unmastered: number;
  focus_count: number;
  pending_retry: number;
  by_knowledge: WrongQuestionDistributionItem[];
  by_question_type: WrongQuestionDistributionItem[];
  by_wrong_reason: WrongQuestionDistributionItem[];
  wrong_count_top10: WrongQuestion[];
  repeated_wrong_questions: WrongQuestion[];
}

export interface ReviewItem {
  review_id: string;
  source_type: string;
  source_id: string;
  knowledge_id: string;
  title: string;
  prompt: string;
  answer: string;
  priority_score: number;
  next_review_at: string;
  review_count: number;
  status: string;
}
export interface PlanReorderResult {
  old_task_order: string[];
  new_task_order: string[];
  reason: string;
  adjustment_summary: string;
  need_confirm: boolean;
  plan_task_version: Record<string, unknown>;
}

export interface MaterialParseTask {
  task_id: string;
  filename: string;
  content_type: string;
  status: string;
  progress?: number;
  retry_count: number;
  fail_reason: string;
  created_at: string;
  updated_at?: string;
}

export interface RagQueryResult {
  kb_name: string;
  query: string;
  status?: string;
  answer?: string;
  results: unknown[];
  fallback?: string;
  error?: string;
  raw?: Record<string, unknown>;
}

export interface MasteryRecord {
  mastery_id: string;
  user_id: string;
  knowledge_id: string;
  mastery_score: number;
  attempts: number;
  correct_count: number;
  wrong_count: number;
  last_practiced_at?: string | null;
  updated_at: string;
}

export interface ExamSimulation {
  simulation_id: string;
  status: "reserved" | string;
  subject: string;
  year?: number | null;
  module: string;
  time_limit_minutes: number;
  practice_session: PracticeSession;
  questions: ContentQuestion[];
  score_report?: unknown;
}

export interface ExamSubmitResult {
  simulation_id: string;
  elapsed_seconds?: number | null;
  score_report: {
    total_count: number;
    correct_count: number;
    accuracy: number;
    analysis_summary: string;
    next_actions: string[];
  };
  practice_result: PracticeResult;
}
