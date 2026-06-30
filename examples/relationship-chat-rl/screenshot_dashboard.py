#!/usr/bin/env python3
"""Screenshot the Arena Dashboard Verify Stats tab."""
import sys
import time
from playwright.sync_api import sync_playwright


URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:9091"
OUT = sys.argv[2] if len(sys.argv) > 2 else "website-demo/relationship-chat-dashboard.png"
MIN_ROLLOUTS = int(sys.argv[3]) if len(sys.argv) > 3 else 0


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL)
        # Wait for the rollouts table to load.
        for _ in range(60):
            try:
                total = page.locator("#stat-total").inner_text(timeout=1000)
                if total != "--":
                    if MIN_ROLLOUTS == 0 or int(total) >= MIN_ROLLOUTS:
                        break
            except Exception:
                pass
            time.sleep(1)
        # Click Verify Stats tab.
        page.locator("button[data-tab='verify']").click()
        time.sleep(2)
        # Wait for chart canvas to appear.
        page.wait_for_selector("canvas#verify-timeline-chart", timeout=10000)
        # Screenshot the whole page.
        page.screenshot(path=OUT, full_page=True)
        browser.close()
        print(f"Screenshot saved to {OUT}")


if __name__ == "__main__":
    main()
