"""Connector registry — pure Python functions callable from workflow YAML.

Register any function as a named connector. Workflows reference them by name:

    steps:
      - name: search
        type: connector
        connector: doc_search
        input:
          query: "{{input.topic}}"
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ConnectorFunc = Callable[[dict[str, Any]], str]


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, ConnectorFunc] = {}
        self._register_defaults()

    def register(self, name: str, func: ConnectorFunc) -> None:
        self._connectors[name] = func

    def execute(self, name: str, input_data: dict[str, Any]) -> str:
        func = self._connectors.get(name)
        if not func:
            raise KeyError(f"Connector '{name}' not found. Available: {self.list()}")
        result = func(input_data)
        logger.info(f"Connector '{name}': {len(result)} chars output")
        return result

    def list(self) -> list[str]:
        return sorted(self._connectors.keys())

    def _register_defaults(self) -> None:
        self.register("script", _run_script)
        self.register("file_read", _file_read)
        self.register("echo", _echo)


# --- Built-in connectors ---

def _run_script(input_data: dict[str, Any]) -> str:
    """Run a shell command. Input: {script: str, args: list, timeout: int}"""
    script = input_data.get("script")
    if not script:
        raise ValueError("'script' required")
    args = input_data.get("args", [])
    timeout = input_data.get("timeout", 120)
    result = subprocess.run(
        [script] + (args if isinstance(args, list) else [args]),
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Script failed (exit {result.returncode}): {result.stderr}")
    return result.stdout or "OK"


def _file_read(input_data: dict[str, Any]) -> str:
    """Read a file. Input: {source: str}"""
    source = input_data.get("source")
    if not source:
        raise ValueError("'source' required")
    return Path(source).read_text(encoding="utf-8")


def _echo(input_data: dict[str, Any]) -> str:
    """Pass-through connector for testing. Returns input as string."""
    return str(input_data.get("message", input_data))
