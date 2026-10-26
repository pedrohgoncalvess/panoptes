"""Run against frontend/tests/preview.mjs with MCP_KEYS_UI_TEST_URL configured."""

import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.skipif(
    not os.getenv("MCP_KEYS_UI_TEST_URL"), reason="Requires fixture and Chromium"
)
async def test_key_creation_admin_revocation_and_mobile():
    from playwright.async_api import async_playwright, expect

    origin = os.environ["MCP_KEYS_UI_TEST_URL"]
    artifacts = Path(__file__).resolve().parents[1] / "artifacts"
    key_name = f"Pesquisa {uuid4().hex[:8]}"
    async with async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            page = await browser.new_page(
                viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
            )
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(origin + "/", wait_until="networkidle")
            await page.get_by_label("Email", exact=True).fill("admin@panoptes.com")
            await page.get_by_label("Password", exact=True).fill("admin")
            await page.get_by_role("button", name="Sign in", exact=True).click()
            await page.wait_for_url("**/dashboard")
            await page.get_by_role("button", name="Administrator", exact=True).click()
            await page.get_by_role("link", name="MCP keys", exact=True).click()
            await page.wait_for_url("**/administrator/mcp-keys")
            await page.get_by_label("Name", exact=True).fill(key_name)
            await page.get_by_label("Create routines", exact=True).check()
            await page.get_by_label("Maximum routines created by this key").fill(
                "3"
            )
            await page.get_by_label(
                "View extractions and products from authorized routines"
            ).check()
            await page.get_by_label("Fonte de teste", exact=True).check()
            await page.get_by_label("Livros de tecnologia", exact=True).check()
            await page.get_by_label("Expiration", exact=True).select_option("custom")
            await page.get_by_label("Expires at (local time)").fill(
                (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M")
            )
            async with page.expect_request(
                lambda r: r.method == "POST" and r.url.endswith("/api/auth/mcp-keys")
            ) as created:
                await page.get_by_role("button", name="Generate key", exact=True).click()
            body = (await created.value).post_data_json
            assert body["permissions"]["max_routines"] == 3
            assert len(body["routine_ids"]) == 1 and body["expiration"] == "custom"
            assert body["expires_at"].endswith("Z")
            await expect(page.get_by_label("Generated MCP credential")).to_have_value(
                "pmcp_fixture-credential"
            )
            await page.evaluate("window.scrollTo(0, 0)")
            await page.screenshot(
                path=str(artifacts / "mcp-keys-desktop.png"), full_page=True
            )
            await page.get_by_role("button", name="Hide key").click()
            article = page.get_by_role("article").filter(has_text=key_name)
            await article.get_by_role("button", name="Revoke", exact=True).click()
            await expect(
                article.get_by_text("1 authorized routines · Revoked", exact=True)
            ).to_be_visible()
            await page.get_by_label("MCP admin — full access").check()
            await expect(page.get_by_label("Create routines", exact=True)).to_have_count(
                0
            )
            await page.get_by_label("Name", exact=True).fill("Administrador MCP")
            await page.get_by_label("Expiration", exact=True).select_option("never")
            async with page.expect_request(
                lambda r: r.method == "POST" and r.url.endswith("/api/auth/mcp-keys")
            ) as created:
                await page.get_by_role("button", name="Generate key", exact=True).click()
            body = (await created.value).post_data_json
            assert (
                body["admin"]
                and "permissions" not in body
                and "routine_ids" not in body
            )
            await expect(page.get_by_label("Generated MCP credential")).to_be_visible()
            await page.set_viewport_size({"width": 390, "height": 844})
            await expect(
                page.get_by_role("button", name="Open navigation")
            ).to_be_visible()
            await page.wait_for_function(
                "document.querySelector('.sidebar').getBoundingClientRect().right <= 0"
            )
            assert await page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            )
            await page.screenshot(
                path=str(artifacts / "mcp-keys-mobile.png"), full_page=True
            )
            await page.reload()
            await expect(page.get_by_label("Generated MCP credential")).to_have_count(0)
            assert not errors
        finally:
            await browser.close()
