"""Workflow state and step definitions."""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any

from typing_extensions import TypedDict


class WorkflowState(TypedDict):
    """Shared state flowing through every node in the graph."""
    workflow_name: str
    current_step: str
    step_outputs: Annotated[dict, operator.ior]  # each node merges its key in
    workflow_inputs: dict  # user-provided at launch
    status: str  # running | completed | failed | interrupted
    error: str | None


@dataclass
class WorkflowStep:
    """A single step parsed from YAML."""
    name: str
    type: str  # ai | connector | human_gate | script
    skill: str | None = None
    connector: str | None = None
    model: str | None = None
    max_tokens: int = 4096
    input_map: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
