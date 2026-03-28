# yaml-to-langgraph

Stop hand-coding AI pipelines. Write YAML, run graphs.

This engine compiles human-readable YAML workflow definitions into executable [LangGraph](https://github.com/langchain-ai/langgraph) StateGraphs at runtime. New workflow = new YAML file. No Python changes needed.

## How it works

```
YAML file → parse steps → topological sort → build StateGraph nodes → wire edges → compile → run
```

You define workflows as YAML. The engine handles compilation, state management, checkpointing, and human-in-the-loop gates. LLM calls route through [LiteLLM](https://github.com/BerriAI/litellm) (100+ providers).

## The workflow

**You don't write these YAMLs by hand.** You describe what you want to your AI, and it writes the YAML for you. That's the whole point — YAML is the interface between human intent and LangGraph execution.

Tell your AI:
> "I need a pipeline that takes a topic, researches it, drafts a blog post, reviews it for quality, and waits for my approval before publishing."

It produces a YAML file. You drop it in your workflows folder. You run it. Done.

If you know LangGraph and prefer manual control, you can obviously write the YAML yourself. The schema is dead simple.

## YAML schema

```yaml
name: my_workflow

steps:
  - name: step_name
    type: ai | connector | human_gate | script
    skill: skill-folder-name     # for type: ai — loads SKILL.md as system prompt
    model: gpt-4o                # any LiteLLM-supported model string
    max_tokens: 4096
    connector: connector_name    # for type: connector
    depends_on: [other_step]     # controls execution order
    input:
      task: "Do this: {{input.topic}}"           # user input reference
      context: "{{previous_step.output}}"        # chain step outputs
```

### Step types

| Type | What it does |
|------|-------------|
| `ai` | LLM call. Loads a skill folder as system prompt, routes through LiteLLM |
| `connector` | Pure Python function. Registered by name in ConnectorRegistry |
| `human_gate` | Pauses execution. Waits for human approval. Resumes from checkpoint |
| `script` | Shell command via subprocess |

### Template syntax

- `{{input.topic}}` — references workflow inputs (passed at launch)
- `{{step_name.output}}` — references output from a completed step
- `depends_on: [a, b]` — ensures steps a and b complete before this one runs

## Setup

```bash
git clone <this-repo>
cd yaml-to-langgraph
pip install -r requirements.txt
cp .env.example .env
# Add at least one LLM provider key to .env
```

### Create a skill (optional)

Skills are system prompts that `type: ai` steps load automatically.

```
skills/
  my-skill/
    SKILL.md              ← the system prompt
    references/           ← optional context files (appended to prompt)
      style-guide.md
```

### Register custom connectors (optional)

Add your own Python functions to `src/connectors.py`:

```python
def my_search(input_data: dict) -> str:
    topic = input_data["topic"]
    # your logic here
    return f"Results for {topic}"

# In ConnectorRegistry._register_defaults():
self.register("my_search", my_search)
```

## Run

```bash
# Run a workflow
python cli.py run my-workflow.yaml

# Pass inputs
python cli.py run my-workflow.yaml -i topic="AI agents" -i tone="casual"

# Load file content as input
python cli.py run my-workflow.yaml -i content=@article.md -i topic="LangGraph"
```

## What you get for free

- **Checkpointing** — SQLite-backed. If the process crashes, resume from last completed step
- **Human-in-the-loop** — `type: human_gate` pauses the graph. Resume when ready
- **Dependency resolution** — topological sort handles execution order from `depends_on`
- **Any LLM** — LiteLLM routes to OpenAI, Anthropic, Gemini, Groq, DeepSeek, local models, etc.
- **Skill injection** — system prompts loaded from disk, not hardcoded. Swap skills without touching workflow code

## Architecture

```
yaml-to-langgraph/
├── cli.py                ← entry point
├── src/
│   ├── engine.py         ← the compiler: YAML → StateGraph → run
│   ├── schema.py         ← WorkflowState (TypedDict) + WorkflowStep (dataclass)
│   ├── skill_loader.py   ← reads skills/{name}/SKILL.md as system prompts
│   └── connectors.py     ← registry of callable Python functions
├── skills/               ← skill folders (nodemaker + flowmaker ship included)
├── workflows/            ← your YAML workflows (gitignored — bring your own)
└── data/                 ← SQLite checkpoints (gitignored)
```

The entire engine is `engine.py` (~200 lines). Everything else is plumbing.

## Built with

- [LangGraph](https://github.com/langchain-ai/langgraph) — state machine execution, checkpointing, interrupts
- [LiteLLM](https://github.com/BerriAI/litellm) — unified LLM API (100+ providers)
- [PyYAML](https://pyyaml.org/) — workflow parsing
- [Click](https://click.palletsprojects.com/) — CLI

## License

MIT
