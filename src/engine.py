"""The compiler — turns YAML workflow definitions into executable LangGraph StateGraphs.

This is the core. It:
1. Parses YAML into WorkflowStep objects
2. Validates dependencies (no missing refs, no cycles)
3. Topologically sorts steps
4. Creates a LangGraph node for each step (type determines which factory)
5. Wires edges in topo order
6. Compiles with SQLite checkpointer for crash recovery
"""

from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import yaml
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command

from src.schema import WorkflowState, WorkflowStep
from src.skill_loader import SkillLoader
from src.connectors import ConnectorRegistry

logger = logging.getLogger(__name__)


class Workflow:
    """Parsed workflow from a YAML file."""

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.config = config
        self.steps: list[WorkflowStep] = []
        self._parse_steps()

    def _parse_steps(self) -> None:
        for step_data in self.config.get("steps", []):
            self.steps.append(WorkflowStep(
                name=step_data["name"],
                type=step_data["type"],
                skill=step_data.get("skill"),
                connector=step_data.get("connector"),
                model=step_data.get("model"),
                max_tokens=step_data.get("max_tokens", 4096),
                input_map=step_data.get("input", {}),
                depends_on=step_data.get("depends_on", []),
            ))

    def validate(self) -> list[str]:
        """Check for missing dependencies and cycles."""
        errors = []
        names = {s.name for s in self.steps}
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in names:
                    errors.append(f"Step '{step.name}' depends on missing step '{dep}'")

        # Cycle detection via DFS
        visited, temp = set(), set()
        def has_cycle(name: str) -> bool:
            if name in temp:
                return True
            if name in visited:
                return False
            temp.add(name)
            step = next((s for s in self.steps if s.name == name), None)
            if step:
                for dep in step.depends_on:
                    if has_cycle(dep):
                        return True
            temp.discard(name)
            visited.add(name)
            return False

        for step in self.steps:
            if has_cycle(step.name):
                errors.append(f"Dependency cycle involving '{step.name}'")
                break
        return errors


class WorkflowEngine:
    """Compiles and runs YAML workflows as LangGraph StateGraphs."""

    def __init__(
        self,
        skill_loader: SkillLoader,
        connector_registry: ConnectorRegistry,
        llm_call: Any = None,
        checkpoint_db: str = "data/checkpoints.db",
    ) -> None:
        self.skill_loader = skill_loader
        self.connectors = connector_registry
        self.llm_call = llm_call  # callable(model, system_prompt, user_msg, max_tokens) -> str
        Path(checkpoint_db).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(checkpoint_db, check_same_thread=False)
        self._checkpointer = SqliteSaver(self._conn)

    def load(self, yaml_path: str | Path) -> Workflow:
        """Load a workflow from a YAML file."""
        path = Path(yaml_path)
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return Workflow(config.get("name", path.stem), config)

    # --- Template resolution ---

    def _resolve(self, input_map: dict[str, Any], step_outputs: dict, workflow_inputs: dict) -> dict:
        """Replace {{scope.key}} references in input maps."""
        resolved = {}
        for key, value in input_map.items():
            if isinstance(value, str):
                def replacer(match):
                    scope, field = match.group(1), match.group(2)
                    if scope == "input":
                        return str(workflow_inputs.get(field, ""))
                    if field == "output":
                        return step_outputs.get(scope, "")
                    return match.group(0)
                resolved[key] = re.sub(r"\{\{(\w+)\.(\w+)\}\}", replacer, value)
            else:
                resolved[key] = value
        return resolved

    # --- Node factories ---

    def _make_ai_node(self, step: WorkflowStep):
        engine = self
        def node(state: WorkflowState) -> dict:
            resolved = engine._resolve(step.input_map, state["step_outputs"], state.get("workflow_inputs", {}))
            task = resolved.get("task", "")

            if not engine.llm_call:
                raise RuntimeError("No llm_call configured. Pass a callable to WorkflowEngine.")
            if not step.skill:
                raise ValueError(f"Step '{step.name}' is type 'ai' but no skill specified")

            skill_ctx = engine.skill_loader.load(step.skill)
            result = engine.llm_call(
                model=step.model or "sonnet",
                system_prompt=skill_ctx.system_prompt,
                user_msg=task,
                max_tokens=step.max_tokens,
            )
            return {"step_outputs": {step.name: result}, "current_step": step.name}
        node.__name__ = f"node_{step.name}"
        return node

    def _make_connector_node(self, step: WorkflowStep):
        engine = self
        def node(state: WorkflowState) -> dict:
            resolved = engine._resolve(step.input_map, state["step_outputs"], state.get("workflow_inputs", {}))
            result = engine.connectors.execute(step.connector, resolved)
            return {"step_outputs": {step.name: result}, "current_step": step.name}
        node.__name__ = f"node_{step.name}"
        return node

    def _make_human_gate_node(self, step: WorkflowStep):
        engine = self
        def node(state: WorkflowState) -> dict:
            resolved = engine._resolve(step.input_map, state["step_outputs"], state.get("workflow_inputs", {}))
            prompt = resolved.get("prompt", "Approve?")
            response = interrupt({"prompt": prompt, "step": step.name})
            return {"step_outputs": {step.name: response}, "current_step": step.name}
        node.__name__ = f"node_{step.name}"
        return node

    def _make_script_node(self, step: WorkflowStep):
        engine = self
        def node(state: WorkflowState) -> dict:
            resolved = engine._resolve(step.input_map, state["step_outputs"], state.get("workflow_inputs", {}))
            result = engine.connectors.execute("script", resolved)
            return {"step_outputs": {step.name: result}, "current_step": step.name}
        node.__name__ = f"node_{step.name}"
        return node

    # --- Compiler ---

    def _topo_sort(self, workflow: Workflow) -> list[str]:
        step_map = {s.name: s for s in workflow.steps}
        visited, order = set(), []
        def visit(name: str):
            if name in visited:
                return
            visited.add(name)
            for dep in step_map[name].depends_on:
                visit(dep)
            order.append(name)
        for step in workflow.steps:
            visit(step.name)
        return order

    def _build_graph(self, workflow: Workflow):
        """The core compiler. YAML steps -> LangGraph StateGraph."""
        builder = StateGraph(WorkflowState)
        step_map = {s.name: s for s in workflow.steps}
        order = self._topo_sort(workflow)

        factories = {
            "ai": self._make_ai_node,
            "connector": self._make_connector_node,
            "human_gate": self._make_human_gate_node,
            "script": self._make_script_node,
        }

        for name in order:
            step = step_map[name]
            factory = factories.get(step.type)
            if not factory:
                raise ValueError(f"Unknown step type: {step.type}")
            builder.add_node(name, factory(step))

        # Wire edges in topo order (linear chain)
        for i, name in enumerate(order):
            if i == 0:
                builder.add_edge(START, name)
            if i < len(order) - 1:
                builder.add_edge(name, order[i + 1])
            else:
                builder.add_edge(name, END)

        return builder.compile(checkpointer=self._checkpointer)

    # --- Runtime ---

    def run(self, workflow: Workflow, inputs: dict[str, Any] | None = None) -> str:
        """Execute a workflow. Returns run_id."""
        errors = workflow.validate()
        if errors:
            raise ValueError(f"Validation failed: {errors}")

        run_id = str(uuid.uuid4())
        graph = self._build_graph(workflow)

        initial: WorkflowState = {
            "workflow_name": workflow.name,
            "current_step": "",
            "step_outputs": {},
            "workflow_inputs": inputs or {},
            "status": "running",
            "error": None,
        }

        config = {"configurable": {"thread_id": run_id}}

        for event in graph.stream(initial, config, stream_mode="updates"):
            for node_name, update in event.items():
                if node_name == "__interrupt__":
                    logger.info(f"Workflow {run_id} paused at human gate")
                    return run_id
                output = update.get("step_outputs", {}).get(node_name, "")
                logger.info(f"Step '{node_name}' done ({len(str(output))} chars)")

        return run_id

    def resume(self, workflow: Workflow, run_id: str, response: str) -> str:
        """Resume from a human gate interrupt."""
        graph = self._build_graph(workflow)
        config = {"configurable": {"thread_id": run_id}}

        for event in graph.stream(Command(resume=response), config, stream_mode="updates"):
            for node_name, update in event.items():
                if node_name == "__interrupt__":
                    return run_id
                output = update.get("step_outputs", {}).get(node_name, "")
                logger.info(f"Step '{node_name}' done ({len(str(output))} chars)")

        return run_id
