"""Manual registry sync: python -m panoptes_ai.sync [agents|models]."""

import argparse
import asyncio

import httpx
from panoptes_database.config import load_database_settings
from panoptes_database.session import create_database

from .registry import sync_agents, sync_models


async def main(mode="agents"):
    engine, sessions = create_database(load_database_settings())
    try:
        if mode == "agents":
            print(f"Platform agents synchronized: {await sync_agents(sessions)}")
        else:
            async with httpx.AsyncClient(timeout=30) as http:
                await sync_models(sessions, http)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", choices=("agents", "models"), nargs="?", default="agents"
    )
    asyncio.run(main(parser.parse_args().mode))
