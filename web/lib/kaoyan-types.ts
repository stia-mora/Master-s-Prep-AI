export interface KaoyanProfile {
  user_id?: string;
  target_school: string;
  target_major: string;
  exam_date: string;
  daily_minutes: number;
  target_score: number;
  baseline_level: string;
  weak_modules: string[];
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
  status: "pending" | "in_progress" | "completed" | "skipped" | string;
  priority_score: number;
  related_knowledge_ids: string[];
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
  mode: "light" | "deep" | string;
  profile_snapshot: Partial<KaoyanProfile>;
  answer_summary: {
    total?: number;
    correct?: number;
    accuracy?: number;
    answers?: PracticeAnswerResult[];
  };
  profile_draft: ProfileDraft;
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
  error_reason: string;
  wrong_count: number;
  review_status: string;
  last_wrong_at: string;
  next_review_at: string;
  question?: ContentQuestion | null;
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