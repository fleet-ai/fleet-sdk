import asyncio
import json
from datetime import datetime
from typing import List

import fleet
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


MODEL = "claude-opus-4-7"


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
    tasks = await fleet.load_tasks_async(project_key="bloomberg-sample-tasks")
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
    mcp_url = env.mcp.url

    await wait_for_mcp(mcp_url)

    print(f"App URL: {env.urls.app[0]}")

    system: List[TextBlockParam] = [
        {
            "type": "text",
            "text": "You are a helpful agent. Complete the task. The session ends when you stop calling tools. Avoid unnecessary actions, as side effects may be graded as task failure.",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages: List[MessageParam] = [
        {
            "role": "user",
            "content": [{"type": "text", "text": task.prompt}],
        }
    ]

    async with streamable_http_client(mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            list_tools = await session.list_tools()

            anthropic_tools: List[ToolParam] = [
                convert_tool_format(tool) for tool in list_tools.tools
            ]
            if anthropic_tools:
                anthropic_tools[-1]["cache_control"] = {"type": "ephemeral"}

            print(f"Loaded {len(anthropic_tools)} tools")

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

                    result = await session.call_tool(block.name, block.input)
                    result_str = result.content[0].text

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

    result = await task.verify_detailed_async(env, final_answer=final_answer)
    print(f"Verifier stdout:", result.stdout)
    print(f"Reward score:", result.result)

    await env.close()


if __name__ == "__main__":
    asyncio.run(main())
