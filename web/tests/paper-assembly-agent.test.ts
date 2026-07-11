import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

function makeMathQuestionBank(): string {
  const lines = [
    "# 2024 年考研数学一真题",
    "",
  ];
  for (let number = 1; number <= 20; number += 1) {
    if (number <= 10) {
      lines.push(
        `${number}. 函数极限、矩阵或概率基础选择题 ${number}。A. 选项甲 B. 选项乙 C. 选项丙 D. 选项丁`,
      );
    } else {
      lines.push(`${number}. 计算函数极限、矩阵特征值或概率分布的综合解答题 ${number}，写出完整过程。`);
    }
    lines.push("");
  }
  return lines.join("\n");
}

test("paper assembly service loads a math template bank and builds a full exam-format paper", async () => {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), "paper-assembly-math-"));
  fs.writeFileSync(path.join(dataRoot, "2024年考研数学一真题.md"), makeMathQuestionBank(), "utf8");
  process.env.PAPER_ASSEMBLY_DATA_ROOT = dataRoot;

  const { paperAssemblyService } = await import("../lib/paper-assembly-agent/service");
  const health = paperAssemblyService.health();
  assert.equal(health.questionCount, 20);

  const paper = paperAssemblyService.assemble(
    { paper_mode: "by_real_exam_format", source_scope: "all" },
    "paper_assembly_test_user",
  );

  assert.equal(paper.mode, "by_real_exam_format");
  assert.equal(paper.questions.length, 20);
  assert.equal(paper.summary.totalPoints, 150);
});
