import asyncio
import fleet
from anthropic import AsyncAnthropic
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from dotenv import load_dotenv

load_dotenv()

client = AsyncAnthropic()


async def main():
    env = fleet.env.make("fira")
    print("Created environment:", env.urls.app)
    print("MCP URL:", env.mcp.url)

    asyncio.sleep(5)

    async with streamablehttp_client(url=env.mcp.url) as streams:
        async with ClientSession(
            read_stream=streams[0], write_stream=streams[1]
        ) as session:
            await session.initialize()

            list_tools = await session.list_tools()
            available_tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                }
                for tool in list_tools.tools
            ]

            messages = [
                {
                    "role": "user",
                    "content": "Get the current authorized user.",
                },
            ]
            response = await client.beta.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=messages,
                tools=available_tools,
            )

            tool_results = []
            output_text = []
            for content in response.content:
                if content.type == "text":
                    output_text.append(content.text)
                elif content.type == "tool_use":
                    tool_name = content.name
                    tool_args = content.input

                    result = await session.call_tool(tool_name, tool_args)
                    tool_results.append({"call": tool_name, "result": result})
                    output_text.append(
                        f"[Calling tool {tool_name} with args {tool_args}]"
                    )

                    if hasattr(content, "text") and content.text:
                        messages.append({"role": "assistant", "content": content.text})
                    messages.append({"role": "user", "content": result.content})

                    response = await client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=1000,
                        messages=messages,
                    )

                    output_text.append(response.content[0].text)

            print("\n".join(output_text))

    env.close()


if __name__ == "__main__":
    asyncio.run(main())
