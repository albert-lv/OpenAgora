#!/usr/bin/env python3
"""Capture Arena Dashboard screenshots for the relationship-chat-rl demo."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

DASHBOARD_URL = "http://localhost:9091"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}


async def capture_tab(page, tab_name: str, filename: str):
    tab_btn = page.locator(f"button[data-tab='{tab_name}']")
    await tab_btn.wait_for(state="visible")
    await tab_btn.click()
    # Wait for content to render / charts to animate.
    await asyncio.sleep(3)
    await page.screenshot(path=str(OUTPUT_DIR / filename), full_page=True)
    print(f"Saved {filename}")


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport=VIEWPORT)
        await page.goto(DASHBOARD_URL)
        await asyncio.sleep(3)  # Let initial data load.

        await page.screenshot(
            path=str(OUTPUT_DIR / "relationship-chat-rollouts.png"), full_page=True
        )
        print("Saved relationship-chat-rollouts.png")

        await capture_tab(page, "verify", "relationship-chat-verify-stats.png")
        await capture_tab(page, "tokens", "relationship-chat-token-stats.png")

        # Re-open rollouts so the first tab is active again for any future captures.
        await page.locator("button[data-tab='rollouts']").click()
        await asyncio.sleep(1)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
