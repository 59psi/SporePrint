#!/usr/bin/env python3
"""Check that every label in an SVG diagram fits inside its box.

    python3 scripts/wiring_svg/fit_check.py docs/*.svg

Renders each SVG in headless Chrome and measures every <text> element's real
rendered bounds. A text is reported when it sticks out of the smallest <rect>
that contains its centre (by more than 1 px) or out of the canvas, and every
pair of texts whose bounds overlap is reported too. Prints one JSON object
per file and exits 1 if any file has a problem.

Chrome is found at SPOREPRINT_CHROME, the macOS app path, or google-chrome /
chromium / chromium-browser on PATH. server/tests/test_svg_text_fit.py runs
this over docs/*.svg and skips when no Chrome is installed.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

_MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

_MEASURE_JS = r"""
(() => {
  const svg = document.querySelector('svg');
  const vb = svg.viewBox.baseVal;
  const W = vb && vb.width ? vb.width : svg.width.baseVal.value;
  const H = vb && vb.height ? vb.height : svg.height.baseVal.value;
  const bounds = (el) => {
    const b = el.getBBox(), m = el.getCTM();
    const pts = [[b.x, b.y], [b.x + b.width, b.y], [b.x, b.y + b.height], [b.x + b.width, b.y + b.height]]
      .map(([x, y]) => { const p = svg.createSVGPoint(); p.x = x; p.y = y; return p.matrixTransform(m); });
    const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
    return {x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys)};
  };
  // Full-canvas background rects own nothing.
  const rects = [...svg.querySelectorAll('rect')].map(r => bounds(r))
    .filter(b => (b.x1 - b.x0) < W * 0.98 || (b.y1 - b.y0) < H * 0.98);
  const texts = [...svg.querySelectorAll('text')].filter(t => t.textContent.trim())
    .map(t => ({b: bounds(t), s: t.textContent.trim().slice(0, 80)}));
  const overflow = [], overlaps = [];
  for (const t of texts) {
    if (t.b.x0 < -0.5 || t.b.y0 < -0.5 || t.b.x1 > W + 0.5 || t.b.y1 > H + 0.5) {
      overflow.push({text: t.s, where: 'canvas'});
      continue;
    }
    const cx = (t.b.x0 + t.b.x1) / 2, cy = (t.b.y0 + t.b.y1) / 2;
    const owners = rects.filter(o => cx >= o.x0 && cx <= o.x1 && cy >= o.y0 && cy <= o.y1)
      .sort((a, c) => (a.x1 - a.x0) * (a.y1 - a.y0) - (c.x1 - c.x0) * (c.y1 - c.y0));
    if (!owners.length) continue;
    const o = owners[0];
    const out = {left: o.x0 - t.b.x0, right: t.b.x1 - o.x1, top: o.y0 - t.b.y0, bottom: t.b.y1 - o.y1};
    const bad = Object.entries(out).filter(([, v]) => v > 1).map(([k, v]) => `${k} ${v.toFixed(1)}px`);
    if (bad.length) overflow.push({text: t.s, where: 'box', by: bad.join(', '),
      box: [Math.round(o.x0), Math.round(o.y0), Math.round(o.x1 - o.x0), Math.round(o.y1 - o.y0)]});
  }
  for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
    const a = texts[i].b, c = texts[j].b;
    const ix = Math.min(a.x1, c.x1) - Math.max(a.x0, c.x0), iy = Math.min(a.y1, c.y1) - Math.max(a.y0, c.y0);
    if (ix > 1.5 && iy > 1.5) overlaps.push({a: texts[i].s, b: texts[j].s});
  }
  document.getElementById('out').textContent = JSON.stringify({texts: texts.length, overflow, overlaps});
})();
"""


def find_chrome() -> str | None:
    env = os.environ.get("SPOREPRINT_CHROME")
    if env and Path(env).exists():
        return env
    if Path(_MAC_CHROME).exists():
        return _MAC_CHROME
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def check(path: Path, chrome: str) -> dict:
    svg = re.sub(r"^<\?xml[^>]*>", "", path.read_text()).strip()
    page = (f"<!doctype html><html><body style='margin:0'>{svg}<pre id='out'></pre>"
            f"<script>{_MEASURE_JS}</script></body></html>")
    # No custom --user-data-dir: a fresh profile can stall headless Chrome on
    # macOS. --no-sandbox only where CI runners need it (Linux containers).
    args = [chrome, "--headless=new", "--disable-gpu", "--virtual-time-budget=3000"]
    if sys.platform.startswith("linux"):
        args.append("--no-sandbox")
    with tempfile.TemporaryDirectory() as tmp:
        page_path = Path(tmp) / "page.html"
        page_path.write_text(page)
        # Own process group, so a timeout also kills Chrome's helpers — they
        # inherit stdout and would otherwise keep the pipe (and us) waiting.
        proc = subprocess.Popen([*args, "--dump-dom", page_path.as_uri()],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
        try:
            stdout, stderr = proc.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise RuntimeError(f"{path.name}: headless Chrome timed out")
    m = re.search(r'<pre id="out">(.*?)</pre>', stdout, re.S)
    if not m or not m.group(1).strip():
        raise RuntimeError(f"{path.name}: Chrome produced no measurement ({stderr[-300:]})")
    data = json.loads(html.unescape(m.group(1)))
    data["file"] = path.name
    return data


if __name__ == "__main__":
    chrome = find_chrome()
    if not chrome:
        sys.exit("no Chrome / Chromium found (set SPOREPRINT_CHROME)")
    failed = False
    for arg in sys.argv[1:]:
        result = check(Path(arg), chrome)
        failed |= bool(result["overflow"] or result["overlaps"])
        print(json.dumps(result))
    sys.exit(1 if failed else 0)
