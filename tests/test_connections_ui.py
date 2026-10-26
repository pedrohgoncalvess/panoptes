"""Run against frontend/tests/preview.mjs with FRONTEND_TEST_RETAIL_BROWSER=1."""

import os

import pytest


@pytest.mark.skipif(
    not os.getenv("RETAIL_UI_TEST_URL"),
    reason="requires the retail frontend fixture and installed Chromium",
)
async def test_manual_save_auto_login_and_failed_save_in_ui():
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            origin = os.environ["RETAIL_UI_TEST_URL"]
            await page.goto(origin + "/login", wait_until="networkidle")
            await page.get_by_label("Email", exact=True).fill("admin@panoptes.com")
            await page.get_by_label("Password", exact=True).fill("admin")
            await page.get_by_role("button", name="Sign in", exact=True).click()
            await page.wait_for_url("**/dashboard")
            await page.goto(origin + "/connections", wait_until="networkidle")

            dialog = page.get_by_role("dialog")
            await page.get_by_role("button", name="Connect", exact=True).click()
            await expect(dialog).to_be_visible()
            # Public access must stay open across multiple polling cycles.
            for _ in range(3):
                async with page.expect_response("**/pichau_br/frame"):
                    pass
            await expect(dialog).to_be_visible()
            await page.get_by_role("button", name="Use this session").click()
            await expect(dialog).not_to_be_visible()
            await expect(page.get_by_role("status")).to_have_text("Session saved.")

            # The second fixture connection confirms login on its third frame.
            await page.get_by_role("button", name="Open browser", exact=True).click()
            await expect(dialog).to_be_visible()
            await expect(dialog).not_to_be_visible(timeout=10000)
            await expect(page.get_by_role("status")).to_have_text(
                "Sign-in confirmed. Session saved."
            )

            # A refused save must retain the modal and explain the failure.
            await page.get_by_role("button", name="Open browser", exact=True).click()
            await page.get_by_role("button", name="Use this session").click()
            await expect(dialog).to_be_visible()
            await expect(dialog.get_by_role("alert")).to_have_text(
                "Conclua a verificação da loja."
            )
            await page.get_by_role("button", name="Close", exact=True).click()
            await expect(dialog).not_to_be_visible()
        finally:
            await browser.close()
