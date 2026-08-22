# MemoryTool - Long-term memory for MollyPaw agent
import os
import json
import uuid
import time
import re

class MemoryTool:
    """Persistent memory system. Memories are stored as JSON in data/memory/."""

    name = "memory_tool"
    description = "Long-term memory: save, search, list, delete memories"

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "save_memory",
                "description": "Save a memory with optional tags and category. Use this to remember facts, preferences, user info, or anything important for future conversations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The content to remember.",
                        },
                        "tags": {
                            "type": "string",
                            "description": "Comma-separated tags for categorization, e.g. 'user,preference,language'.",
                        },
                        "category": {
                            "type": "string",
                            "description": "Category: 'info', 'preference', 'task', 'note', or custom.",
                        },
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_memory",
                "description": "Search memories by keyword or tag. Returns matching memories.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search keyword or phrase.",
                        },
                        "tag": {
                            "type": "string",
                            "description": "Filter by specific tag.",
                        },
                        "category": {
                            "type": "string",
                            "description": "Filter by category.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results to return. Default 10.",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_memories",
                "description": "List all stored memories, newest first.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Max memories to list. Default 20.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_memory",
                "description": "Delete a memory by its ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "The memory ID to delete.",
                        },
                    },
                    "required": ["id"],
                },
            },
        },
    ]

    def __init__(self):
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self._mem_dir = os.path.join(base, "data", "memory")
        os.makedirs(self._mem_dir, exist_ok=True)

    def execute(self, func_name, arguments):
        method = getattr(self, func_name, None)
        if method is None:
            return "Error: MemoryTool has no method '%s'" % func_name
        return method(**arguments)

    def _load_all(self):
        memories = []
        for fname in os.listdir(self._mem_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(self._mem_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    memories.append(json.load(f))
            except Exception:
                pass
        memories.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return memories

    def save_memory(self, content, tags="", category="info"):
        mem_id = str(uuid.uuid4())[:8]
        now = time.time()
        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        memory = {
            "id": mem_id,
            "content": content,
            "tags": tags_list,
            "category": category,
            "created_at": now,
            "updated_at": now,
        }
        fpath = os.path.join(self._mem_dir, mem_id + ".json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
        return "Memory saved (id: %s)" % mem_id

    def search_memory(self, query, tag=None, category=None, limit=10):
        memories = self._load_all()
        query_lower = query.lower()
        results = []
        for m in memories:
            content_lower = m.get("content", "").lower()
            tags = [t.lower() for t in m.get("tags", [])]
            # Match query in content or tags
            matched = query_lower in content_lower or any(query_lower in t for t in tags)
            if not matched:
                continue
            if tag and tag.lower() not in tags:
                continue
            if category and m.get("category", "").lower() != category.lower():
                continue
            results.append(m)
            if len(results) >= limit:
                break
        if not results:
            return "No memories found for '%s'" % query
        out = []
        for m in results:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(m.get("created_at", 0)))
            out.append("[%s] (%s) %s" % (m["id"], ts, m["content"][:200]))
        return "\n".join(out)

    def list_memories(self, limit=20):
        memories = self._load_all()[:limit]
        if not memories:
            return "No memories stored yet."
        out = []
        for m in memories:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(m.get("created_at", 0)))
            tags = ", ".join(m.get("tags", []))
            cat = m.get("category", "")
            out.append("[%s] (%s) [%s] [%s] %s" % (m["id"], ts, cat, tags, m["content"][:150]))
        return "\n".join(out)

    def delete_memory(self, id):
        fpath = os.path.join(self._mem_dir, id + ".json")
        if not os.path.isfile(fpath):
            return "Error: Memory '%s' not found" % id
        try:
            os.remove(fpath)
            return "Memory '%s' deleted" % id
        except Exception as e:
            return "Error deleting memory: %s" % e
