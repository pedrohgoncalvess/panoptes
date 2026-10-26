"""File-backed platform agent registry."""

from .upsert_agents import load_agents, upsert_agents

__all__ = ["load_agents", "upsert_agents"]
