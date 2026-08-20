"""Optional natural-language agent layer. Requires ``pip install 'vida-sdk[agent]'``."""

from vida.agent.agent import SYSTEM_PROMPT, VidaAgent
from vida.agent.tools import build_tools

__all__ = ["VidaAgent", "build_tools", "SYSTEM_PROMPT"]
