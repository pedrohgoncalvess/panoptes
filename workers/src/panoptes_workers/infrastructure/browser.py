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
        for attempt in range(3):
            try:
                return await self._fetch_once(site, url, lock, interval)
            except (
                httpx.NetworkError,
                httpx.TimeoutException,
                httpx.RemoteProtocolError,
            ):
                if attempt == 2:
                    raise
            except httpx.HTTPStatusError as error:
                if error.response.status_code not in (502, 503, 504) or attempt == 2:
                    raise
            await asyncio.sleep(2 ** (attempt + 1))

    async def unavailable_sites(self):
        response = await self.client.get("/internal/browser/availability")
        response.raise_for_status()
        return [
            site
            for site, status in response.json().items()
            if status not in ("connected", "disconnected")
        ]

    async def _fetch_once(self, site, url, lock, interval):
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
