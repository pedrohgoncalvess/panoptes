"""Submit work to the management API; workers execute queued requests."""

import argparse
import asyncio
import json
import os

import httpx
from panoptes_contracts.sources import SOURCES


async def submit(args):
    async with httpx.AsyncClient(base_url=args.api_url, timeout=30) as client:
        login = await client.post(
            "/auth/login", json={"email": args.email, "password": args.password}
        )
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        if args.command == "discover":
            if args.category:
                criteria = {
                    "match_mode": "category",
                    "category": args.category,
                    "required_attributes": json.loads(args.attributes),
                    "brands": args.brands,
                }
            else:
                criteria = {
                    "title": args.title or args.term,
                    "authors": args.authors,
                    "isbn": args.isbn,
                }
            response = await client.post(
                "/search-terms",
                json={
                    "site": args.site,
                    "term": args.term,
                    "criteria": criteria,
                    "max_pages": args.pages,
                    "max_candidates": args.max_candidates,
                    "refresh_interval_seconds": args.interval,
                },
            )
            response.raise_for_status()
            term = response.json()
            response = await client.post(f"/search-terms/{term['public_id']}/discover")
            response.raise_for_status()
            print(
                json.dumps(
                    {"search_term": term, "request": response.json()},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "refresh":
            response = await client.post(f"/products/{args.product_id}/refresh")
            response.raise_for_status()
            print(json.dumps(response.json(), indent=2))
        elif args.command == "products":
            response = await client.get(f"/search-terms/{args.term_id}/products")
            response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))
        else:
            response = await client.get(f"/scrape-requests/{args.request_id}")
            response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument(
        "--email", default=os.getenv("PANOPTES_EMAIL", "admin@panoptes.com")
    )
    parser.add_argument("--password", default=os.getenv("PANOPTES_PASSWORD", "admin"))
    commands = parser.add_subparsers(dest="command", required=True)
    discovery = commands.add_parser("discover")
    discovery.add_argument("term")
    discovery.add_argument("--site", choices=list(SOURCES), default="amazon_br")
    discovery.add_argument("--title")
    discovery.add_argument("--authors", nargs="*", default=[])
    discovery.add_argument("--isbn", nargs="*", default=[])
    discovery.add_argument("--pages", type=int, default=1)
    discovery.add_argument(
        "--category", choices=["television", "refrigerator", "book", "school_supplies"]
    )
    discovery.add_argument(
        "--attributes", default="{}", help="JSON of required normalized attributes"
    )
    discovery.add_argument("--brands", nargs="*", default=[])
    discovery.add_argument("--max-candidates", type=int, default=100)
    discovery.add_argument("--interval", type=int, default=86400)
    commands.add_parser("refresh").add_argument("product_id")
    commands.add_parser("status").add_argument("request_id")
    commands.add_parser("products").add_argument("term_id")
    asyncio.run(submit(parser.parse_args()))


if __name__ == "__main__":
    main()
