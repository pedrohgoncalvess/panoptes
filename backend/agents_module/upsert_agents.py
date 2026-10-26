"""Compatibility entry point for the shared platform agent registry."""
import asyncio

from panoptes_ai.registry import load_agents, sync_agents
from panoptes_ai.sync import main

__all__ = ["load_agents", "sync_agents"]

if __name__ == "__main__":
    asyncio.run(main("agents"))
