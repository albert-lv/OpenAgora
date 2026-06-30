#!/usr/bin/env python3
"""Capture Code Colosseum dashboard screenshots for the website."""

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright


async def capture_tab(page, tab_text: str, filename: str, wait: int = 3):
    # Find nav button by its text content; command-center has an icon inside, so
    # search for the button element whose text contains the tab label.
    btn = page.locator(f"nav button:has-text('{tab_text}')")
    await btn.wait_for(state="visible")
    await btn.click()
    await asyncio.sleep(wait)
    await page.screenshot(path=filename, full_page=False)
    print(f"Saved {filename}")


async def main(dashboard_url: str, output_dir: str):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        await page.goto(dashboard_url.rstrip("/"))
        await asyncio.sleep(3)

        await page.screenshot(path=str(out / "code-colosseum-dashboard.png"), full_page=False)
        print(f"Saved {out / 'code-colosseum-dashboard.png'}")

        await capture_tab(page, "Arena", str(out / "code-colosseum-arena.png"))
        await capture_tab(page, "Benchmark", str(out / "code-colosseum-benchmark.png"))
        await capture_tab(page, "Trajectory", str(out / "code-colosseum-trajectory.png"))

        await browser.close()


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
    path = sys.argv[2] if len(sys.argv) > 2 else "."
    asyncio.run(main(url, path))
