from typing import Dict


class MCPResource:
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
