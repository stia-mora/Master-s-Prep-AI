const FENCE = "```";

export const CO_WRITER_SAMPLE_TEMPLATE = `# Master Prep AI Co-Writer

> Master Prep AI's built-in writing canvas for notes, reports, tutorials, and AI-assisted drafts.

### Features

- Support Standard Markdown / CommonMark / GFM for everyday writing
- Real-time preview for headings, tables, code, math, flowchart, and sequence diagrams
- AI editing workflows for rewrite, shorten, and expand
- HTML tag decoding for tags like <sub>, <sup>, <abbr>, and <mark>
- A practical starter draft for Master Prep AI product docs and learning content

## Table of Contents

[TOCM]

[TOC]

#Master Prep AI Mission
##Master Prep AI Product Surface
###Master Prep AI Learning Experience
####Master Prep AI Co-Writer
#####Master Prep AI Knowledge Layer
######Master Prep AI Agent Runtime

#Master Prep AI Docs [Project Overview](#master_prep_ai-mission "Jump to project overview")
##Master Prep AI Authoring [Co-Writer Section](#master_prep_ai-co-writer "Jump to co-writer section")
###Master Prep AI Research [Learning Note](#master_prep_ai-learning-note "Jump to learning note")

## Headers (Underline)

Master Prep AI Learning Note
=============

Master Prep AI Study Outline
-------------

### Characters

----

~~Deprecated behavior~~ <s>Legacy formatting path</s>
*Italic* _Italic_
**Emphasis** __Emphasis__
***Emphasis Italic*** ___Emphasis Italic___

Superscript: X<sub>2</sub>, Subscript: O<sup>2</sup>

**Abbreviation(link HTML abbr tag)**

The <abbr title="Large Language Model">LLM</abbr> layer powers Master Prep AI while the <abbr title="Retrieval Augmented Generation">RAG</abbr> layer provides grounded knowledge support.

### Blockquotes

> Master Prep AI helps students turn questions into structured understanding.
>
> "Learn deeply, write clearly.", [Master Prep AI](#master_prep_ai-co-writer)

### Links

[Master Prep AI Overview](#master_prep_ai-mission)

[Master Prep AI Co-Writer](#master_prep_ai-co-writer "co-writer section")

[Master Prep AI Runtime](#master_prep_ai-agent-runtime)

[Reference link][master_prep_ai-doc]

[master_prep_ai-doc]: #master_prep_ai-learning-note

### Code Blocks

#### Inline code

\`master_prep_ai chat --once "Summarize this section"\`

#### Code Blocks (Indented style)

    from master_prep_ai.runtime.orchestrator import ChatOrchestrator
    orchestrator = ChatOrchestrator()
    print("Master Prep AI is ready.")

#### Python

${FENCE}python
from master_prep_ai.runtime.orchestrator import ChatOrchestrator
from master_prep_ai.core.context import UnifiedContext


async def run_demo() -> str:
    orchestrator = ChatOrchestrator()
    context = UnifiedContext(
        user_query="Explain Newton's second law",
        capability="chat",
    )
    result = await orchestrator.run(context)
    return result.get("response", "")
${FENCE}

#### JSON config

${FENCE}json
{
  "app_name": "Master Prep AI",
  "default_capability": "chat",
  "enabled_tools": ["rag", "web_search", "code_execution", "reason"],
  "ui": {
    "co_writer_template": true
  }
}
${FENCE}

#### HTML code

${FENCE}html
<section class="master_prep_ai-card">
  <h1>Master Prep AI</h1>
  <p>Write, revise, and organize learning content with AI.</p>
</section>
${FENCE}

### Images

![](/logo-ver2.png)

> Master Prep AI brand mark used inside the co-writer template.

### Lists

- Master Prep AI Chat
- Master Prep AI Co-Writer
- Master Prep AI Research

1. Draft a concept note
2. Ask AI to refine it
3. Export the polished markdown

### Tables

Feature       | Description
------------- | -------------
Co-Writer     | Draft and refine Markdown content
Chat          | Ask questions and iterate ideas
Research      | Build structured multi-step reports

| Capability    | Primary Use Case                     |
| ------------- | ------------------------------------ |
| \`chat\`       | General tutoring and guidance        |
| \`deep_solve\` | Structured problem solving           |
| \`deep_question\` | Question generation and validation |

### Markdown extras

- [x] Draft a Master Prep AI product note
- [x] Add references and structure
- [ ] Polish the final explanation
  - [ ] Check headings
  - [ ] Check citations

### TeX (LaTeX)

$$ E=mc^2 $$

Inline $$E=mc^2$$ appears in physics notes, and Inline $$a^2+b^2=c^2$$ appears in geometry notes.

$$\(\sqrt{3x-1}+(1+x)^2\)$$

$$ \sin(\alpha)^{\theta}=\sum_{i=0}^{n}(x^i + \cos(f))$$

### FlowChart

${FENCE}flow
st=>start: Student asks a question
op=>operation: Master Prep AI analyzes intent
cond=>condition: Need deep workflow?
chat=>operation: Answer with chat capability
solve=>operation: Route to deep solve
e=>end: Return structured response

st->op->cond
cond(no)->chat
cond(yes)->solve
chat->e
solve->e
${FENCE}

### Sequence Diagram

${FENCE}seq
Student->Master Prep AI: Ask for help
Master Prep AI->KnowledgeBase: Load context
Note right of Master Prep AI: Collect memory\nand relevant knowledge
Master Prep AI-->Student: Return guided response
Student->>Master Prep AI: Request rewrite in co-writer
${FENCE}

### End
`;
