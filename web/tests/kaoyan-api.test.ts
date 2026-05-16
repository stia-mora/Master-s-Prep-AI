import test from "node:test";
import assert from "node:assert/strict";

process.env.NEXT_PUBLIC_API_BASE = "http://localhost:8001";

(globalThis as { window?: unknown }).window = {
  location: { hostname: "localhost", protocol: "http:", host: "localhost:3000" },
};

type FetchCall = {
  url: string;
  init?: RequestInit;
};

const fetchCalls: FetchCall[] = [];

function mockFetch(body: unknown = {}) {
  fetchCalls.length = 0;
  (globalThis as { fetch: typeof fetch }).fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    fetchCalls.push({ url: String(input), init });
    return {
      ok: true,
      status: 200,
      json: async () => body,
      text: async () => JSON.stringify(body),
      blob: async () => new Blob([body instanceof Uint8Array ? Array.from(body).join("") : JSON.stringify(body)]),
    } as Response;
  }) as typeof fetch;
}

async function loadKaoyanApi(): Promise<typeof import("../lib/kaoyan-api")> {
  return import("../lib/kaoyan-api");
}

test("getProfile calls the current-user profile endpoint", async () => {
  const api = await loadKaoyanApi();
  mockFetch(null);

  const profile = await api.getProfile();

  assert.equal(profile, null);
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/profile/me");
  assert.equal(fetchCalls[0].init?.credentials, "include");
});

test("updateTaskStatus sends compatible task status payloads", async () => {
  const api = await loadKaoyanApi();
  mockFetch({ task_id: "task_1", status: "completed" });

  await api.updateTaskStatus("task_1", "done");

  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/tasks/task_1/status");
  assert.equal(fetchCalls[0].init?.method, "PATCH");
  assert.equal(fetchCalls[0].init?.body, JSON.stringify({ status: "done" }));
});

test("task date helpers query and create calendar todos", async () => {
  const api = await loadKaoyanApi();
  mockFetch([{ task_id: "task_1", due_at: "2026-05-14" }]);

  await api.getTasksByDate("2026-05-14");
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/tasks?date=2026-05-14");

  mockFetch({ task_id: "task_2", title: "Review" });
  await api.createTask({ title: "Review", due_at: "2026-05-14", estimated_minutes: 20 });
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/tasks");
  assert.equal(fetchCalls[0].init?.method, "POST");
  assert.equal(fetchCalls[0].init?.body, JSON.stringify({ title: "Review", due_at: "2026-05-14", estimated_minutes: 20 }));
});

test("diagnostic report helpers use the expected endpoints", async () => {
  const api = await loadKaoyanApi();
  mockFetch({ reports: [] });

  await api.getDiagnosticReports(10, 5);
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/diagnostic/reports?limit=10&offset=5");

  mockFetch({ report_id: "diagrep_1" });
  await api.getDiagnosticReport("diagrep_1");
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/diagnostic/reports/diagrep_1");

  mockFetch({ report_id: "diagrep_1", confirmed: true });
  await api.confirmDiagnosticReport("diagrep_1");
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/diagnostic/reports/diagrep_1/confirm");
  assert.equal(fetchCalls[0].init?.method, "PATCH");
});

test("practice helpers route choice sessions and free-response pdf payloads", async () => {
  const api = await loadKaoyanApi();
  mockFetch({ session_id: "prac_1", questions: [] });

  await api.createPracticeSession({ knowledge_id: "K_LIMIT", question_family: "choice", limit: 5 });
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/practice/session");
  assert.equal(fetchCalls[0].init?.method, "POST");
  assert.equal(fetchCalls[0].init?.body, JSON.stringify({ knowledge_id: "K_LIMIT", question_family: "choice", limit: 5 }));

  mockFetch({ title: "PDF", filename: "practice.pdf", questions: [] });
  await api.createPracticePdf({ knowledge_id: "K_LIMIT", limit: 8 });
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/practice/pdf");
  assert.equal(fetchCalls[0].init?.method, "POST");
  assert.equal(fetchCalls[0].init?.body, JSON.stringify({ knowledge_id: "K_LIMIT", limit: 8 }));

  mockFetch(new Uint8Array([37, 80, 68, 70]));
  const blob = await api.downloadPracticePdf({ knowledge_id: "K_LIMIT", question_ids: ["q_fill"], limit: 1 });
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/practice/pdf/download");
  assert.equal(fetchCalls[0].init?.method, "POST");
  assert.equal(fetchCalls[0].init?.body, JSON.stringify({ knowledge_id: "K_LIMIT", question_ids: ["q_fill"], limit: 1 }));
  assert.equal(blob.size > 0, true);
});

test("learning path helpers use the expected endpoints", async () => {
  const api = await loadKaoyanApi();
  mockFetch({ path_id: "path_1", stages: [] });

  await api.getLearningPath();
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/learning-path");

  await api.refreshLearningPath();
  assert.equal(fetchCalls[1].url, "/api/v1/kaoyan/learning-path/refresh");
  assert.equal(fetchCalls[1].init?.method, "POST");

  mockFetch({ practice_session: { session_id: "prac_1" } });
  await api.startStage("stage_1");
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/learning-path/stages/stage_1/start");
  assert.equal(fetchCalls[0].init?.method, "POST");

  mockFetch({ stage_id: "stage_1", mastery_score: 91, passed: true });
  await api.submitStage("stage_1", {
    practice_session_id: "prac_1",
    answers: [{ question_id: "q1", answer: "A" }],
  });
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/learning-path/stages/stage_1/submit");
  assert.equal(fetchCalls[0].init?.method, "POST");
  assert.equal(
    fetchCalls[0].init?.body,
    JSON.stringify({ practice_session_id: "prac_1", answers: [{ question_id: "q1", answer: "A" }] }),
  );
});

test("review helpers use calendar, hidden tests, and daily export endpoints", async () => {
  const api = await loadKaoyanApi();
  mockFetch({ start_date: "2026-05-14", end_date: "2026-05-14", days: [] });

  await api.getReviewsCalendar("2026-05-14", "2026-05-14");
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/reviews/calendar?start=2026-05-14&end=2026-05-14");

  mockFetch({ review_id: "rev_1", answer_hidden: true });
  await api.startReviewTest("rev_1");
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/reviews/rev_1/start-test");
  assert.equal(fetchCalls[0].init?.method, "POST");

  mockFetch({ review_id: "rev_1", is_correct: true });
  await api.submitReviewTest("rev_1", "A");
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/reviews/rev_1/submit-test");
  assert.equal(fetchCalls[0].init?.body, JSON.stringify({ answer: "A" }));

  mockFetch(new Uint8Array([37, 80, 68, 70]));
  const blob = await api.downloadDailyReviewPdf("2026-05-14");
  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/reviews/daily-export?date=2026-05-14&format=pdf");
  assert.equal(blob.size > 0, true);
});

test("dashboard summary returns compatible optional member A fields", async () => {
  const api = await loadKaoyanApi();
  mockFetch({
    task_total: 1,
    task_completed: 1,
    completion_rate: 1,
    practice_sessions: 0,
    accuracy: 0,
    wrong_count: 0,
    review_due_count: 0,
    mastery_average: 0,
    mastery_distribution: { low: 0, medium: 0, high: 0 },
    today_tasks: [{ task_id: "task_1", status: "completed" }],
    weak_knowledge_ids: ["K_LIMIT"],
  });

  const summary = await api.getDashboardSummary();

  assert.equal(fetchCalls[0].url, "/api/v1/kaoyan/dashboard/summary");
  assert.equal(summary.today_tasks?.[0]?.task_id, "task_1");
  assert.deepEqual(summary.weak_knowledge_ids, ["K_LIMIT"]);
});
