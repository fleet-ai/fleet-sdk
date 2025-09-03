from typing import Dict


class AsyncMCPResource:
    def __init__(self, url: str, env_key: str):
        self.url = url
        self._env_key = env_key

    def openai(self) -> Dict[str, str]:
        return {
            "type": "mcp",
            "server_label": self._env_key,
            "server_url": self.url,
            "require_approval": "never",
        }

    def anthropic(self) -> Dict[str, str]:
        return {
            "type": "url",
            "url": self.url,
            "name": self._env_key,
        }

    async def list_tools(self):
        import aiohttp

        """
        Make an async request to list available tools from the MCP endpoint.
        
        Returns:
            List of available tools with name, description, and input_schema
        """
        async with aiohttp.ClientSession() as session:
            payload = {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2}

            async with session.post(self.url, json=payload) as response:
                data = await response.json()

                # Extract tools from the response
                if "result" in data and "tools" in data["result"]:
                    tools = data["result"]["tools"]

                    available_tools = [
                        {
                            "name": tool.get("name"),
                            "description": tool.get("description"),
                            "input_schema": tool.get("inputSchema"),
                        }
                        for tool in tools
                    ]

                    return available_tools
                else:
                    # Handle error or empty response
                    return []
