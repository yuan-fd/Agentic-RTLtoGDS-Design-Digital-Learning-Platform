"""OpenROAD Workbench: a terminal-first EDA debugging workbench.

Layout
------
backend/  shared daemon: PTY sessions, run tracking, artifact index, MCP client, agent
tui/      Textual control surface (primary entry point)
web/      aiohttp dashboard (management / analysis surface)
"""

__version__ = "0.1.0"
