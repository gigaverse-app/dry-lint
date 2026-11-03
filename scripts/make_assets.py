"""
Generate dry-lint's brand assets from the mascot art in docs/assets/lint.png.

    uv run --with pillow python scripts/make_assets.py              # avatar.png, the mark, banners, social-preview.svg
    uv run --with playwright==1.58.0 python scripts/render_png.py   # social-preview.png

Lint is a ball of dryer lint with a lint roller, for picking up duplicated code. The SVGs embed a downscaled copy of
the art, so they render anywhere an <img> can show them, including GitHub READMEs.
"""

import base64
import io
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "docs" / "assets"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
PURPLE, PURPLE_LIGHT, LAVENDER, MINT = "#7E4FC9", "#C9AEF5", "#F1EAFD", "#7FD49A"


def art(height: int) -> tuple[str, int]:
    """Lint at `height` pixels, as a PNG data URI, and its width."""
    lint = Image.open(ASSETS / "lint.png")
    width = round(lint.width * height / lint.height)
    buffer = io.BytesIO()
    lint.resize((width, height), Image.LANCZOS).save(buffer, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(), width


def avatar(size: int = 512) -> Image.Image:
    lint = Image.open(ASSETS / "lint.png")
    scale = size * 0.86 / max(lint.size)
    lint = lint.resize((round(lint.width * scale), round(lint.height * scale)), Image.LANCZOS)
    tile = Image.new("RGBA", (size, size), LAVENDER)
    tile.alpha_composite(lint, ((size - lint.width) // 2, (size - lint.height) // 2))
    return tile.convert("RGB")


def mark() -> str:
    uri, width = art(168)
    shown = 56 * width / 168
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64" role="img" aria-label="dry-lint">
<title>dry-lint</title>
<rect width="64" height="64" rx="15" fill="{LAVENDER}"/>
<image href="{uri}" x="{(64 - shown) / 2:.1f}" y="4" width="{shown:.1f}" height="56"/>
</svg>
"""


def banner(dark: bool) -> str:
    bg, stroke, ink, sub, track = (
        ("#0D1117", "#30363D", "#F0F6FC", "#9198A1", "#21262D") if dark else ("#FFFFFF", "#D1D9E0", "#1F2328", "#59636E", "#F3EFFA")
    )
    accent = PURPLE_LIGHT if dark else PURPLE
    uri, width = art(156)
    shown = 50 * width / 156

    def block(x: float, lines: list[int]) -> str:
        rows = "".join(
            f'<rect x="{x + 7}" y="{14 + i * 7}" width="{w}" height="3" rx="1.5" fill="{accent if i in (1, 2) else sub}" '
            f'opacity="{0.9 if i in (1, 2) else 0.45}"/>'
            for i, w in enumerate(lines)
        )
        return f'<rect x="{x}" y="9" width="44" height="38" rx="6" fill="{track}"/>{rows}'

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="56" viewBox="0 0 640 56" role="img" aria-label="dry-lint duplication report">
  <title>dry-lint duplication report</title>
  <rect x="0.5" y="0.5" width="639" height="55" rx="10" fill="{bg}" stroke="{stroke}"/>
  <image href="{uri}" x="12" y="3" width="{shown:.1f}" height="50"/>
  <text x="{22 + shown:.0f}" y="36" font-family="{FONT}" font-size="25" font-weight="800" letter-spacing="-0.5" fill="{ink}">dry<tspan fill="{accent}">-lint</tspan></text>
  <text x="{130 + shown:.0f}" y="25" font-family="{FONT}" font-size="12" font-weight="600" fill="{sub}">duplication report</text>
  <text x="{130 + shown:.0f}" y="41" font-family="{FONT}" font-size="12" fill="{sub}">one concept · one implementation</text>
  {block(470, [24, 30, 22, 16])}
  {block(580, [20, 30, 22, 26])}
  <path d="M514 28 C 534 14, 560 14, 580 28" fill="none" stroke="{accent}" stroke-width="1.6" stroke-dasharray="3 3"/>
  <circle cx="547" cy="18.5" r="8" fill="{bg}" stroke="{MINT}" stroke-width="1.6"/>
  <text x="547" y="22.5" text-anchor="middle" font-family="{FONT}" font-size="11" font-weight="800" fill="{accent}">≈</text>
</svg>
"""


def social_preview() -> str:
    uri, width = art(440)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640" role="img" aria-label="dry-lint">
<title>dry-lint</title>
<rect width="1280" height="640" fill="#0D1117"/>
<circle cx="{90 + width / 2:.0f}" cy="330" r="250" fill="{PURPLE}" opacity="0.18"/>
<image href="{uri}" x="90" y="100" width="{width}" height="440"/>
<text x="{170 + width}" y="290" font-family="{FONT}" font-size="104" font-weight="800" letter-spacing="-2" fill="#F0F6FC">dry<tspan fill="{PURPLE_LIGHT}">-lint</tspan></text>
<text x="{174 + width}" y="358" font-family="{FONT}" font-size="34" fill="#9198A1">One concept, one implementation.</text>
<text x="{174 + width}" y="406" font-family="{FONT}" font-size="25" fill="#6E7681">Finds code that re-solves what your codebase</text>
<text x="{174 + width}" y="440" font-family="{FONT}" font-size="25" fill="#6E7681">already does, judges it, and comments on the PR.</text>
</svg>
"""


def main() -> None:
    avatar().save(ASSETS / "avatar.png", optimize=True)
    print("wrote docs/assets/avatar.png")
    files = {
        "dry-lint-mark.svg": mark(),
        "sticky-banner-light.svg": banner(dark=False),
        "sticky-banner-dark.svg": banner(dark=True),
        "social-preview.svg": social_preview(),
    }
    for name, content in files.items():
        (ASSETS / name).write_text(content)
        print(f"wrote docs/assets/{name} ({len(content) // 1024} KB)")


if __name__ == "__main__":
    main()
