"""
Generate dry-lint's brand assets from the mascot art in docs/assets/lint.png.

    uv run --with pillow python scripts/make_assets.py              # avatar.png, the mark, banners, README hero, social preview, the sign's Lint
    uv run --with playwright==1.58.0 python scripts/render_png.py   # social-preview.png

Lint is a purple ball of dryer lint with a mint-green hair dryer. The SVGs embed a downscaled copy of
the art, so they render anywhere an <img> can show them, including GitHub READMEs.
"""

import base64
import io
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "docs" / "assets"
COUNTER = ASSETS.parents[1] / "counter" / "src"
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
        ("#0D1117", "#30363D", "#F0F6FC", "#9198A1", "#21262D")
        if dark
        else ("#FFFFFF", "#D1D9E0", "#1F2328", "#59636E", "#F3EFFA")
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


def hero(dark: bool) -> str:
    """The README's full-width banner: Lint, the name, and two look-alike functions judged one concept."""
    top, bottom, stroke, ink, sub, card, glow = (
        ("#0D1117", "#1A1030", "#30363D", "#F0F6FC", "#9198A1", "#161B22", 0.22)
        if dark
        else ("#FFFFFF", "#F3ECFD", "#D1D9E0", "#1F2328", "#59636E", "#FFFFFF", 0.55)
    )
    accent = PURPLE_LIGHT if dark else PURPLE
    halo = PURPLE if dark else PURPLE_LIGHT
    mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    uri, width = art(560)
    shown = 272 * width / 560

    def code(x: int, name: str, rows: list[int]) -> str:
        lines = "".join(
            f'<rect x="{x + 18}" y="{132 + i * 20}" width="{w}" height="7" rx="3.5" fill="{accent if i in (1, 2) else sub}" '
            f'opacity="{0.95 if i in (1, 2) else 0.35}"/>'
            for i, w in enumerate(rows)
        )
        return (
            f'<rect x="{x}" y="96" width="160" height="150" rx="14" fill="{card}" stroke="{stroke}"/>'
            f'<text x="{x + 18}" y="120" font-family="{mono}" font-size="14" font-weight="600" fill="{ink}">{name}</text>{lines}'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="320" viewBox="0 0 1280 320" role="img" aria-label="dry-lint: one concept, one implementation">
  <title>dry-lint: one concept, one implementation</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>
    <radialGradient id="halo"><stop offset="0" stop-color="{halo}" stop-opacity="{glow}"/><stop offset="1" stop-color="{halo}" stop-opacity="0"/></radialGradient>
  </defs>
  <rect x="1" y="1" width="1278" height="318" rx="22" fill="url(#bg)" stroke="{stroke}" stroke-width="2"/>
  <circle cx="176" cy="164" r="170" fill="url(#halo)"/>
  <image href="{uri}" x="{176 - shown / 2:.1f}" y="26" width="{shown:.1f}" height="272"/>
  <text x="340" y="150" font-family="{FONT}" font-size="92" font-weight="800" letter-spacing="-2" fill="{ink}">dry<tspan fill="{accent}">-lint</tspan></text>
  <text x="344" y="204" font-family="{FONT}" font-size="30" font-weight="600" fill="{ink}">One concept, one implementation.</text>
  <text x="344" y="244" font-family="{FONT}" font-size="20" fill="{sub}">Catches new code that re-solves what already exists.</text>
  {code(904, "preview_text()", [92, 120, 104, 70, 50])}
  {code(1094, "shorten_text()", [80, 112, 120, 58, 86])}
  <path d="M984 94 C 1010 40, 1148 40, 1174 94" fill="none" stroke="{accent}" stroke-width="2.5" stroke-dasharray="6 6"/>
  <circle cx="1079" cy="53" r="17" fill="{top}" stroke="{MINT}" stroke-width="2.5"/>
  <text x="1079" y="61" text-anchor="middle" font-family="{FONT}" font-size="22" font-weight="800" fill="{accent}">≈</text>
  <rect x="984" y="262" width="190" height="32" rx="16" fill="{MINT}" fill-opacity="{0.16 if dark else 0.28}" stroke="{MINT}"/>
  <text x="1079" y="283" text-anchor="middle" font-family="{FONT}" font-size="14" font-weight="700" fill="{ink}">one concept · judge 0.91</text>
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
        "readme-hero-light.svg": hero(dark=False),
        "readme-hero-dark.svg": hero(dark=True),
        "social-preview.svg": social_preview(),
    }
    for name, content in files.items():
        (ASSETS / name).write_text(content)
        print(f"wrote docs/assets/{name} ({len(content) // 1024} KB)")
    uri, _ = art(240)
    (COUNTER / "lint.js").write_text(
        f'// Generated by scripts/make_assets.py: Lint, for the counter\'s sign.\nexport const LINT = "{uri}";\n'
    )
    print(f"wrote counter/src/lint.js ({len(uri) // 1024} KB)")


if __name__ == "__main__":
    main()
