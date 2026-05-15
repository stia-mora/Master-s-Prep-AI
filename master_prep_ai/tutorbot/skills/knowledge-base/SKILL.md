---
name: knowledge-base
description: "Manage Master Prep AI knowledge bases — list, create, search, add documents, delete."
metadata: {"nanobot":{"emoji":"📚","requires":{"bins":["master_prep_ai"]}}}
always: false
---

# Knowledge Base Management

Use the `exec` tool to manage Master Prep AI knowledge bases via CLI.

## When to Use

- User asks about their **knowledge bases** or **study materials**
- User wants to **create**, **search**, or **manage** a knowledge base
- User needs to **add documents** to an existing KB

## Commands

### List all knowledge bases

```bash
master_prep_ai kb list --format json
```

> `--format json` outputs machine-readable JSON instead of a Rich table.

### Get info about a knowledge base

```bash
master_prep_ai kb info <kb_name>
```

### Create a knowledge base

```bash
master_prep_ai kb create <kb_name> --doc /path/to/file.pdf
master_prep_ai kb create <kb_name> --docs-dir /path/to/directory/
```

### Add documents to existing KB

```bash
master_prep_ai kb add <kb_name> --doc /path/to/new_file.pdf
```

### Search a knowledge base

```bash
master_prep_ai kb search <kb_name> "<query>" --format json
```

### Set a default knowledge base

```bash
master_prep_ai kb set-default <kb_name>
```

### Delete a knowledge base

```bash
master_prep_ai kb delete <kb_name> --force
```

## Tips

- Use `kb list` first to see what's available before searching.
- The `rag` tool can also search KBs directly within the conversation — use it for quick lookups.
- KB creation from large PDFs can take a few minutes.
- Always confirm with the user before deleting a knowledge base.
