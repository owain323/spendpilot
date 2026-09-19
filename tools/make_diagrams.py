"""Diagram generator — renders SpendLatch's three figure SVGs per the AGC
chart spec v1.1 (800px logical canvas, 8px grid, semantic palette, evidence
badge, source line, caption). SVG is the single master; PNG @2x is derived
via headless Edge (see --export note in README of docs/diagrams).

Spec anchors:
  Sec.1  canvas 800 logical px, 32px safe margins, 8px grid, spacing tokens
  Sec.2  font ladder 26/20/16/14, 14px hard floor
  Sec.3  semantic colors only; at most one dark hub node per figure
  Sec.4  evidence badge top-left, fixed label text
  Sec.5  nodes: radius 8, stroke 1.5, two layers (arch: three), ids in mono
  Sec.6  Manhattan edges, 2px, 10x8 arrowheads, white pill labels on edges
  Sec.7  one conclusion per figure, <= 12 core nodes
  Sec.8  title = conclusion sentence; source line under title; caption below

Usage:  python tools/make_diagrams.py    # writes docs/diagrams/*.svg + .alt.txt
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "docs" / "diagrams"

SANS = "Inter, 'Segoe UI', sans-serif"
MONO = "'Cascadia Mono', Consolas, monospace"

# Sec.3 semantic palette (fill, stroke, text)
STYLES = {
    "data":    ("#E8F0FE", "#A8C7FA", "#1A3C8F"),
    "control": ("#FFF6E0", "#F0C36D", "#7A5200"),
    "alert":   ("#FDECEA", "#F2A9A0", "#A5271F"),
    "ok":      ("#E8F5EC", "#93CFA4", "#1E6B34"),
    "hub":     ("#2B2F36", "#2B2F36", "#FFFFFF"),
    "meta":    ("#F7F8F9", "#D5D9DE", "#6B7280"),
}
EDGE_COLOR = "#57606A"
GRAY = "#6B7280"

# per-char width estimates (px) keyed by (size, mono) — verified visually
# against the @2x PNG export; conservative on purpose.
CHAR_W = {(26, False): 13.5, (20, False): 11.0, (16, False): 8.3,
          (14, False): 7.7, (16, True): 9.6, (14, True): 8.4}


def _w(text: str, size: int, mono: bool = False) -> float:
    return len(text) * CHAR_W[(size, mono)]


class Svg:
    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.parts: list[str] = []

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def text(self, x: float, y: float, s: str, size: int, color: str,
             weight: int = 400, anchor: str = "start", mono: bool = False,
             spacing: float | None = None) -> None:
        font = MONO if mono else SANS
        ls = f' letter-spacing="{spacing}"' if spacing else ""
        self.add(
            f'<text x="{x:.0f}" y="{y:.0f}" font-family="{font}" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}"{ls}>'
            f'{escape(s)}</text>')

    def rect(self, x: float, y: float, w: float, h: float, style: str,
             dashed: bool = False) -> None:
        fill, stroke, _ = STYLES[style]
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.add(
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="8" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"{dash}/>')

    def node(self, x: float, y: float, w: float, h: float, style: str,
             lines: list[tuple[str, int, int, bool]]) -> None:
        """lines: (text, size, weight, mono). Vertically centered block."""
        self.rect(x, y, w, h, style, dashed=(style == "meta"))
        color = STYLES[style][2]
        total = len(lines) * 22 - 6
        cy = y + (h - total) / 2 + size_baseline(lines[0][1])
        for text, size, weight, mono in lines:
            self.text(x + w / 2, cy, text, size, color, weight, "middle", mono)
            cy += 22

    def diamond(self, cx: float, cy: float, w: float, h: float, style: str,
                title: str, sub: str) -> None:
        fill, stroke, color = STYLES[style]
        pts = (f"{cx - w / 2:.0f},{cy:.0f} {cx:.0f},{cy - h / 2:.0f} "
               f"{cx + w / 2:.0f},{cy:.0f} {cx:.0f},{cy + h / 2:.0f}")
        self.add(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        self.text(cx, cy - 2, title, 20, color, 600, "middle")
        self.text(cx, cy + 20, sub, 16, color, 400, "middle")

    def edge(self, points: list[tuple[float, float]], dashed: bool = False) -> None:
        pts = " ".join(f"{x:.0f},{y:.0f}" for x, y in points)
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        self.add(
            f'<polyline points="{pts}" fill="none" stroke="{EDGE_COLOR}" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"{dash} '
            f'marker-end="url(#arrow)"/>')

    def pill(self, cx: float, cy: float, text: str) -> None:
        """Sec.6.5 edge label: white pill, 14px/500, masks the line at midpoint."""
        w = _w(text, 14) + 12
        self.add(f'<rect x="{cx - w / 2:.0f}" y="{cy - 11}" width="{w:.0f}" height="22" rx="11" '
                 f'fill="#FFFFFF" stroke="#E5E7EB" stroke-width="1"/>')
        self.text(cx, cy + 5, text, 14, "#374151", 500, "middle")

    def badge(self, x: float, y: float, label: str) -> float:
        """Evidence badge pill. Returns right edge x."""
        w = _w(label, 14) + 20
        self.add(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="24" rx="12" '
                 f'fill="#CFFAFE" stroke="#0E7490" stroke-opacity="0.2" stroke-width="1"/>')
        self.text(x + 10, y + 17, label, 14, "#0E7490", 600)
        return x + w

    def render(self, title: str) -> str:
        header = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
            f'width="{self.width}" height="{self.height}" role="img" aria-label="{escape(title)}">'
            f'<defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" '
            f'orient="auto"><polygon points="0,0 10,4 0,8" fill="{EDGE_COLOR}"/></marker></defs>'
            f'<rect width="{self.width}" height="{self.height}" fill="#FFFFFF"/>')
        return header + "".join(self.parts) + "</svg>"


def size_baseline(size: int) -> float:
    return int(size * 0.35) + size // 2


def header(s: Svg, title: str, source: str) -> None:
    # Evidence badge: machine-verified (the figure's content is exercised by
    # runnable checks, not asserted by hand). Legend in docs/ARCHITECTURE.md.
    s.text(32, 58, title, 26, "#111111", 700)
    end = s.badge(32, 72, "MACHINE-VERIFIED")
    s.text(end + 16, 90, source, 14, GRAY)


def lane(s: Svg, label: str, y: float, x: float = 32) -> None:
    s.text(x, y, label, 14, GRAY, 600, spacing="0.08em")


# ---------------------------------------------------------------- figure 1

def figure1() -> tuple[str, str]:
    s = Svg(800, 1008)
    header(s, "One tool layer, three surfaces, one mandate gate",
           "Source: mcp_server/, agent/, benchmarks/ — SpendLatch v0.3.0 working tree")

    # Two strict columns: left axis x=172, right axis x=484; every inter-lane
    # edge is a straight vertical on one of the two axes (no zigzag).
    lane(s, "EXPERIENCE", 124)
    s.node(32, 136, 280, 96, "data", [
        ("Web experience", 20, 600, False), ("web/ + backend.py", 16, 400, True),
        ("voice · cards · ledger", 16, 400, False)])
    s.node(344, 136, 280, 96, "data", [
        ("MCP Apps hosts", 20, 600, False), ("Claude · ChatGPT · Goose", 16, 400, False),
        ("renders ui:// approval card", 16, 400, False)])

    lane(s, "ACCESS", 284)  # short label parked clear of the edge columns
    s.node(32, 300, 280, 96, "data", [
        ("Intent routing", 20, 600, False), ("brain.py", 16, 400, True),
        ("deterministic; LLM optional", 16, 400, False)])
    s.node(344, 300, 280, 96, "data", [
        ("MCP server", 20, 600, False), ("server.py", 16, 400, True),
        ("13 tools + ui:// resource", 16, 400, False)])

    lane(s, "CORE LAYER", 452, x=620)  # parked right, clear of the y=432 pill
    s.node(32, 468, 280, 96, "data", [
        ("Pure analysis", 20, 600, False), ("tools.py", 16, 400, True),
        ("detect & prove", 16, 400, False)])
    s.node(344, 468, 280, 96, "hub", [  # the single dark adjudicator (Sec.3)
        ("Mandate gate", 20, 600, False), ("actions.py", 16, 400, True),
        ("five-gate verify", 16, 400, False)])
    s.node(364, 612, 240, 96, "data", [
        ("Provider adapters", 20, 600, False), ("adapters.py", 16, 400, True),
        ("aws·figma·zoom·openai", 16, 400, False)])

    lane(s, "STATE", 732)
    s.node(32, 744, 280, 96, "data", [
        ("State", 20, 600, False), ("store.py", 16, 400, True),
        ("budgets · mandates · receipts", 16, 400, False)])
    s.node(536, 744, 232, 96, "data", [
        ("Decision ledger", 20, 600, False), ("ledger.py", 16, 400, True),
        ("holds & refusals logged", 16, 400, False)])

    lane(s, "VERIFICATION — GATES EVERY BOX ABOVE", 870)
    s.node(32, 882, 280, 76, "meta", [
        ("Sealed benchmark", 20, 600, False), ("benchmarks/run.py", 16, 400, True)])
    s.node(536, 882, 232, 76, "meta", [
        ("Quality gates", 20, 600, False), ("run_checks.py", 16, 400, True)])

    # edges (Manhattan; pills sit only on collision-free segments, Sec.6.5)
    s.edge([(172, 232), (172, 300)])
    s.pill(172, 254, "HTTPS · /api/chat")
    s.edge([(484, 232), (484, 300)])
    s.pill(484, 254, "MCP 2025-11-25")
    s.edge([(172, 396), (172, 468)])
    s.pill(172, 432, "in-process calls")
    s.edge([(484, 396), (484, 468)])
    s.pill(484, 432, "13 tools · 4 action tools")
    s.edge([(484, 564), (484, 612)])
    s.pill(484, 588, "executes only via mandate")
    s.edge([(172, 564), (172, 744)])          # persist: straight into store top
    s.pill(172, 654, "persist")
    s.edge([(624, 516), (688, 516), (688, 744)])
    s.pill(688, 630, "decisions logged")

    s.text(400, 988, "Figure 1: One implementation, three surfaces; "
                     "the mandate gate decides what may act.", 14, GRAY, 400, "middle")
    alt = ("SpendLatch architecture: a web experience and MCP Apps hosts sit above one "
           "tool layer; every execution passes the mandate gate (dark node); state and "
           "decision ledger persist below; sealed benchmark and quality gates verify all.")
    return s.render("SpendLatch architecture"), alt


# ---------------------------------------------------------------- figure 2

def figure2() -> tuple[str, str]:
    s = Svg(800, 576)
    header(s, "Nothing executes on trust — five gates to execution",
           "Source: mcp_server/actions.py — verified by 20 tests in tests/test_actions.py")

    s.node(32, 120, 112, 76, "data", [
        ("Propose", 20, 600, False), ("proof attached", 16, 400, False)])
    s.node(240, 120, 192, 76, "control", [
        ("Approve", 20, 600, False), ("signed mandate issued", 16, 400, False)])
    s.diamond(568, 160, 192, 112, "control", "Mandate", "valid?")

    s.node(32, 288, 144, 76, "ok", [
        ("Execute", 20, 600, False), ("adapter runs", 16, 400, False)])
    s.node(240, 288, 192, 76, "ok", [
        ("Receipt", 20, 600, False), ("simulated: true", 16, 400, False)])
    s.node(600, 432, 168, 76, "alert", [
        ("Refuse", 20, 600, False), ("logged with seq", 16, 400, False)])

    # Sec.5.8 meta annotation: the five gates, spelled out
    s.node(32, 432, 312, 76, "meta", [
        ("The five gates", 16, 600, False),
        ("known · signature · unexpired", 14, 400, False),
        ("single-use · scope cap", 14, 400, False)])

    # sequence edges are label-exempt (Sec.6.4); branch edges carry conditions
    s.edge([(144, 160), (240, 160)])            # propose -> approve
    s.edge([(432, 160), (472, 160)])            # approve -> diamond (enters left vertex)
    # pass: diamond bottom -> 180-degree wrap into execute (Sec.6.9, no text on the bend)
    s.edge([(568, 216), (568, 252), (88, 252), (88, 288)])
    s.pill(568, 234, "all 5 pass")
    s.edge([(176, 326), (240, 326)])            # execute -> receipt
    # fail: dashed, exits right vertex, drops the free right column
    s.edge([(664, 160), (712, 160), (712, 432)], dashed=True)
    s.pill(712, 296, "any gate fails")

    s.text(400, 548, "Figure 2: A forged, expired, replayed, or drifted mandate "
                     "never reaches the adapter.", 14, GRAY, 400, "middle")
    alt = ("The mandate loop: propose with proof, human approves a signed mandate, five "
           "verification gates; pass reaches the adapter and returns a receipt, any "
           "failure is refused and logged.")
    return s.render("Mandate-gated execution loop"), alt


# ---------------------------------------------------------------- figure 3

def figure3() -> tuple[str, str]:
    s = Svg(800, 672)
    header(s, "Every claim is one command away from reproduction",
           "Source: docs/CLAIMS.md C1-C12 mapped to docs/evidence/ and benchmarks/results/")

    s.text(32, 120, "CLAIM", 14, GRAY, 600, spacing="0.08em")
    s.text(456, 120, "RUNNABLE PROOF", 14, GRAY, 600, spacing="0.08em")

    rows = [
        ("Detection quality", "12 sealed cases · P/R 1.0",
         "Benchmark metrics", "results/metrics.json", "sealed benchmark"),
        ("Action-loop security", "4 attack classes refused",
         "Mandate tests", "test_actions.py", "pytest -q"),
        ("MCP wire compliance", "13 tools · spec 2025-11-25",
         "Wire probe log", "mcp-roundtrip.txt", "roundtrip probe"),
        ("MCP Apps surface", "ui:// approval card served",
         "App resource + link", "approval-card.html", "roundtrip step 7"),
        ("End-to-end web flow", "9 judge criteria pass",
         "E2E transcript", "e2e-flow.txt", "e2e_flow.py"),
    ]
    y = 132
    for claim, csub, proof, pfile, cmd in rows:
        s.node(32, y, 280, 76, "control", [(claim, 20, 600, False), (csub, 16, 400, False)])
        s.node(456, y, 280, 76, "data", [(proof, 20, 600, False), (pfile, 16, 400, True)])
        s.edge([(312, y + 38), (456, y + 38)])  # solid = empirical edge (Sec.6.11)
        s.pill(384, y + 38, cmd)
        y += 100

    s.text(400, 640, "Figure 3: Claims on the left, runnable proof on the right; "
                     "nothing ships without both.", 14, GRAY, 400, "middle")
    alt = ("Five claims from the claims matrix, each linked by one reproduction command "
           "to its evidence artifact: benchmark metrics, mandate tests, MCP wire probe, "
           "MCP Apps resource, and the end-to-end transcript.")
    return s.render("Claims-to-evidence map"), alt


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    figures = {"fig1-architecture": figure1, "fig2-mandate-loop": figure2,
               "fig3-evidence-map": figure3}
    for name, build in figures.items():
        svg, alt = build()
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
        (OUT / f"{name}.alt.txt").write_text(alt + "\n", encoding="utf-8")
        print(f"wrote {name}.svg + .alt.txt")
    print("export PNG @2x: msedge --headless --force-device-scale-factor=2 "
          "--screenshot=<name>.png --window-size=800,<H> file:///<name>.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
