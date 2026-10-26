"""Compatibility entry point for shared OpenRouter model synchronization."""
import asyncio

from panoptes_ai.registry import model_sync_loop, sync_models
from panoptes_ai.sync import main

__all__ = ["model_sync_loop", "sync_models"]

if __name__ == "__main__":
    asyncio.run(main("models"))
