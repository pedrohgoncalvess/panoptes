"""Run against frontend/tests/preview.mjs with ALERTS_UI_TEST_URL configured."""

import json
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.getenv("ALERTS_UI_TEST_URL"), reason="Requires frontend fixture and Chromium"
)
async def test_alerts_create_scope_price_edit_pause_history_mobile_delete(tmp_path):
    from playwright.async_api import async_playwright, expect

    origin = os.environ["ALERTS_UI_TEST_URL"]
    screenshots = Path(__file__).resolve().parents[1] / "artifacts"
    async with async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(origin + "/login")
            await page.get_by_label("Email", exact=True).fill("admin@panoptes.com")
            await page.get_by_label("Password", exact=True).fill("admin")
            await page.get_by_role("button", name="Sign in", exact=True).click()
            await page.wait_for_url("**/dashboard")
            await page.get_by_role("link", name="Alerts", exact=True).click()
            await expect(
                page.get_by_role("heading", name="Alerts", exact=True)
            ).to_be_visible()
            for event in (
                "extraction_started",
                "extraction_finished",
                "extraction_error",
                "price_threshold",
                "price_drop",
                "price_increase",
            ):
                await page.locator("#webhook-model-event").select_option(
                    event
                )
                async with page.expect_download() as pending_download:
                    await page.get_by_role(
                        "link", name="Download .json template", exact=True
                    ).click()
                download = await pending_download.value
                assert download.suggested_filename == f"panoptes-{event}.json"
                target = tmp_path / download.suggested_filename
                await download.save_as(target)
                payload = json.loads(target.read_text(encoding="utf-8"))
                assert payload["event"] == event
                assert payload["version"] == 1
                assert payload["matched_rules"][0]["event"] == event
                assert "request_id" in payload["data"]
            await page.get_by_role("button", name="New webhook", exact=True).click()
            await page.get_by_label("Endpoint name").fill("Alertas de tecnologia")
            await page.get_by_label("Webhook URL").fill(
                "https://example.com/eventos"
            )
            await page.get_by_label("Livros de tecnologia", exact=True).check()
            await page.get_by_role("button", name="Add rule", exact=True).click()
            await page.locator("#event-1").select_option("price_drop")
            await page.get_by_label("Minimum change (%)").fill("10.5")
            await page.get_by_role("button", name="Add rule", exact=True).click()
            await page.locator("#event-2").select_option("price_threshold")
            await page.get_by_label("Price threshold").fill("2500.00")
            await page.screenshot(
                path=str(screenshots / "alerts-form-desktop.png"), full_page=True
            )
            async with page.expect_request(
                lambda req: (
                    req.method == "POST" and req.url.endswith("/api/alerts/webhooks")
                )
            ) as saved:
                await page.get_by_role(
                    "button", name="Save webhook", exact=True
                ).click()
            data = (await saved.value).post_data_json
            assert len(data["rules"]) == 3
            assert len(data["rules"][0]["routine_ids"]) == 1
            assert data["rules"][1]["percent"] == "10.5"
            assert data["rules"][2]["threshold"] == "2500.00"
            await expect(page.get_by_role("status")).to_have_text("Webhook saved.")
            await expect(
                page.get_by_role("heading", name="Alertas de tecnologia")
            ).to_be_visible()
            await page.screenshot(
                path=str(screenshots / "alerts-desktop.png"), full_page=True
            )
            await page.get_by_role("button", name="Edit", exact=True).click()
            await expect(page.get_by_label("Price threshold")).to_have_value("2500.00")
            await page.locator("#event-0").select_option("extraction_error")
            await page.get_by_role("button", name="Save webhook", exact=True).click()
            await expect(page.get_by_role("status")).to_have_text("Webhook saved.")
            await page.get_by_role("button", name="Pause", exact=True).click()
            await expect(
                page.get_by_role("button", name="Enable", exact=True)
            ).to_be_visible()
            await page.get_by_role("button", name="Deliveries", exact=True).click()
            await expect(
                page.get_by_text("No deliveries recorded on this page.")
            ).to_be_visible()
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            )
            await page.screenshot(
                path=str(screenshots / "alerts-mobile.png"), full_page=True
            )
            await page.get_by_role("button", name="Edit", exact=True).click()
            assert await page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            )
            await page.screenshot(
                path=str(screenshots / "alerts-form-mobile.png"), full_page=True
            )
            await page.get_by_role("button", name="Cancel", exact=True).click()
            await page.get_by_role("button", name="Remove", exact=True).click()
            await page.get_by_role("button", name="Remove webhook", exact=True).click()
            await expect(page.get_by_role("status")).to_have_text("Webhook removed.")
            assert not errors
        except Exception:
            await page.screenshot(
                path=str(screenshots / "alerts-ui-failure.png"), full_page=True
            )
            (screenshots / "alerts-ui-failure.txt").write_text(
                await page.locator("body").inner_text(), encoding="utf-8"
            )
            raise
        finally:
            await browser.close()
