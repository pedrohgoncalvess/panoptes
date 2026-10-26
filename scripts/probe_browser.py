"""Test the backend Chromium capture and worker parsers, without database/login."""

import argparse
import asyncio
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet
from panoptes_backend.browser.service import BrowserConnections
from panoptes_contracts.sources import captcha_page
from panoptes_workers.probe import SEEDS
from panoptes_workers.retailers.identity import key_from_url
from panoptes_workers.sources import get_source


async def probe(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix="browser-probe-", dir=output) as directory:
        service = BrowserConnections(directory, Fernet.generate_key().decode())
        try:
            if args.interactive:
                os.environ["BROWSER_RETAIL_HEADLESS"] = "false"
                for site in args.sites:
                    await service.connect(site)
                    await service.live[site]["page"].screenshot(
                        path=str(output / f"{site}-verification.png")
                    )
                    print(
                        json.dumps({"site": site, "status": "manual_action_required"}),
                        flush=True,
                    )
                remaining = set(args.sites)
                while remaining:
                    answer = await asyncio.to_thread(
                        input,
                        "Conclua a verificação nas janelas, volte à página inicial e pressione Enter (q para encerrar): ",
                    )
                    if answer.strip().lower() == "q":
                        return
                    for site in tuple(remaining):
                        if await service.authenticated(site, service.live[site]):
                            await service.save(site)
                            remaining.remove(site)
                            print(
                                json.dumps({"site": site, "status": "access_verified"}),
                                flush=True,
                            )
                        else:
                            print(
                                json.dumps(
                                    {"site": site, "status": "manual_action_required"}
                                ),
                                flush=True,
                            )
            for site in args.sites:
                source = get_source(site)
                product_urls = [SEEDS[site]]
                for stage, url in [
                    ("search", source.search_url("ssd kingston")),
                    ("product", SEEDS[site]),
                ]:
                    await visit(service, source, stage, url, output, rows, product_urls)
                for url in product_urls[1:2]:
                    await visit(service, source, "product", url, output, rows, [])
                if args.restart:
                    # Close the live context and restore only encrypted storage_state.
                    await service.drop(site)
                    await visit(
                        service,
                        source,
                        "product_after_context_restart",
                        product_urls[-1] if len(product_urls) > 1 else SEEDS[site],
                        output,
                        rows,
                        [],
                    )
        finally:
            await service.close()
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "transport": "backend_chromium",
        "requests": rows,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )


async def visit(service, source, stage, url, output, rows, product_urls):
    site = source.definition.id
    row = {"site": site, "stage": stage, "source_url": url}
    try:
        result = await asyncio.wait_for(service.fetch(site, url), timeout=65)
        if result.get("blocked"):
            row.update(status="blocked", reason=result["blocked"])
        elif not result.get("body"):
            row.update(status="failed", reason="no_browser_body")
        else:
            body, final = result["body"], result["final_url"]
            row.update(
                http_status=result["status"], final_url=final, bytes=len(body.encode())
            )
            if captcha_page(final, body) or result["status"] in (401, 403, 429):
                row.update(
                    status="blocked",
                    reason="captcha"
                    if captcha_page(final, body)
                    else f"http_{result['status']}",
                )
            elif result["status"] != 200:
                row.update(status="failed", reason=f"http_{result['status']}")
            else:
                filename = f"{site}-{len(rows)}-{stage}.html"
                (output / filename).write_text(body, encoding="utf-8")
                row["html_path"] = filename
                if stage == "search":
                    candidates, next_url = source.parse_search(body, uuid4(), 1)
                    row.update(
                        status="parsed", candidates=len(candidates), next_url=next_url
                    )
                    product_urls.extend(
                        str(c.url)
                        for c in candidates
                        if c.title.lower().startswith("ssd ")
                    )
                else:
                    detail = source.parse_product(body, final, key_from_url(site, url))
                    row.update(status="parsed", result=detail.model_dump(mode="json"))
    except Exception as error:
        row.update(
            status="failed", error_type=type(error).__name__, reason=str(error)[:700]
        )
    rows.append(row)
    print(
        json.dumps({k: v for k, v in row.items() if k != "result"}, ensure_ascii=True),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/backend-browser-probe")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Open manual verification windows before testing the saved sessions",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Also test restoring the encrypted state into a fresh context",
    )
    parser.add_argument(
        "--sites",
        nargs="+",
        choices=["pichau_br", "terabyte_br"],
        default=["pichau_br", "terabyte_br"],
    )
    asyncio.run(probe(parser.parse_args()))
