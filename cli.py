"""CLI — run any YAML workflow from the command line.

Usage:
    python cli.py run my-workflow.yaml
    python cli.py run my-workflow.yaml --input topic="LangGraph patterns"
    python cli.py run my-workflow.yaml --input content=@article.md --input topic="AI agents"
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
import litellm

from src.engine import WorkflowEngine
from src.skill_loader import SkillLoader
from src.connectors import ConnectorRegistry

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _llm_call(model: str, system_prompt: str, user_msg: str, max_tokens: int) -> str:
    """Route LLM calls through LiteLLM. Supports 100+ providers."""
    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


@click.group()
def cli():
    pass


@cli.command()
@click.argument("yaml_path", type=click.Path(exists=True))
@click.option("--input", "-i", "inputs", multiple=True, help="key=value or key=@file.txt")
@click.option("--skills-dir", default="skills", help="Path to skills directory")
def run(yaml_path: str, inputs: tuple[str], skills_dir: str):
    """Run a YAML workflow."""
    # Parse inputs
    workflow_inputs = {}
    for inp in inputs:
        key, _, value = inp.partition("=")
        if value.startswith("@"):
            value = Path(value[1:]).read_text(encoding="utf-8")
        workflow_inputs[key] = value

    skill_loader = SkillLoader(skills_dir)
    registry = ConnectorRegistry()
    engine = WorkflowEngine(
        skill_loader=skill_loader,
        connector_registry=registry,
        llm_call=_llm_call,
    )

    workflow = engine.load(yaml_path)
    click.echo(f"Running: {workflow.name} ({len(workflow.steps)} steps)")
    click.echo(f"Steps: {' → '.join(s.name for s in workflow.steps)}")

    run_id = engine.run(workflow, workflow_inputs)
    click.echo(f"Done. Run ID: {run_id}")


if __name__ == "__main__":
    cli()
