"""Opt-in public HTTP probes; no database, credentials or paid inference.

python -m panoptes_workers.probe --output artifacts/hardware-probe
"""

import argparse
import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from .infrastructure.http import block_reason, download
from .sources import ADAPTERS

SEEDS = {
    "kabum_br": "https://www.kabum.com.br/produto/162131/placa-de-video-asus-nvidia-geforce-rtx-3070-8gb-gddr6-rtx-dual-rtx3070-o8g",
    "pichau_br": "https://www.pichau.com.br/placa-de-video-mancer-geforce-rtx-3070-heimdall-x-8gb-gddr6-256-bit-mcr-rtx3070x",
    "terabyte_br": "https://www.terabyteshop.com.br/produto/42636/placa-de-video-superframe-nvidia-geforce-rtx-3070-epic-8gb-gddr6-dlss-ray-tracing-sf-gc-epnv30708gbd6",
}


async def probe_site(site, terms, output, timeout, interval, max_products):
    source = ADAPTERS[site]
    lock = asyncio.Lock()
    rows, products = [], {}
    if site in SEEDS:
        products[SEEDS[site]] = None
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={
            "User-Agent": "Panoptes/0.1 (public product availability probe)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "pt-BR,pt;q=0.9",
        },
    ) as client:

        async def fetch(stage, url, key=None, term=None):
            started = time.monotonic()
            row = {
                "site": site,
                "stage": stage,
                "source_url": url,
                "term": term,
                "captured_at": datetime.now(UTC).isoformat(),
            }
            try:
                page = await download(
                    client,
                    lock,
                    url,
                    interval,
                    allowed_hosts=source.definition.page_hosts,
                )
                body = page.body.decode(page.encoding or "utf-8", errors="replace")
                filename = f"{site}-{len(rows):02d}-{stage}.html"
                (output / filename).write_text(body, encoding="utf-8")
                row.update(
                    http_status=page.status,
                    final_url=page.final_url,
                    bytes=len(page.body),
                    sha256=hashlib.sha256(page.body).hexdigest(),
                    html_path=filename,
                )
                reason = block_reason(page)
                if reason:
                    row.update(status="blocked", reason=reason)
                elif page.status != 200:
                    row.update(
                        status="unavailable", reason=f"http_status_{page.status}"
                    )
                elif page.media_type not in ("text/html", "application/xhtml+xml"):
                    row.update(status="failed", reason="unexpected_content_type")
                elif stage == "search":
                    candidates, next_url = source.parse_search(body, uuid4(), 1)
                    from panoptes_contracts.discovery import ProductMatchCriteria

                    validations = [
                        source.validate(c, ProductMatchCriteria(title=term))
                        for c in candidates
                    ]
                    accepted = [
                        v.candidate for v in validations if v.decision == "accepted"
                    ]
                    row.update(
                        status="parsed",
                        candidates=len(candidates),
                        accepted_candidates=len(accepted),
                        next_url=next_url,
                        rejected_sample=[
                            {"title": v.candidate.title, "reason": v.reason}
                            for v in validations
                            if v.decision != "accepted"
                        ][:5],
                    )
                    for candidate in accepted[:max_products]:
                        products[str(candidate.url)] = candidate.source_key
                else:
                    if key is None:
                        from .retailers.identity import key_from_url

                        key = key_from_url(site, url)
                    detail = source.parse_product(body, page.final_url, key)
                    row.update(status="parsed", result=detail.model_dump(mode="json"))
                    row["warnings"] = [
                        field
                        for field in ("price", "availability")
                        if getattr(detail.offer, field) in (None, "unknown")
                    ]
            except Exception as error:
                row.update(
                    status="failed",
                    reason=str(error)[:400],
                    error_type=type(error).__name__,
                )
            row["duration_ms"] = round((time.monotonic() - started) * 1000)
            rows.append(row)
            print(
                json.dumps(
                    {k: v for k, v in row.items() if k != "result"}, ensure_ascii=True
                ),
                flush=True,
            )

        for term in terms:
            await fetch("search", source.search_url(term, book_only=False), term=term)
        for url, key in products.items():
            await fetch("product", url, key)
    return rows


async def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    results = await asyncio.gather(
        *(
            probe_site(
                site, args.terms, output, args.timeout, args.interval, args.max_products
            )
            for site in args.sites
        )
    )
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "transport": "public_http",
        "terms": args.terms,
        "requests": [row for rows in results for row in rows],
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/hardware-probe")
    parser.add_argument(
        "--sites", nargs="+", choices=list(ADAPTERS), default=list(ADAPTERS)
    )
    parser.add_argument(
        "--terms",
        nargs="+",
        default=[
            "rtx 3070",
            "ssd kingston nv2 1tb",
            "ssd kingston nv3 1tb",
            "ryzen 5 5600",
        ],
    )
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--interval", type=float, default=1.5)
    parser.add_argument("--max-products", type=int, default=1)
    args = parser.parse_args()
    if args.timeout <= 0 or args.interval < 0.1 or not 0 <= args.max_products <= 5:
        parser.error(
            "timeout > 0, interval >= 0.1 and max-products between 0 and 5 required"
        )
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
