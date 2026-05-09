import ast
import asyncio
import json
import sqlite3
from contextlib import AsyncExitStack
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

import fleet
import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Tool
from anthropic import AsyncAnthropic
from anthropic.types import (
    MessageParam,
    TextBlockParam,
    ToolParam,
    ToolResultBlockParam,
)

load_dotenv()


client = AsyncAnthropic()


MODEL = "claude-opus-4-6"


def save_to_tmp(content: str, prefix: str = "output", extension: str = "txt") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{prefix}_{timestamp}.{extension}"
    filepath = f"/tmp/{filename}"

    with open(filepath, "w") as f:
        f.write(content)

    return filepath


def convert_tool_format(tool: Tool) -> ToolParam:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema,
    }


# ─────────────────── OpenClaw skills + memory integration ───────────────────
#
# Mirrors what `theseus/orchestrator/temporal` does for tasks that ship an
# `INSTANCE_SKILLS_ROOT` and/or `INSTANCE_MEMORY_ROOT` env var. We talk to the
# env's runner FS directly over HTTP (`/fs/list`, `/fs/file/text`) and inject
# skill descriptions + memory contents into the system prompt, plus three
# on-demand tools (`read_skill`, `memory_get`, `memory_search`).


# Both prefaces are copied verbatim from theseus's
# `build_skills_system_prompt_section` / `download_memory_bundle_content`
# so the system prompt is byte-for-byte identical to the orchestrator's.
SKILLS_PROMPT_PREFACE = (
    "At its core, a skill is a folder containing a SKILL.md file. This file "
    "includes metadata (name and description, at minimum) and instructions "
    "that tell you how to perform a specific task. Skills can also bundle "
    "scripts, templates, and reference materials.\n"
    "\n"
    "You have access to the following skills. Use the `read_skill` tool to "
    "load the full instructions for a skill before using it."
)

MEMORY_PROMPT_PREFACE = (
    "- **MEMORY.md** — long-term memory. Durable facts, preferences, and "
    "decisions. Loaded at the start of every DM session.\n"
    "- **memory/YYYY-MM-DD.md** — daily notes. Running context and "
    "observations. Today and yesterday's notes are loaded automatically."
)


class RunnerFs:
    """Minimal client for the env runner's `/fs/list` and `/fs/file/text` routes.

    Same endpoints `theseus/orchestrator/temporal/runner_fs_tools.py` uses.
    `list` normalizes the response so callers always see `{name, is_dir}` dicts.
    """

    # Runner's `FileInfo` returns `file_type`; older fixtures use `type`/`kind`.
    _DIR_TYPES = frozenset({"dir", "directory", "folder"})

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list(self, path: str) -> List[Dict[str, Any]]:
        r = await self._client.get(f"{self.base_url}/fs/list", params={"path": path})
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            raw = next(
                (
                    data[k]
                    for k in ("entries", "items", "files", "results", "children")
                    if isinstance(data.get(k), list)
                ),
                [],
            )
        else:
            raw = []

        out: List[Dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = (
                entry.get("name")
                or entry.get("filename")
                or entry.get("basename")
                or (
                    entry["path"].rsplit("/", 1)[-1]
                    if isinstance(entry.get("path"), str)
                    else None
                )
            )
            if not name:
                continue
            t = entry.get("file_type") or entry.get("type") or entry.get("kind")
            is_dir = (isinstance(t, str) and t.lower() in self._DIR_TYPES) or (
                entry.get("is_dir") is True
            )
            out.append({"name": name, "is_dir": is_dir})
        return out

    async def read_text(self, path: str) -> str:
        r = await self._client.post(
            f"{self.base_url}/fs/file/text", json={"path": path}
        )
        r.raise_for_status()
        return r.text


def parse_skill_description(md_text: str) -> str:
    """Return the first non-blank line that doesn't start with `#` or `---`.

    This matches theseus's naive `_extract_skill_description`: for SKILL.md
    files with YAML frontmatter the first matching line is the `name:` field
    inside the frontmatter, which is what the orchestrator's prompt shows
    (e.g. `- **bash-scripting**: name: bash-scripting`). Skipping the
    frontmatter would return the prose description below it instead and
    break parity.
    """
    for line in md_text.split("\n"):
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith("---"):
            return s
    return ""


async def load_openclaw_skills(
    runner: RunnerFs, skills_root: str
) -> List[Dict[str, str]]:
    """One-level walk of skills_root. Each subfolder with a SKILL.md becomes a skill."""
    skills_root = skills_root.rstrip("/")
    # Retry: the runner FS often 502s for the first few seconds after MCP
    # comes up. 4 attempts at 1.5s spacing covers the warmup window.
    last_error: Optional[BaseException] = None
    for attempt in range(4):
        try:
            entries = await runner.list(skills_root)
            break
        except Exception as e:
            last_error = e
            if attempt < 3:
                await asyncio.sleep(1.5)
    else:
        print(f"  Skills: failed to list {skills_root}: {last_error}")
        return []

    skills: List[Dict[str, str]] = []
    for entry in entries:
        # Top-level SKILL.md is intentionally skipped per OpenClaw spec —
        # every skill lives in `<skills_root>/<skill_name>/SKILL.md`.
        if not entry["is_dir"]:
            continue
        try:
            content = await runner.read_text(f"{skills_root}/{entry['name']}/SKILL.md")
        except Exception:
            continue
        if not content or content.lstrip().startswith("<!"):
            # Defensive: HTTP servers sometimes return HTML 404 with status 200.
            continue
        skills.append(
            {
                "name": entry["name"],
                "description": parse_skill_description(content),
                "content": content,
            }
        )
    return skills


async def load_openclaw_memory(
    runner: RunnerFs, memory_root: str, current_date_iso: Optional[str]
) -> Dict[str, Any]:
    """Load MEMORY.md + today/yesterday daily notes + enumerate every .md path."""
    memory_root = memory_root.rstrip("/")
    today = yesterday = ""
    if current_date_iso:
        try:
            dt = datetime.fromisoformat(current_date_iso.replace("Z", "+00:00"))
            today = dt.strftime("%Y-%m-%d")
            yesterday = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            pass

    async def _try_read(path: str) -> Optional[str]:
        # Retry: the runner FS often 502s during the first few seconds after
        # MCP becomes ready (theseus sees the same thing). Without retries,
        # MEMORY.md / today / yesterday silently come back empty even though
        # the file exists, and the model has to discover them via memory_get.
        # 4 attempts at 1.5s spacing covers the warmup window.
        last_error: Optional[BaseException] = None
        for attempt in range(4):
            try:
                text = await runner.read_text(path)
            except Exception as e:
                last_error = e
                if attempt < 3:
                    await asyncio.sleep(1.5)
                continue
            if not text or text.lstrip().startswith("<!"):
                return None
            return text
        print(
            f"  Memory read failed: {path} -> {type(last_error).__name__}: {last_error}"
        )
        return None

    memory_md = await _try_read(f"{memory_root}/MEMORY.md")
    today_md = await _try_read(f"{memory_root}/memory/{today}.md") if today else None
    yesterday_md = (
        await _try_read(f"{memory_root}/memory/{yesterday}.md") if yesterday else None
    )

    # Enumerate every .md file under memory_root, descending up to 2 levels.
    files: Dict[str, str] = {}

    async def _walk(rel_dir: str, depth: int) -> None:
        if depth > 2:
            return
        abs_dir = memory_root if not rel_dir else f"{memory_root}/{rel_dir}"
        try:
            entries = await runner.list(abs_dir)
        except Exception:
            return
        for entry in entries:
            name = entry["name"]
            new_rel = name if not rel_dir else f"{rel_dir}/{name}"
            if entry["is_dir"]:
                await _walk(new_rel, depth + 1)
            elif name.lower().endswith(".md"):
                files.setdefault(new_rel, "")  # contents lazy-loaded on search

    await _walk("", 0)

    return {
        "today": today,
        "yesterday": yesterday,
        "memory_md": memory_md,
        "today_md": today_md,
        "yesterday_md": yesterday_md,
        "files": files,
    }


def build_openclaw_system_text(
    skills: List[Dict[str, str]], memory: Dict[str, Any]
) -> str:
    """Render Available Skills + Memory System sections for the system prompt."""
    parts: List[str] = []

    if skills:
        bullets = "\n".join(f"- **{s['name']}**: {s['description']}" for s in skills)
        parts.append(
            f"\n\n## Available Skills\n\n{SKILLS_PROMPT_PREFACE}\n\n{bullets}\n"
        )

    if memory and (
        memory.get("memory_md")
        or memory.get("today_md")
        or memory.get("yesterday_md")
        or memory.get("files")
    ):
        # Theseus joins memory sections with `\n\n---\n\n` and does NOT add a
        # trailing `\n` to each section — matching that exactly avoids the
        # extra blank line at EOF that diff -u flags as the only mismatch.
        sections = [f"## Memory System\n\n{MEMORY_PROMPT_PREFACE}"]
        if memory.get("memory_md"):
            sections.append(f"## Memory\n\n{memory['memory_md']}")
        if memory.get("today_md"):
            sections.append(
                f"## Today's notes ({memory['today']})\n\n{memory['today_md']}"
            )
        if memory.get("yesterday_md"):
            sections.append(
                f"## Yesterday's notes ({memory['yesterday']})\n\n"
                f"{memory['yesterday_md']}"
            )
        parts.append("\n\n" + "\n\n---\n\n".join(sections))

    return "".join(parts)


def memory_search_fts5(query: str, documents: List[tuple]) -> str:
    """SQLite FTS5 BM25 ranked search across memory file contents.

    Mirrors theseus's `fts5_search` + `search_memory_from_fs` exactly:
    - Tokens are double-quoted and internal quotes doubled per the FTS5 spec
      (otherwise queries with colons / punctuation crash with `fts5: syntax
      error near ":"`).
    - Returns FULL file content for each ranked hit (top 10), not snippets.
    - Result format: `### {filename} (relevance: {score:.2f})\\n{content}`
      joined by `\\n\\n---\\n\\n`. Score is `-rank` (FTS5 rank is negative;
      closer to 0 = better, so we negate for display).
    - Empty query, no docs, or no matches all return the same string —
      `"No matching memories found."` — matching theseus.
    """
    if not documents:
        return "No matching memories found."
    safe_query = " ".join(
        '"{}"'.format(tok.replace('"', '""')) for tok in query.split() if tok.strip()
    )
    if not safe_query:
        return "No matching memories found."

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE memory_fts USING fts5("
            '  filename, content, tokenize="unicode61"'
            ")"
        )
        conn.executemany("INSERT INTO memory_fts VALUES (?, ?)", documents)
        rows = conn.execute(
            "SELECT filename, content, rank "
            "FROM memory_fts WHERE content MATCH ? "
            "ORDER BY rank LIMIT ?",
            (safe_query, 10),
        ).fetchall()
    except sqlite3.OperationalError:
        return "No matching memories found."
    finally:
        conn.close()
    if not rows:
        return "No matching memories found."
    sections = [
        f"### {fn} (relevance: {-rank:.2f})\n{content}" for fn, content, rank in rows
    ]
    return "\n\n---\n\n".join(sections)


def _block_field(block: Any, key: str) -> Any:
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


def verifier_accepts_conversation(verifier_func: Optional[str]) -> bool:
    """Return True if the verifier's top-level function declares a `conversation` param.

    The verifier is a Python source string (e.g. `def verify(env, final_answer=None,
    conversation=None): ...`). We parse it with ast and inspect the first top-level
    function's signature. Nested helper functions are intentionally ignored.
    """
    if not verifier_func:
        return False
    try:
        tree = ast.parse(verifier_func)
    except SyntaxError:
        return False

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            param_names = {a.arg for a in args.args} | {a.arg for a in args.kwonlyargs}
            return "conversation" in param_names
    return False


def to_openai_conversation(
    system: List[TextBlockParam],
    messages: List[MessageParam],
) -> List[dict]:
    """Convert Anthropic-format system+messages into OpenAI chat schema.

    This is the format Fleet verifiers expect for the `conversation` param:
      - {"role": "system", "content": str}
      - {"role": "user", "content": str}
      - {"role": "assistant", "content": str | None, "tool_calls": [...]}
      - {"role": "tool", "tool_call_id": str, "content": str}
    """
    out: List[dict] = []

    system_text = "\n\n".join(
        b["text"] for b in system if b.get("type") == "text" and b.get("text")
    )
    if system_text:
        out.append({"role": "system", "content": system_text})

    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        blocks = [content] if isinstance(content, str) else list(content)

        if role == "user":
            text_parts: List[str] = []
            tool_msgs: List[dict] = []
            for block in blocks:
                if isinstance(block, str):
                    text_parts.append(block)
                    continue
                btype = _block_field(block, "type")
                if btype == "text":
                    text_parts.append(_block_field(block, "text") or "")
                elif btype == "tool_result":
                    tool_content = _block_field(block, "content")
                    if not isinstance(tool_content, str):
                        tool_content = json.dumps(tool_content, default=str)
                    tool_msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": _block_field(block, "tool_use_id"),
                            "content": tool_content,
                        }
                    )

            if text_parts:
                out.append({"role": "user", "content": "\n".join(text_parts)})
            out.extend(tool_msgs)
            continue

        if role == "assistant":
            text_parts = []
            tool_calls: List[dict] = []
            for block in blocks:
                btype = _block_field(block, "type")
                if btype == "text":
                    text_parts.append(_block_field(block, "text") or "")
                elif btype == "tool_use":
                    tool_calls.append(
                        {
                            "id": _block_field(block, "id"),
                            "type": "function",
                            "function": {
                                "name": _block_field(block, "name"),
                                "arguments": json.dumps(
                                    _block_field(block, "input") or {}
                                ),
                            },
                        }
                    )

            entry: dict = {
                "role": "assistant",
                "content": "\n".join(text_parts) if text_parts else None,
            }
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)

    return out


async def wait_for_mcp(
    mcp_url: str, timeout: float = 120.0, delay: float = 1.0
) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    attempt = 0
    last_error: BaseException | None = None
    while asyncio.get_event_loop().time() < deadline:
        attempt += 1
        try:
            async with streamable_http_client(mcp_url) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
            print(f"\rMCP ready after {attempt} attempt(s)            ")
            return
        except BaseException as e:
            last_error = e
            err_name = type(e).__name__
            print(
                f"\rWaiting for MCP (attempt {attempt}, {err_name})...",
                end="",
                flush=True,
            )
            await asyncio.sleep(delay)
    raise TimeoutError(
        f"MCP did not become ready at {mcp_url} within {timeout}s (last error: {last_error})"
    )


async def main():
    tasks = await fleet.load_tasks_async(
        keys=["task_x4zukk7uk6sj_n_1776210959854_ixm2x50h2_bash"]
    )
    task = tasks[0]

    print("Task Key:", task.key)
    print("Task Prompt:", task.prompt)

    env = await fleet.env.make_async(
        env_key=task.env_key,
        data_key=task.data_key,
        env_variables=task.env_variables,
        ttl_seconds=3600,
    )
    print("Instance URL:", env.urls.root)

    if env.multi_env_list:
        endpoints = [(app, f"{env.urls.root}{app}/mcp") for app in env.multi_env_list]
    else:
        endpoints = [(None, env.mcp.url)]

    print(f"MCP endpoints ({len(endpoints)}):")
    for app_name, url in endpoints:
        print(f"  {app_name or '(root)'}: {url}")

    print(f"\nProbing {len(endpoints)} endpoint(s) in parallel...")
    await asyncio.gather(*(wait_for_mcp(url) for _, url in endpoints))
    print(f"All {len(endpoints)} MCP endpoint(s) ready")

    print(f"App URL: {env.urls.app[0]}")

    # OpenClaw integration: detect via task env_variables and load skills/memory
    # from the env's runner FS. No-op for plain tasks.
    env_vars = task.env_variables or {}
    skills_root = env_vars.get("INSTANCE_SKILLS_ROOT")
    memory_root = env_vars.get("INSTANCE_MEMORY_ROOT")
    current_date = env_vars.get("CURRENT_DATE")
    fs_root = env_vars.get("INSTANCE_FILESYSTEM_ROOT")
    print(
        f"OpenClaw env vars: {sorted(k for k in env_vars if k.startswith(('INSTANCE_', 'CURRENT_')))}"
    )

    skills: List[Dict[str, str]] = []
    memory_data: Dict[str, Any] = {}
    runner_fs: Optional[RunnerFs] = None
    runner_api_url: Optional[str] = None

    openclaw_active = bool(skills_root or memory_root or fs_root or current_date)
    if openclaw_active:
        # Per the openclaw spec, runner_api_url piggy-backs on the first MCP URL:
        # strip "/mcp", append "/api/v1/env". Theseus's `_derive_runner_api_url`
        # uses the same construction for multi-app envs (per-app prefix is fine —
        # the runner proxies through it).
        first_mcp_url = endpoints[0][1]
        runner_api_url = first_mcp_url[: -len("/mcp")] + "/api/v1/env"
        runner_fs = RunnerFs(runner_api_url)
        print(f"Runner FS API: {runner_api_url}")

        if skills_root:
            print(f"Loading skills from {skills_root}...")
            skills = await load_openclaw_skills(runner_fs, skills_root)
            print(f"  Loaded {len(skills)} skills")

        if memory_root:
            print(f"Loading memory from {memory_root}...")
            memory_data = await load_openclaw_memory(
                runner_fs, memory_root, current_date
            )
            print(
                f"  MEMORY.md={'yes' if memory_data.get('memory_md') else 'no'}, "
                f"today({memory_data.get('today') or '-'})="
                f"{'yes' if memory_data.get('today_md') else 'no'}, "
                f"yesterday({memory_data.get('yesterday') or '-'})="
                f"{'yes' if memory_data.get('yesterday_md') else 'no'}, "
                f"all .md={len(memory_data.get('files', {}))}"
            )

    system_text = (
        "You are a helpful agent. Complete the task. The session ends when you "
        "stop calling tools. Avoid unnecessary actions, as side effects may be "
        "graded as task failure."
    )
    if current_date:
        system_text += f"\n\nToday's date is {current_date}."
    if fs_root and runner_api_url:
        # Mirrors theseus's `get_runner_bash_system_prompt(fs_root)` exactly so
        # the agent gets the same input/deliverable contract.
        system_text += (
            "\n\nYou have a bash tool (runner_bash__bash) that runs shell "
            "commands inside the environment container.\n\n"
            f"- **Inputs** for this task live under {fs_root}. If the task "
            'refers to documents, data, or files you were "given," look there '
            f"first (`ls {fs_root}`, `find {fs_root} -type f`).\n"
            "- **Deliverables** go under /root/artifacts/. The verifier reads "
            "that directory — write final outputs there with `cp`, `tee`, "
            'heredocs, or `>` redirection. Example: `echo "..." > '
            "/root/artifacts/report.md`.\n"
            "- Scratch files can go in /tmp.\n"
            "- The working directory persists across calls (`cd` carries "
            "over); env vars and aliases do not."
        )
    system_text += build_openclaw_system_text(skills, memory_data)

    sys_path = save_to_tmp(system_text, prefix="system_prompt", extension="txt")
    print(f"System prompt ({len(system_text)} chars) saved to: {sys_path}")

    system: List[TextBlockParam] = [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages: List[MessageParam] = [
        {
            "role": "user",
            "content": [{"type": "text", "text": task.prompt}],
        }
    ]

    async with AsyncExitStack() as stack:
        anthropic_tools: List[ToolParam] = []
        # namespaced tool name -> async callable taking input dict, returning str
        dispatch: Dict[str, Callable[[Dict[str, Any]], Awaitable[str]]] = {}

        def make_mcp_handler(
            session: ClientSession, original_name: str
        ) -> Callable[[Dict[str, Any]], Awaitable[str]]:
            async def handler(input: Dict[str, Any]) -> str:
                result = await session.call_tool(original_name, input)
                return result.content[0].text

            return handler

        for app_name, url in endpoints:
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamable_http_client(url)
            )
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()

            tools_resp = await session.list_tools()
            # Hyphens in app names (e.g. "google-maps") aren't valid in OpenAI/Anthropic
            # function names, so swap them for underscores.
            prefix = f"{app_name.replace('-', '_')}__" if app_name else ""

            for mcp_tool in tools_resp.tools:
                tool_param = convert_tool_format(mcp_tool)
                if prefix:
                    tool_param["name"] = f"{prefix}{mcp_tool.name}"
                anthropic_tools.append(tool_param)
                dispatch[tool_param["name"]] = make_mcp_handler(session, mcp_tool.name)

        # OpenClaw on-demand tools.
        # All descriptions and behavior are ported verbatim from theseus's
        # `build_*_tool_definition` + `*_from_fs` helpers in
        # `orchestrator/temporal/skill_memory_utils.py` so every tool's
        # surface (name, description, parameter copy, return shape, error
        # strings) is byte-for-byte identical.

        if skills and runner_fs is not None and skills_root:
            skill_choices = [s["name"] for s in skills]
            anthropic_tools.append(
                {
                    "name": "read_skill",
                    "description": (
                        "Load the full instructions for a skill. Call this "
                        "before using a skill to get detailed instructions, "
                        "code examples, and reference materials."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "description": (
                                    "Name of the skill to load. "
                                    f"Available: {', '.join(skill_choices)}"
                                ),
                            }
                        },
                        "required": ["skill_name"],
                    },
                }
            )

            skills_root_clean = skills_root.rstrip("/")

            async def read_skill_handler(input: Dict[str, Any]) -> str:
                # Mirrors `read_skill_from_fs`: re-read SKILL.md from the
                # runner each call (no caching).
                skill_name = input.get("skill_name", "")
                abs_path = f"{skills_root_clean}/{skill_name}/SKILL.md"
                try:
                    return await runner_fs.read_text(abs_path)
                except Exception as exc:
                    return f"Error: skill '{skill_name}' not found at {abs_path}: {exc}"

            dispatch["read_skill"] = read_skill_handler

        if memory_data and runner_fs is not None and memory_root:
            memory_root_clean = memory_root.rstrip("/")

            anthropic_tools.append(
                {
                    "name": "memory_get",
                    "description": (
                        "Read a specific memory file by name. Use this to "
                        "access daily notes or other memory files."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "filename": {
                                "type": "string",
                                "description": (
                                    "The memory filename to read (e.g., "
                                    "'MEMORY.md', 'memory/2024-01-15.md')"
                                ),
                            }
                        },
                        "required": ["filename"],
                    },
                }
            )
            anthropic_tools.append(
                {
                    "name": "memory_search",
                    "description": (
                        "Search across memory files for relevant information. "
                        "Returns matching filenames and snippets."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query to find relevant memories",
                            }
                        },
                        "required": ["query"],
                    },
                }
            )

            async def memory_get_handler(input: Dict[str, Any]) -> str:
                # Mirrors `read_memory_file_from_fs`: no pre-validation, just
                # join the path and try to read it. Same error string.
                filename = input.get("filename", "")
                abs_path = f"{memory_root_clean}/{filename}"
                try:
                    return await runner_fs.read_text(abs_path)
                except Exception as exc:
                    return (
                        f"Error: memory file '{filename}' not found at "
                        f"{abs_path}: {exc}"
                    )

            async def memory_search_handler(input: Dict[str, Any]) -> str:
                # Mirrors `search_memory_from_fs`: re-walk the memory root,
                # re-read every .md file, then run FTS5. Theseus does this
                # fresh on every call rather than relying on an indexed cache,
                # so we do the same.
                query = input.get("query", "")

                filenames: List[str] = []

                async def _walk(rel_dir: str, depth: int) -> None:
                    if depth > 2:
                        return
                    abs_dir = (
                        memory_root_clean
                        if not rel_dir
                        else f"{memory_root_clean}/{rel_dir}"
                    )
                    try:
                        entries = await runner_fs.list(abs_dir)
                    except Exception:
                        return
                    for entry in entries:
                        name = entry["name"]
                        new_rel = name if not rel_dir else f"{rel_dir}/{name}"
                        if entry["is_dir"]:
                            await _walk(new_rel, depth + 1)
                        elif name.lower().endswith(".md"):
                            filenames.append(new_rel)

                await _walk("", 0)
                if not filenames:
                    return "No matching memories found."

                documents: List[tuple] = []
                for fn in filenames:
                    try:
                        text = await runner_fs.read_text(f"{memory_root_clean}/{fn}")
                    except Exception:
                        continue
                    documents.append((fn, text))

                return memory_search_fts5(query, documents)

            dispatch["memory_get"] = memory_get_handler
            dispatch["memory_search"] = memory_search_handler

        if fs_root and runner_api_url:
            # Mirrors theseus's `runner_bash__bash` tool exactly: POST to
            # {runner_api_url}/bash with {command, timeout_ms}. The runner
            # persists the working directory across calls but not env vars.
            # Theseus raises on missing/empty command and on HTTP errors —
            # we let those propagate; the outer dispatch loop turns them
            # into a `Tool error (...)` string for the model.
            bash_url = f"{runner_api_url.rstrip('/')}/bash"
            DEFAULT_TIMEOUT_MS = 120_000
            MAX_TIMEOUT_MS = 600_000
            anthropic_tools.append(
                {
                    "name": "runner_bash__bash",
                    "description": (
                        "Execute a bash command inside the environment "
                        f"container and return its stdout, stderr, and exit "
                        f"code. The environment root is {fs_root}; write "
                        "deliverables to /root/artifacts/. Working directory "
                        "persists across calls; shell env vars do not."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The shell command to execute.",
                            },
                            "timeout": {
                                "type": "integer",
                                "description": (
                                    "Max execution time in milliseconds. "
                                    f"Default {DEFAULT_TIMEOUT_MS} (2 min), "
                                    f"max {MAX_TIMEOUT_MS} (10 min)."
                                ),
                            },
                        },
                        "required": ["command"],
                    },
                }
            )

            async def bash_handler(input: Dict[str, Any]) -> str:
                command = (input or {}).get("command")
                if not isinstance(command, str) or not command:
                    raise ValueError("bash tool requires a non-empty `command` string")
                timeout_ms = (input or {}).get("timeout", DEFAULT_TIMEOUT_MS)
                if not isinstance(timeout_ms, int) or timeout_ms <= 0:
                    timeout_ms = DEFAULT_TIMEOUT_MS
                timeout_ms = min(timeout_ms, MAX_TIMEOUT_MS)
                http_timeout = httpx.Timeout(
                    connect=10.0,
                    read=(timeout_ms / 1000.0) + 30.0,
                    write=30.0,
                    pool=10.0,
                )
                async with httpx.AsyncClient(timeout=http_timeout) as c:
                    r = await c.post(
                        bash_url,
                        json={"command": command, "timeout_ms": timeout_ms},
                    )
                r.raise_for_status()
                body = r.json()
                return (
                    body
                    if isinstance(body, str)
                    else json.dumps(body, ensure_ascii=False)
                )

            dispatch["runner_bash__bash"] = bash_handler

        if anthropic_tools:
            anthropic_tools[-1]["cache_control"] = {"type": "ephemeral"}

        openclaw_tools = [
            n
            for n in dispatch
            if n in {"read_skill", "memory_get", "memory_search", "runner_bash__bash"}
        ]
        print(
            f"Loaded {len(anthropic_tools)} tools "
            f"({len(anthropic_tools) - len(openclaw_tools)} from {len(endpoints)} MCP endpoint(s), "
            f"{len(openclaw_tools)} OpenClaw: {openclaw_tools or '-'})"
        )

        while True:
            print(f"\nSending {len(messages)} messages")
            print([m["role"] for m in messages])

            messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}

            print("\nAssistant: ", end="", flush=True)
            async with client.messages.stream(
                model=MODEL,
                max_tokens=128000,
                messages=messages,
                tools=anthropic_tools,
                system=system,
            ) as stream:
                async for text in stream.text_stream:
                    print(text, end="", flush=True)
                response = await stream.get_final_message()
            print()

            del messages[-1]["content"][-1]["cache_control"]

            usage = response.usage
            print(f"Stop reason: {response.stop_reason}")
            print(
                f"Tokens: input={usage.input_tokens} output={usage.output_tokens} "
                f"cache_read={getattr(usage, 'cache_read_input_tokens', 0)} "
                f"cache_create={getattr(usage, 'cache_creation_input_tokens', 0)}"
            )

            messages.append({"role": "assistant", "content": response.content})

            tool_results: List[ToolResultBlockParam] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                print(f"\nTool ({block.name}): {block.input}")

                handler = dispatch.get(block.name)
                if handler is None:
                    result_str = f"Unknown tool: {block.name}"
                else:
                    try:
                        result_str = await handler(block.input or {})
                    except Exception as e:
                        result_str = f"Tool error ({type(e).__name__}): {e}"

                result_path = save_to_tmp(
                    result_str, prefix="tool_result", extension="txt"
                )
                print(f"Tool result saved to: {result_path}")

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    }
                )

            if not tool_results:
                break

            messages.append({"role": "user", "content": tool_results})

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        transcript_filename = f"messages_transcript_{timestamp}.json"
        transcript_path = f"/tmp/{transcript_filename}"

        with open(transcript_path, "w") as f:
            json.dump(messages, f, indent=2, default=str)

        print(f"\nFull transcript saved to: {transcript_path}")

    final_answer = response.content[-1].text
    print(f" Final Answer: {final_answer}")

    verify_kwargs: dict = {"final_answer": final_answer}
    if verifier_accepts_conversation(task.verifier_func):
        # Per Theseus orchestrator's `pass_conversation_to_verifier` contract,
        # `conversation` is a "JSON serialized format" string. Verifiers that want
        # the list back can `json.loads(conversation)`; verifiers that just want to
        # concatenate it into a prompt can do so without `str + list` errors.
        verify_kwargs["conversation"] = json.dumps(
            to_openai_conversation(system, messages)
        )
        print("Verifier accepts `conversation` param; passing it as a JSON string.")
    else:
        print("Verifier does not accept `conversation` param; skipping.")

    result = await task.verify_detailed_async(env, **verify_kwargs)
    print(f"Verifier error:", result.error)
    print(f"Verifier stdout:", result.stdout)
    print(f"Reward score:", result.result)

    if runner_fs is not None:
        await runner_fs.aclose()

    await env.close()


if __name__ == "__main__":
    asyncio.run(main())
