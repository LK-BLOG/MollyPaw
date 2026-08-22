"""Skill Tool - MD-based skill system. Skills live in subdirectories with SKILL.md."""
import os
import re
import shutil


class SkillTool:
    """MD skill system. Skills are subdirectories in skills/ each containing SKILL.md."""

    name = "skill_tool"
    description = "Manage agent skills (MD files)"

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "list_skills",
                "description": "List all available skills with their names and descriptions.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "load_skill",
                "description": "Load and return the content of a specific skill by name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The skill name to load.",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_skill",
                "description": "Create a new skill directory with SKILL.md file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Skill name (used as directory name, no spaces).",
                        },
                        "content": {
                            "type": "string",
                            "description": "The full markdown content of the SKILL.md file.",
                        },
                        "description": {
                            "type": "string",
                            "description": "One-line description of the skill.",
                        },
                        "danger_level": {
                            "type": "string",
                            "description": "Danger level: safe, moderate, or dangerous.",
                            "enum": ["safe", "moderate", "dangerous"],
                        },
                    },
                    "required": ["name", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_skill",
                "description": "Delete a skill by name (removes entire subdirectory).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The skill name to delete.",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
    ]

    def __init__(self):
        from agent.paths import skills_dir
        self._skills_dir = skills_dir()

    def execute(self, func_name: str, arguments: dict) -> str:
        method = getattr(self, func_name, None)
        if method is None:
            return f"Error: SkillTool has no method '{func_name}'"
        return method(**arguments)

    def _parse_frontmatter(self, content: str) -> dict:
        meta = {}
        if content.startswith("---"):
            match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
            if match:
                for line in match.group(1).split('\n'):
                    line = line.strip()
                    if ':' in line:
                        key, val = line.split(':', 1)
                        meta[key.strip()] = val.strip().strip('"').strip("'")
        return meta

    def list_skills(self) -> str:
        skills = []
        if not os.path.isdir(self._skills_dir):
            return str(skills)
        for entry in sorted(os.listdir(self._skills_dir)):
            entry_path = os.path.join(self._skills_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            skill_md = os.path.join(entry_path, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue
            try:
                with open(skill_md, 'r', encoding='utf-8') as f:
                    content = f.read()
                meta = self._parse_frontmatter(content)
                skills.append({
                    "name": meta.get("name", entry),
                    "description": meta.get("description", "(no description)"),
                    "danger_level": meta.get("danger_level", "safe"),
                    "file": os.path.join(entry, "SKILL.md"),
                })
            except Exception:
                skills.append({
                    "name": entry,
                    "description": "(error reading file)",
                    "danger_level": "unknown",
                    "file": os.path.join(entry, "SKILL.md"),
                })
        return str(skills) if skills else str([])

    def load_skill(self, name: str) -> str:
        skill_dir = os.path.join(self._skills_dir, name)
        fpath = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(fpath):
            return f"Error: Skill '{name}' not found"
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error reading skill: {e}"

    def create_skill(self, name: str, content: str, description: str = "", danger_level: str = "safe") -> str:
        if not name or not name.replace('-', '').replace('_', '').isalnum():
            return "Error: Skill name must be alphanumeric (dashes/underscores allowed)"
        skill_dir = os.path.join(self._skills_dir, name)
        fpath = os.path.join(skill_dir, "SKILL.md")
        if not content.startswith("---"):
            frontmatter = f"---\nname: {name}\ndescription: {description}\ndanger_level: {danger_level}\n---\n\n"
            content = frontmatter + content
        try:
            os.makedirs(skill_dir, exist_ok=True)
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully created skill '{name}'"
        except Exception as e:
            return f"Error creating skill: {e}"

    def delete_skill(self, name: str) -> str:
        skill_dir = os.path.join(self._skills_dir, name)
        if not os.path.isdir(skill_dir):
            return f"Error: Skill '{name}' not found"
        try:
            shutil.rmtree(skill_dir)
            return f"Successfully deleted skill '{name}'"
        except Exception as e:
            return f"Error deleting skill: {e}"