"""
Generate dry-lint's brand assets: the lint avatar, the mark, and the light and dark banners.

    python scripts/make_assets.py            # writes docs/assets/*.svg
    uv run --with playwright==1.58.0 python scripts/render_png.py   # avatar.png and social-preview.png

The avatar is Lint, a piece of dryer lint: a felted ball, fuzzy at the edge, with a few stray coloured threads, a
blow-dried pompadour and the blow dryer that did it.
It is drawn procedurally from a fixed seed, so every run produces the same file.
"""

import math
import random
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "docs" / "assets"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
TEAL_DARK, TEAL, TEAL_LIGHT = "#0F766E", "#14B8A6", "#5EEAD4"
LINT_GREYS = ["#8E8A9E", "#A19DB0", "#B4B0C2", "#C7C3D3", "#D9D6E2", "#ECEAF2", "#F7F6FA"]
THREADS = ["#2563EB", "#DC2626", "#F59E0B"]


def blob_radius(theta: float, base: float, wobble: list[tuple[int, float, float]]) -> float:
    return base * (1 + sum(amp * math.sin(k * theta + phase) for k, amp, phase in wobble))


def blow_dryer(x: float, y: float, angle: float, scale: float) -> str:
    """A retro red blow dryer gripped at (x, y), nozzle pointing along `angle` degrees from the left, puffing air."""
    air = "".join(
        f'<path d="M-86,{dy} q-8,-6 -16,0 t-16,0 t-16,0" stroke="#E0F2FE" stroke-width="3" stroke-linecap="round" '
        f'fill="none" opacity="0.6" stroke-dasharray="10 9"/>'
        for dy in (-54, -42, -30)
    )
    return f"""<g transform="translate({x:.1f} {y:.1f}) rotate({angle:.0f}) scale({scale:.3f})">
  <rect x="-10" y="-34" width="20" height="62" rx="9" fill="#B91C1C"/>
  <rect x="-4" y="-22" width="8" height="12" rx="3" fill="#FCA5A5"/>
  <polygon points="-52,-53 -82,-50 -82,-34 -52,-31" fill="#CBD5E1" stroke="#64748B" stroke-width="2"/>
  <rect x="-58" y="-58" width="82" height="32" rx="16" fill="#EF4444"/>
  <rect x="-50" y="-53" width="56" height="6" rx="3" fill="#FFFFFF" opacity="0.45"/>
  <circle cx="24" cy="-42" r="20" fill="#DC2626"/>
  <circle cx="24" cy="-42" r="12" fill="#7F1D1D"/>
  <circle cx="24" cy="-42" r="7" fill="none" stroke="#FCA5A5" stroke-width="2"/>
  {air}
</g>"""


def lint(cx: float, cy: float, base: float, seed: int, detail: float = 1.0, threads: bool = True,
         pose: str = "full") -> str:
    """
    An SVG group: Lint, the mascot. A matted wad with felted layers, fibres lying every which way, a fuzzy rim and
    curly threads, a blow-dried pompadour and a winking face; the full pose adds feet, a thumbs-up and the blow dryer.
    """
    rng = random.Random(seed)
    squash = 0.8
    wobble = [(k, rng.uniform(0.03, 0.1) / k**0.35, rng.uniform(0, math.tau)) for k in range(2, 8)]

    def edge(theta: float, scale: float = 1.0) -> tuple[float, float]:
        r = blob_radius(theta, base, wobble) * scale
        return cx + r * math.cos(theta), cy + r * squash * math.sin(theta)

    def outline(scale: float, jitter: float) -> str:
        pts = [edge(math.tau * i / 120, scale * rng.uniform(1 - jitter, 1 + jitter)) for i in range(120)]
        return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z"

    def inside(max_r: float = 0.9) -> tuple[float, float]:
        theta, r = rng.uniform(0, math.tau), math.sqrt(rng.uniform(0, 1)) * max_r
        return edge(theta, r)

    def curl(x0: float, y0: float, angle: float, length: float, bends: int, width: float, colour: str, opacity: float,
             turn: float = 1.1) -> str:
        d, x, y = [f"M{x0:.1f},{y0:.1f}"], x0, y0
        for _ in range(bends):
            angle += rng.uniform(-turn, turn)
            step = length / bends
            cx1, cy1 = x + step * 0.5 * math.cos(angle + rng.uniform(-0.8, 0.8)), y + step * 0.5 * math.sin(angle + rng.uniform(-0.8, 0.8))
            x, y = x + step * math.cos(angle), y + step * math.sin(angle)
            d.append(f"Q{cx1:.1f},{cy1:.1f} {x:.1f},{y:.1f}")
        return (f'<path d="{" ".join(d)}" stroke="{colour}" stroke-width="{width:.2f}" stroke-linecap="round" '
                f'fill="none" opacity="{opacity:.2f}"/>')

    unit = base / 150
    b = base
    parts = [f'<ellipse cx="{cx:.1f}" cy="{cy + b * squash * 1.1:.1f}" rx="{b * 0.85:.1f}" ry="{b * 0.12:.1f}" fill="#000" opacity="0.2"/>']
    if pose == "full":
        # little felt feet, then fluffy arms: one giving a thumbs-up, one holding the blow dryer
        for side in (-1, 1):
            parts.append(f'<ellipse cx="{cx + side * b * 0.34:.1f}" cy="{cy + b * squash * 0.98:.1f}" rx="{b * 0.2:.1f}" '
                         f'ry="{b * 0.11:.1f}" fill="#CFCBDB" stroke="#A9A5B9" stroke-width="{2 * unit:.1f}"/>')
        arms = [(cx - b * 0.78, cy + b * 0.15, cx - b * 1.1, cy - b * 0.18), (cx + b * 0.76, cy + b * 0.1, cx + b * 1.12, cy - b * 0.3)]
        for x0, y0, x1, y1 in arms:
            parts.append(f'<path d="M{x0:.1f},{y0:.1f} Q{(x0 + x1) / 2:.1f},{max(y0, y1) + b * 0.08:.1f} {x1:.1f},{y1:.1f}" '
                         f'stroke="#C9C5D5" stroke-width="{b * 0.14:.1f}" stroke-linecap="round" fill="none"/>')
            for _ in range(int(40 * detail)):
                t = rng.uniform(0, 1)
                x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                parts.append(curl(x, y, rng.uniform(0, math.tau), b * rng.uniform(0.04, 0.09), 2, 1.1 * unit,
                                  rng.choice(LINT_GREYS[1:]), 0.75))
        tx, ty = arms[0][2], arms[0][3]
        parts.append(f'<ellipse cx="{tx + b * 0.01:.1f}" cy="{ty - b * 0.15:.1f}" rx="{b * 0.045:.1f}" ry="{b * 0.1:.1f}" '
                     f'fill="#DAD7E4" stroke="#A9A5B9" stroke-width="{2 * unit:.1f}"/>')
        parts.append(f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="{b * 0.12:.1f}" fill="#DAD7E4" stroke="#A9A5B9" stroke-width="{2 * unit:.1f}"/>')
        hx, hy = arms[1][2], arms[1][3]
        on_top = [blow_dryer(hx, hy, 8, b / 110),
                  f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="{b * 0.11:.1f}" fill="#DAD7E4" stroke="#A9A5B9" stroke-width="{2 * unit:.1f}"/>']
    else:
        on_top = []
    parts.append(f'<path d="{outline(1.0, 0.012)}" fill="url(#felt)"/>')
    # felted layers: a few lighter and darker matted patches
    for _ in range(int(7 * max(detail, 0.4))):
        px, py = inside(0.55)
        rx, ry = base * rng.uniform(0.18, 0.4), base * squash * rng.uniform(0.12, 0.3)
        tone = rng.choice(["#FFFFFF", "#ECEAF3", "#BDB9CB", "#A7A3B6"])
        parts.append(f'<ellipse cx="{px:.1f}" cy="{py:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="{tone}" opacity="0.28" '
                     f'transform="rotate({rng.uniform(-40, 40):.0f} {px:.1f} {py:.1f})"/>')
    if threads:
        # stray coloured threads, partly buried under the fibres that come next
        for colour in THREADS:
            x0, y0 = edge(rng.uniform(0.25, 0.75) * math.pi, rng.uniform(0.5, 0.7))
            parts.append(curl(x0, y0, rng.choice([0.2, math.pi - 0.2]) + rng.uniform(-0.4, 0.4), base * rng.uniform(0.4, 0.65), 6, 1.8 * unit, colour, 0.85, turn=0.55))
    # matted fibres lying every which way across the surface
    for _ in range(int(520 * detail)):
        x0, y0 = inside(0.92)
        parts.append(curl(x0, y0, rng.uniform(0, math.tau), base * rng.uniform(0.06, 0.2), 2,
                          rng.uniform(0.7, 1.4) * unit, rng.choice(LINT_GREYS), rng.uniform(0.3, 0.7)))
    # fuzzy rim: short fibres along the edge, mostly tangential, poking a little outward
    for _ in range(int(380 * detail)):
        theta = rng.uniform(0, math.tau)
        x0, y0 = edge(theta, rng.uniform(0.9, 1.0))
        outward = math.atan2((y0 - cy) / squash, x0 - cx)
        angle = outward + rng.choice([-1, 1]) * rng.uniform(0.6, 1.4)
        parts.append(curl(x0, y0, angle, base * rng.uniform(0.06, 0.15), 2,
                          rng.uniform(0.8, 1.5) * unit, rng.choice(LINT_GREYS[2:]), rng.uniform(0.5, 0.9)))
    for _ in range(int(12 * detail)):
        x, y = edge(rng.uniform(0, math.tau), rng.uniform(1.12, 1.3))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rng.uniform(0.8, 1.7) * unit:.1f}" fill="#E8E6EF" opacity="0.65"/>')
    # the hair: a glossy blow-dried pompadour sweeping forward, with sideburns and one loose curl
    def at(dx: float, dy: float) -> str:
        return f"{cx + dx * b:.1f},{cy + dy * b:.1f}"

    def hair(dx: float, dy: float) -> str:
        return at(dx * 0.92, dy + 0.17)

    if pose == "full":
        for side in (-1, 1):
            parts.append(f'<path d="M{hair(side * 0.6, -0.5)} Q{hair(side * 0.72, -0.32)} {hair(side * 0.66, -0.16)} '
                         f'Q{hair(side * 0.58, -0.3)} {hair(side * 0.5, -0.46)} Z" fill="url(#hair)"/>')
    parts.append(f'<path d="M{hair(0.64, -0.42)} C{hair(0.78, -0.82)} {hair(0.45, -1.06)} {hair(0.05, -1.12)} '
                 f'C{hair(-0.3, -1.18)} {hair(-0.52, -1.42)} {hair(-0.84, -1.28)} C{hair(-1.08, -1.16)} {hair(-1.0, -0.84)} {hair(-0.76, -0.84)} '
                 f'C{hair(-0.55, -0.68)} {hair(-0.2, -0.66)} {hair(0.0, -0.7)} C{hair(0.25, -0.62)} {hair(0.45, -0.6)} {hair(0.64, -0.42)} Z" '
                 f'fill="url(#hair)"/>')
    # the front roll, and the gloss of a fresh blow-dry
    parts.append(f'<path d="M{hair(-0.7, -0.92)} C{hair(-0.92, -0.9)} {hair(-0.95, -1.18)} {hair(-0.76, -1.2)} '
                 f'C{hair(-0.62, -1.2)} {hair(-0.6, -1.04)} {hair(-0.72, -1.02)}" stroke="#64748B" '
                 f'stroke-width="{max(b * 0.03, 0.6):.1f}" stroke-linecap="round" fill="none" opacity="0.8"/>')
    for k, (w, o) in enumerate(((0.05, 0.55), (0.03, 0.4), (0.02, 0.3))):
        parts.append(f'<path d="M{hair(0.52 - k * 0.1, -0.56 - k * 0.04)} C{hair(0.45 - k * 0.08, -0.95 + k * 0.04)} '
                     f'{hair(-0.1, -1.12 + k * 0.06)} {hair(-0.55 + k * 0.08, -1.3 + k * 0.1)}" stroke="#A5B4CC" '
                     f'stroke-width="{max(b * w, 0.6):.1f}" stroke-linecap="round" fill="none" opacity="{o}"/>')
    parts.append(f'<path d="M{hair(-0.74, -0.86)} q{b * -0.08:.1f},{b * 0.08:.1f} {b * 0.0:.1f},{b * 0.15:.1f} '
                 f't{b * -0.04:.1f},{b * 0.12:.1f}" stroke="#2B3040" stroke-width="{max(b * 0.035, 0.9):.1f}" '
                 f'stroke-linecap="round" fill="none"/>')
    # the face: one big shiny eye, one wink, rosy cheeks, a lopsided grin
    ey = cy - b * 0.1
    parts.append(f'<path d="M{at(-0.42, -0.08)} Q{at(-0.3, -0.24)} {at(-0.18, -0.08)}" stroke="#1F2328" '
                 f'stroke-width="{max(b * 0.05, 1.4):.1f}" stroke-linecap="round" fill="none"/>')
    ex = cx + b * 0.3
    parts.append(f'<ellipse cx="{ex:.1f}" cy="{ey:.1f}" rx="{b * 0.115:.1f}" ry="{b * 0.15:.1f}" fill="#1F2328"/>')
    parts.append(f'<circle cx="{ex - b * 0.035:.1f}" cy="{ey - b * 0.055:.1f}" r="{b * 0.045:.1f}" fill="#FFFFFF"/>')
    parts.append(f'<circle cx="{ex + b * 0.04:.1f}" cy="{ey + b * 0.05:.1f}" r="{b * 0.02:.1f}" fill="#FFFFFF" opacity="0.85"/>')
    for side in (-1, 1):
        parts.append(f'<ellipse cx="{cx + side * b * 0.5:.1f}" cy="{ey + b * 0.22:.1f}" rx="{b * 0.11:.1f}" ry="{b * 0.065:.1f}" '
                     f'fill="#F472B6" opacity="0.55"/>')
    parts.append(f'<path d="M{at(-0.13, 0.13)} Q{at(0.0, 0.27)} {at(0.15, 0.08)}" stroke="#1F2328" '
                 f'stroke-width="{max(b * 0.035, 1.2):.1f}" stroke-linecap="round" fill="none"/>')
    return "\n".join(parts + on_top)


DEFS = f"""<defs>
  <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{TEAL}"/><stop offset="1" stop-color="{TEAL_DARK}"/>
  </linearGradient>
  <linearGradient id="hair" x1="0" y1="0" x2="0.3" y2="1">
    <stop offset="0" stop-color="#475569"/><stop offset="0.5" stop-color="#2B3040"/><stop offset="1" stop-color="#171A23"/>
  </linearGradient>
  <radialGradient id="felt" cx="0.42" cy="0.36" r="0.75">
    <stop offset="0" stop-color="#F4F3F8"/><stop offset="0.55" stop-color="#D3D0DE"/><stop offset="1" stop-color="#A9A5B9"/>
  </radialGradient>
</defs>"""


def avatar() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512" role="img" aria-label="dry-lint">
<title>dry-lint</title>
{DEFS}
<rect width="512" height="512" fill="url(#tile)"/>
{lint(222, 304, 112, seed=7)}
</svg>
"""


def mark(size: int = 64) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 64 64" role="img" aria-label="dry-lint">
<title>dry-lint</title>
{DEFS}
<rect width="64" height="64" rx="15" fill="url(#tile)"/>
{lint(32, 38, 20, seed=7, detail=0.4, threads=True, pose="face")}
</svg>
"""


def banner(dark: bool) -> str:
    bg, stroke, ink, sub, track = (
        ("#0D1117", "#30363D", "#F0F6FC", "#9198A1", "#21262D") if dark else ("#FFFFFF", "#D1D9E0", "#1F2328", "#59636E", "#EFF2F5")
    )
    accent = TEAL_LIGHT if dark else TEAL_DARK

    def block(x: float, lines: list[int], highlight: str | None) -> str:
        rows = "".join(
            f'<rect x="{x + 7}" y="{14 + i * 7}" width="{w}" height="3" rx="1.5" fill="{highlight if highlight and i in (1, 2) else sub}" opacity="{0.9 if highlight and i in (1, 2) else 0.45}"/>'
            for i, w in enumerate(lines)
        )
        return f'<rect x="{x}" y="9" width="44" height="38" rx="6" fill="{track}"/>{rows}'

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="56" viewBox="0 0 640 56" role="img" aria-label="dry-lint duplication report">
  <title>dry-lint duplication report</title>
  {DEFS}
  <rect x="0.5" y="0.5" width="639" height="55" rx="10" fill="{bg}" stroke="{stroke}"/>
  <g transform="translate(10 8) scale(0.625)">
    <rect width="64" height="64" rx="15" fill="url(#tile)"/>
    {lint(32, 38, 20, seed=7, detail=0.4, pose="face")}
  </g>
  <text x="62" y="36" font-family="{FONT}" font-size="25" font-weight="800" letter-spacing="-0.5" fill="{ink}">dry<tspan fill="{accent}">-lint</tspan></text>
  <text x="170" y="25" font-family="{FONT}" font-size="12" font-weight="600" fill="{sub}">duplication report</text>
  <text x="170" y="41" font-family="{FONT}" font-size="12" fill="{sub}">one concept · one implementation</text>
  {block(470, [24, 30, 22, 16], accent)}
  {block(580, [20, 30, 22, 26], accent)}
  <path d="M514 28 C 534 14, 560 14, 580 28" fill="none" stroke="{accent}" stroke-width="1.6" stroke-dasharray="3 3"/>
  <circle cx="547" cy="18.5" r="8" fill="{bg}" stroke="{accent}" stroke-width="1.4"/>
  <text x="547" y="22.5" text-anchor="middle" font-family="{FONT}" font-size="11" font-weight="800" fill="{accent}">≈</text>
</svg>
"""


def social_preview() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640" role="img" aria-label="dry-lint">
<title>dry-lint</title>
{DEFS}
<rect width="1280" height="640" fill="#0D1117"/>
<g transform="translate(96 140) scale(0.70)"><rect width="512" height="512" rx="110" fill="url(#tile)"/>{lint(222, 304, 112, seed=7)}</g>
<text x="520" y="300" font-family="{FONT}" font-size="104" font-weight="800" letter-spacing="-2" fill="#F0F6FC">dry<tspan fill="{TEAL_LIGHT}">-lint</tspan></text>
<text x="524" y="368" font-family="{FONT}" font-size="34" fill="#9198A1">One concept, one implementation.</text>
<text x="524" y="416" font-family="{FONT}" font-size="26" fill="#6E7681">Finds code that re-solves what your codebase already does,</text>
<text x="524" y="452" font-family="{FONT}" font-size="26" fill="#6E7681">judges it, and comments on the pull request.</text>
</svg>
"""


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    files = {
        "avatar.svg": avatar(),
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
