import test from "node:test";
import assert from "node:assert/strict";

import { paperAssemblyService } from "../lib/paper-assembly-agent/service";

test("paper assembly service loads 408 bank and builds a full exam-format paper", () => {
  const health = paperAssemblyService.health();
  assert.ok(Number(health.questionCount) > 100, `expected parsed questions, got ${health.questionCount}`);

  const paper = paperAssemblyService.assemble(
    { paper_mode: "by_real_exam_format", source_scope: "all" },
    "paper_assembly_test_user",
  );

  assert.equal(paper.mode, "by_real_exam_format");
  assert.equal(paper.questions.length, 47);
  assert.equal(paper.summary.totalPoints, 150);
});
