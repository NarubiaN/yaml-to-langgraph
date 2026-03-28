"""Load system prompts from skill folders on disk.

Expected structure:
    skills/
      my-skill/
        SKILL.md          <- system prompt
        references/       <- optional context files appended to prompt
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillContext:
    name: str
    system_prompt: str
    references: list[Path] = field(default_factory=list)


class SkillLoader:
    def __init__(self, skills_dir: str | Path = "skills") -> None:
        self._dir = Path(skills_dir)
        self._cache: dict[str, SkillContext] = {}

    def load(self, skill_name: str) -> SkillContext:
        if skill_name in self._cache:
            return self._cache[skill_name]

        skill_dir = self._dir / skill_name
        skill_md = skill_dir / "SKILL.md"

        if not skill_md.exists():
            raise FileNotFoundError(f"Skill '{skill_name}' not found at {skill_dir}")

        parts = [skill_md.read_text(encoding="utf-8")]
        refs = []

        ref_dir = skill_dir / "references"
        if ref_dir.exists():
            for f in sorted(ref_dir.iterdir()):
                if f.is_file():
                    parts.append(f"\n--- Reference: {f.stem}\n\n{f.read_text(encoding='utf-8')}")
                    refs.append(f)

        ctx = SkillContext(name=skill_name, system_prompt="\n".join(parts), references=refs)
        self._cache[skill_name] = ctx
        return ctx

    def list_available(self) -> list[str]:
        if not self._dir.exists():
            return []
        return sorted(d.name for d in self._dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
