# Master Prep AI — Agent-Native Architecture

## Overview

Master Prep AI is an **agent-native** intelligent learning companion built around
a two-layer plugin model (Tools + Capabilities) with three entry points:
CLI, WebSocket API, and Python SDK.

## Architecture

```
Entry Points:  CLI (Typer)  |  WebSocket /api/v1/ws  |  Python SDK
                    ↓                   ↓                   ↓
              ┌─────────────────────────────────────────────────┐
              │              ChatOrchestrator                    │
              │   routes to ChatCapability (default)             │
              │   or a selected deep Capability                  │
              └──────────┬──────────────┬───────────────────────┘
                         │              │
              ┌──────────▼──┐  ┌────────▼──────────┐
              │ ToolRegistry │  │ CapabilityRegistry │
              │  (Level 1)   │  │   (Level 2)        │
              └──────────────┘  └────────────────────┘
```

### Level 1 — Tools

Lightweight single-function tools the LLM calls on demand:

| Tool                | Description                                    |
| ------------------- | ---------------------------------------------- |
| `rag`               | Knowledge base retrieval (RAG)                 |
| `web_search`        | Web search with citations                      |
| `code_execution`    | Sandboxed Python execution                     |
| `reason`            | Dedicated deep-reasoning LLM call              |
| `brainstorm`        | Breadth-first idea exploration with rationale  |
| `paper_search`      | arXiv academic paper search                    |
| `geogebra_analysis` | Image → GeoGebra commands (4-stage vision pipeline) |

### Level 2 — Capabilities

Multi-step agent pipelines that take over the conversation:

| Capability       | Stages                                         |
| ---------------- | ---------------------------------------------- |
| `chat`           | responding (default, tool-augmented)           |
| `deep_solve`     | planning → reasoning → writing                 |
| `deep_question`  | ideation → evaluation → generation → validation |

### Playground Plugins

Extended features in `master-prep-ai/plugins/`:

| Plugin            | Type       | Description                          |
| ----------------- | ---------- | ------------------------------------ |
| `deep_research`   | playground | Multi-agent research + reporting     |

## CLI Usage

```bash
# Install CLI
pip install -e ".[cli]"

# Run any capability (agent-first entry point)
master-prep-ai run chat "Explain Fourier transform"
master-prep-ai run deep_solve "Solve x^2=4" -t rag --kb my-kb
master-prep-ai run deep_question "Linear algebra" --config num_questions=5

# Interactive REPL
master-prep-ai chat
# (inside the REPL: /regenerate or /retry re-runs the last user message)

# Knowledge bases
master-prep-ai kb list
master-prep-ai kb create my-kb --doc textbook.pdf

# Plugins & memory
master-prep-ai plugin list
master-prep-ai memory show

# API server (requires .[server])
master-prep-ai serve --port 8001
```

## Key Files

| Path                          | Purpose                              |
| ----------------------------- | ------------------------------------ |
| `master-prep-ai/runtime/orchestrator.py` | ChatOrchestrator — unified entry     |
| `master-prep-ai/core/stream.py`          | StreamEvent protocol                 |
| `master-prep-ai/core/stream_bus.py`      | Async event fan-out                  |
| `master-prep-ai/core/tool_protocol.py`   | BaseTool abstract class              |
| `master-prep-ai/core/capability_protocol.py` | BaseCapability abstract class    |
| `master-prep-ai/core/context.py`         | UnifiedContext dataclass             |
| `master-prep-ai/runtime/registry/tool_registry.py` | Tool discovery & registration |
| `master-prep-ai/runtime/registry/capability_registry.py` | Capability discovery & registration |
| `master-prep-ai/runtime/mode.py`         | RunMode (CLI vs SERVER)              |
| `master-prep-ai/capabilities/`           | Built-in capability wrappers         |
| `master-prep-ai/tools/builtin/`          | Built-in tool wrappers               |
| `master-prep-ai/plugins/`                | Playground plugins                   |
| `master-prep-ai/plugins/loader.py`       | Plugin discovery from manifest.yaml  |
| `master-prep-ai_cli/main.py`             | Typer CLI entry point                |
| `master-prep-ai/api/routers/unified_ws.py` | Unified WebSocket endpoint         |

## Plugin Development

Create a directory under `master-prep-ai/plugins/<name>/` with:

```
manifest.yaml     # name, version, type, description, stages
capability.py     # class extending BaseCapability
```

Minimal `manifest.yaml`:
```yaml
name: my_plugin
version: 0.1.0
type: playground
description: "My custom plugin"
stages: [step1, step2]
```

Minimal `capability.py`:
```python
from master_prep_ai.core.capability_protocol import BaseCapability, CapabilityManifest
from master_prep_ai.core.context import UnifiedContext
from master_prep_ai.core.stream_bus import StreamBus

class MyPlugin(BaseCapability):
    manifest = CapabilityManifest(
        name="my_plugin",
        description="My custom plugin",
        stages=["step1", "step2"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        async with stream.stage("step1", source=self.name):
            await stream.content("Working on step 1...", source=self.name)
        await stream.result({"response": "Done!"}, source=self.name)
```

## Dependency Layers

Defined in `pyproject.toml` `[project.optional-dependencies]`. Mirrored as flat
lists in `requirements/*.txt` for Docker/CI installs without source code.

```
.[cli]            — CLI full (LLM + RAG + providers + document parsing)
.[server]         — .[cli] + FastAPI/uvicorn (for Web/API)
.[tutorbot]       — .[server] + TutorBot agent engine + channel SDKs
.[matrix]         — Matrix channel for TutorBot (matrix-nio[e2e]; needs libolm)
.[math-animator]  — Manim addon (for `master-prep-ai animate`)
.[dev]            — .[server] + test/lint tools
.[all]            — Everything above
```
