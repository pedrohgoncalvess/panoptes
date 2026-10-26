import asyncio

import httpx

from .http import Download


class BrowserClient:
    def __init__(self, url, token):
        self.client = httpx.AsyncClient(
            base_url=url,
            timeout=65,
            headers={"X-Browser-Service-Token": token},
        )

    async def fetch(self, site, url, lock, interval):
        async with lock:
            await asyncio.sleep(interval)
            response = await self.client.post(
                "/internal/browser/fetch", json={"site": site, "url": url}
            )
        response.raise_for_status()
        value = response.json()
        if value.get("fallback"):
            return None
        if value.get("blocked"):
            return value
        return Download(
            url,
            value["final_url"],
            value["body"].encode(),
            value["status"],
            value["media_type"],
            capture_mode=value.get("capture_mode", "browser"),
        )

    async def close(self):
        await self.client.aclose()
