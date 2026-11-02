"""
Render the PNG assets from their SVG sources with headless Chromium.

    uv run --with playwright==1.58.0 python scripts/render_png.py

Writes docs/assets/avatar.png (512x512, for the GitHub avatar) and docs/assets/social-preview.png (1280x640).
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ASSETS = Path(__file__).resolve().parents[1] / "docs" / "assets"
TARGETS = [("avatar.svg", "avatar.png", 512, 512), ("social-preview.svg", "social-preview.png", 1280, 640)]


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for source, target, width, height in TARGETS:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(f"<html><body style='margin:0'>{(ASSETS / source).read_text()}</body></html>")
            page.screenshot(path=str(ASSETS / target), clip={"x": 0, "y": 0, "width": width, "height": height})
            print(f"wrote docs/assets/{target}")
        browser.close()


if __name__ == "__main__":
    main()
