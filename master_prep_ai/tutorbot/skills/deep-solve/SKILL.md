---
name: deep-solve
description: "Multi-stage problem solving via Master Prep AI (plan → reason → write)."
metadata: {"nanobot":{"emoji":"🧠","requires":{"bins":["master_prep_ai"]}}}
always: false
---

# Deep Solve

Use the `exec` tool to invoke Master Prep AI's multi-stage solver for complex math, science, or engineering problems.

## When to Use

- User asks to **prove** something, **derive** a formula, or **solve** a hard problem
- The problem requires structured multi-step reasoning
- A direct answer would be insufficient or unreliable

## Command

```bash
master_prep_ai run deep_solve "<problem description>" --format json -l <lang>
```

### Options

| Flag | Description |
|------|-------------|
| `-l <lang>` | Response language: `en` or `zh` |
| `-t rag` | Enable RAG to ground in knowledge base |
| `-t web_search` | Enable web search |
| `-t code_execution` | Enable code verification |
| `-t reason` | Enable dedicated reasoning |
| `--kb <name>` | Knowledge base to use with RAG |
| `--config detailed_answer=false` | Return a concise answer |

## Examples

Prove a theorem:
```bash
master_prep_ai run deep_solve "Prove that for any positive integer n, n³ - n is divisible by 6" --format json -l en
```

Solve with knowledge base:
```bash
master_prep_ai run deep_solve "Derive the Euler-Lagrange equation" --format json -l en -t rag --kb physics-textbook
```

Solve with code verification:
```bash
master_prep_ai run deep_solve "Find all roots of x⁴ - 5x² + 4 = 0" --format json -l en -t code_execution
```

## Important

- Deep solve can take **over a minute** — use `timeout=300` with the `exec` tool.
- The `--format json` flag outputs NDJSON stream events. Parse the `content` field from lines with `"type": "content"` to get the final answer. Concatenate all content events for the full response.
