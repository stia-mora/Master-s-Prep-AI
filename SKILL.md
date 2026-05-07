# Master Prep AI CLI Skill

> Teach your AI agent to configure, manage, and use Master Prep AI — an intelligent learning platform — entirely through the command line.

## When to Use

Use this skill when the user wants to:
- Set up or configure Master Prep AI
- Chat with Master Prep AI or run a capability (deep solve, quiz generation, deep research, math animation)
- Create, manage, or search knowledge bases
- Manage TutorBot instances
- View or manage learning memory, sessions, or notebooks
- Start the Master Prep AI API server

## Prerequisites

- Python 3.11+
- Master Prep AI installed: `pip install -e ".[cli]"` (CLI + RAG + providers) or `pip install -e ".[server]"` (adds web/API)
- Run `python scripts/start_tour.py` for first-time interactive setup (configures LLM, embedding, search providers and writes `.env`)

## Commands

### Chat & Capabilities

```bash
# Interactive REPL
master-prep-ai chat
master-prep-ai chat --capability deep_solve --kb my-kb --tool rag --tool web_search

# One-shot capability execution
master-prep-ai run chat "Explain Fourier transform"
master-prep-ai run deep_solve "Solve x^2 = 4" --tool rag --kb textbook
master-prep-ai run deep_question "Linear algebra" --config num_questions=5
master-prep-ai run deep_research "Attention mechanisms" --kb papers
master-prep-ai run math_animator "Visualize a Fourier series"

# Options for `run`:
#   --session <id>         Resume existing session
#   --tool/-t <name>       Enable tool (repeatable): rag, web_search, code_execution, reason, brainstorm, paper_search
#   --kb <name>            Knowledge base (repeatable)
#   --notebook-ref <ref>   Notebook reference (repeatable)
#   --history-ref <id>     Referenced session id (repeatable)
#   --language/-l <code>   Response language (default: en)
#   --config <key=value>   Capability config (repeatable)
#   --config-json <json>   Capability config as JSON
#   --format/-f <fmt>      Output format: rich | json
```

### Knowledge Bases

```bash
master-prep-ai kb list                              # List all knowledge bases
master-prep-ai kb info <name>                       # Show knowledge base details
master-prep-ai kb create <name> --doc file.pdf      # Create from documents (--doc repeatable)
master-prep-ai kb add <name> --doc more.pdf         # Add documents incrementally
master-prep-ai kb search <name> "query text"        # Search a knowledge base
master-prep-ai kb set-default <name>                # Set as default KB
master-prep-ai kb delete <name> [--force]           # Delete a knowledge base
```

### TutorBot

```bash
master-prep-ai bot list                             # List all TutorBot instances
master-prep-ai bot create <id> --name "My Tutor"    # Create and start a new bot
master-prep-ai bot start <id>                       # Start a bot
master-prep-ai bot stop <id>                        # Stop a bot
```

### Memory

```bash
master-prep-ai memory show [summary|profile|all]    # View learning memory
master-prep-ai memory clear [summary|profile|all]   # Clear memory (--force to skip confirm)
```

### Sessions

```bash
master-prep-ai session list [--limit 20]            # List sessions
master-prep-ai session show <id>                    # View session messages
master-prep-ai session open <id>                    # Resume session in REPL
master-prep-ai session rename <id> --title "..."    # Rename a session
master-prep-ai session delete <id>                  # Delete a session
```

### Notebooks

```bash
master-prep-ai notebook list                        # List notebooks
master-prep-ai notebook create <name>               # Create a notebook
master-prep-ai notebook show <id>                   # View notebook records
master-prep-ai notebook add-md <id> <file.md>       # Import markdown as record
master-prep-ai notebook replace-md <id> <rec> <f>   # Replace a markdown record
master-prep-ai notebook remove-record <id> <rec>    # Remove a record
```

### System

```bash
master-prep-ai config show                          # Print current configuration
master-prep-ai plugin list                          # List registered tools and capabilities
master-prep-ai plugin info <name>                   # Show tool/capability details
master-prep-ai provider login <provider>            # OAuth login (openai-codex, github-copilot)
master-prep-ai serve [--port 8001] [--reload]       # Start API server
```

## REPL Slash Commands

Inside `master-prep-ai chat`, use these:

| Command | Effect |
|:---|:---|
| `/quit` | Exit REPL |
| `/session` | Show current session id |
| `/new` | Start a new session |
| `/tool on\|off <name>` | Toggle a tool |
| `/cap <name>` | Switch capability |
| `/kb <name>\|none` | Set or clear knowledge base |
| `/history add <id>` / `/history clear` | Manage history references |
| `/notebook add <ref>` / `/notebook clear` | Manage notebook references |
| `/refs` | Show active references |
| `/config show\|set\|clear` | Manage capability config |

## Typical Workflows

**First-time setup:**
```bash
cd Master Prep AI
pip install -e ".[server]"
python scripts/start_tour.py    # Interactive guided setup
```

**Daily learning:**
```bash
master-prep-ai chat --kb textbook --tool rag --tool web_search
```

**Build a knowledge base from documents:**
```bash
master-prep-ai kb create physics --doc ch1.pdf --doc ch2.pdf
master-prep-ai run chat "Explain Newton's third law" --kb physics --tool rag
```

**Generate quiz questions:**
```bash
master-prep-ai run deep_question "Thermodynamics" --kb physics --config num_questions=5
```
