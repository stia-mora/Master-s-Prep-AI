import test from "node:test";
import assert from "node:assert/strict";

import {
  isChoiceQuizQuestion,
  normalizeQuizQuestionType,
  resolveChoiceAnswerKey,
} from "../lib/quiz-question-type";
import { extractQuizQuestions } from "../lib/quiz-types";

test("normalizeQuizQuestionType maps legacy choice aliases to choice", () => {
  assert.equal(normalizeQuizQuestionType("choice"), "choice");
  assert.equal(normalizeQuizQuestionType("multiple_choice"), "choice");
  assert.equal(normalizeQuizQuestionType("multiple choice"), "choice");
  assert.equal(normalizeQuizQuestionType("mcq"), "choice");
  assert.equal(isChoiceQuizQuestion("multiple_choice"), true);
});

test("normalizeQuizQuestionType keeps written and coding families stable", () => {
  assert.equal(normalizeQuizQuestionType("written"), "written");
  assert.equal(normalizeQuizQuestionType("fill_in_blank"), "written");
  assert.equal(normalizeQuizQuestionType("coding"), "coding");
  assert.equal(normalizeQuizQuestionType("programming"), "coding");
});

test("resolveChoiceAnswerKey accepts either the option key or label text", () => {
  const options = {
    A: "Alpha",
    B: "Beta",
    C: "Gamma",
    D: "Delta",
  };

  assert.equal(resolveChoiceAnswerKey("C", options), "C");
  assert.equal(resolveChoiceAnswerKey("gamma", options), "C");
});

test("extractQuizQuestions normalizes legacy question types from payloads", () => {
  const questions = extractQuizQuestions({
    summary: {
      results: [
        {
          qa_pair: {
            question_id: "q_1",
            question: "Pick the best answer.",
            question_type: "multiple_choice",
            options: { A: "One", B: "Two", C: "Three", D: "Four" },
            correct_answer: "B",
            explanation: "Because two is correct.",
          },
        },
      ],
    },
  });

  assert.ok(questions);
  assert.equal(questions?.[0]?.question_type, "choice");
});
