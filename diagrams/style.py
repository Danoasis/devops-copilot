"""Shared drawing kit for the architecture diagrams.

Everything is plain matplotlib (no graphviz binary, no extra system deps) so
`uv run python diagrams/<name>.py` works anywhere the repo runs. Each diagram
script owns its layout; this module owns the look, so all diagrams stay
visually consistent.

Palette semantics (one color per architectural layer, reused everywhere):
    pipeline  blue    — Azure DevOps / CI / CD / Eval
    service   teal    — FastAPI (day 3)
    agent     purple  — agent loop + MCP client (day 2)
    model     orange  — Ollama / LLMs
    data      green   — KB, sqlite-vec, ingest
    obs       amber   — Prometheus, Grafana, Jaeger / OTel
    ops       red     — kubectl tools, kind cluster (day 5)
"""
from __future__ import annotations

from dataclasses import dataclass

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

PALETTE = {
    "pipeline": "#2563eb",
    "service":  "#0d9488",
    "agent":    "#7c3aed",
    "model":    "#ea580c",
    "data":     "#16a34a",
    "obs":      "#d97706",
    "ops":      "#dc2626",
    "neutral":  "#475569",
}
BG = "#f8fafc"
INK = "#0f172a"
FONT = "DejaVu Sans"
MONO = "DejaVu Sans Mono"


@dataclass
class Box:
    """A titled box; remembers its geometry so arrows can anchor to edges."""
    x: float
    y: float
    w: float
    h: float

    # edge anchors -----------------------------------------------------
    @property
    def top(self):    return (self.x + self.w / 2, self.y + self.h)
    @property
    def bottom(self): return (self.x + self.w / 2, self.y)
    @property
    def left(self):   return (self.x, self.y + self.h / 2)
    @property
    def right(self):  return (self.x + self.w, self.y + self.h / 2)

    def top_at(self, frac: float):    return (self.x + self.w * frac, self.y + self.h)
    def bottom_at(self, frac: float): return (self.x + self.w * frac, self.y)


def new_canvas(width: float, height: float, title: str, subtitle: str = ""):
    fig, ax = plt.subplots(figsize=(width, height), dpi=100)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")
    ax.text(0.35, height - 0.42, title, fontsize=17, fontweight="bold",
            color=INK, fontfamily=FONT, va="center")
    if subtitle:
        ax.text(0.37, height - 0.78, subtitle, fontsize=10.5,
                color="#64748b", fontfamily=FONT, va="center")
    return fig, ax


def draw_box(ax, x, y, w, h, *, title, lines=(), color, mono_lines=False,
             title_size=11.5, line_size=9.3) -> Box:
    """A rounded box with a colored title band and optional body lines."""
    body = FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.10",
        linewidth=1.4, edgecolor=color, facecolor="white", zorder=2)
    ax.add_patch(body)
    band_h = 0.42
    band = FancyBboxPatch(
        (x, y + h - band_h), w, band_h,
        boxstyle="round,pad=0.02,rounding_size=0.10",
        linewidth=0, facecolor=color, alpha=0.14, zorder=3)
    ax.add_patch(band)
    ax.text(x + w / 2, y + h - band_h / 2, title, ha="center", va="center",
            fontsize=title_size, fontweight="bold", color=color,
            fontfamily=FONT, zorder=4)
    family = MONO if mono_lines else FONT
    n = len(lines)
    if n:
        # distribute body lines evenly in the space under the title band
        space = h - band_h - 0.12
        step = space / n
        for i, line in enumerate(lines):
            ax.text(x + w / 2, y + h - band_h - 0.10 - step * (i + 0.5) + step * 0.0,
                    line, ha="center", va="center", fontsize=line_size,
                    color=INK, fontfamily=family, zorder=4)
    return Box(x, y, w, h)


def draw_note(ax, x, y, text, *, size=8.6, color="#64748b", ha="center"):
    ax.text(x, y, text, ha=ha, va="center", fontsize=size, color=color,
            fontfamily=FONT, style="italic", zorder=4)


def arrow(ax, p1, p2, *, label="", color=INK, style="-|>", lw=1.6,
          curve=0.0, label_dx=0.0, label_dy=0.14, label_size=8.8,
          dashed=False, both=False):
    """Arrow between two anchor points with an optional floating label."""
    if both:
        style = "<|-|>"
    patch = FancyArrowPatch(
        p1, p2, arrowstyle=style, mutation_scale=14, linewidth=lw,
        color=color, zorder=1,
        connectionstyle=f"arc3,rad={curve}",
        linestyle=(0, (5, 4)) if dashed else "solid",
        shrinkA=4, shrinkB=4)
    ax.add_patch(patch)
    if label:
        mx, my = (p1[0] + p2[0]) / 2 + label_dx, (p1[1] + p2[1]) / 2 + label_dy
        ax.text(mx, my, label, ha="center", va="center", fontsize=label_size,
                color=color, fontfamily=FONT, zorder=5,
                bbox=dict(boxstyle="round,pad=0.18", facecolor=BG,
                          edgecolor="none", alpha=0.9))


def save(fig, stem: str) -> list[str]:
    """Write PNG + SVG next to docs (docs/img/) and return the paths."""
    from pathlib import Path
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "img"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("png", "svg"):
        path = out_dir / f"{stem}.{ext}"
        fig.savefig(path, bbox_inches="tight", facecolor=BG,
                    dpi=160 if ext == "png" else None)
        paths.append(str(path))
    plt.close(fig)
    return paths
