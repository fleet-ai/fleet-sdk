"""Gemini Computer Use Agent.

- agent.py: Runs on HOST, calls Gemini API
- cua_server.py: Runs in Docker, controls browser via Playwright
"""

from pathlib import Path

AGENT_DIR = Path(__file__).parent

