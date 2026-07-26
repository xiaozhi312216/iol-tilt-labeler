#!/usr/bin/env python3
"""生成 macOS .icns 与 Windows .ico 图标。

图形语义：镜片圆 + 两条成夹角的线（IOL 轴与 A-B 参考线），
与软件里左上角的品牌标记同一套造型。

跑法：.venv/bin/python tools/make_icons.py
"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT_MAC = ROOT / "resources" / "macos"
OUT_WIN = ROOT / "resources" / "windows"

SS = 4                      # 超采样倍数
BASE = 1024
TOP = (63, 138, 250)        # #3f8afa
BOTTOM = (19, 68, 200)      # #1344c8


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=255)
    return mask


def gradient(size: int) -> Image.Image:
    """左上到右下的线性渐变。"""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = (round(TOP[0] + (BOTTOM[0] - TOP[0]) * t),
                        round(TOP[1] + (BOTTOM[1] - TOP[1]) * t),
                        round(TOP[2] + (BOTTOM[2] - TOP[2]) * t))
    return img


def line_at(cx: float, cy: float, length: float, deg: float):
    rad = math.radians(deg)
    dx, dy = math.cos(rad) * length / 2, math.sin(rad) * length / 2
    return (cx - dx, cy - dy, cx + dx, cy + dy)


def lens_mask(s: int, tilt_deg: float) -> Image.Image:
    """双凸晶体剖面：两个圆的交集，再整体旋转出倾斜角。"""
    pad = int(s * 0.5)
    big = s + pad * 2
    r = s * 0.495
    off = s * 0.40
    c = big / 2
    a = Image.new("L", (big, big), 0)
    ImageDraw.Draw(a).ellipse((c - r, c - off - r, c + r, c - off + r), fill=255)
    b = Image.new("L", (big, big), 0)
    ImageDraw.Draw(b).ellipse((c - r, c + off - r, c + r, c + off + r), fill=255)
    lens = ImageChops.darker(a, b)
    lens = lens.rotate(-tilt_deg, resample=Image.BICUBIC, center=(c, c))
    return lens.crop((pad, pad, pad + s, pad + s))


def render(size: int) -> Image.Image:
    s = size * SS
    base = gradient(s)
    base.putalpha(rounded_mask(s, int(s * 0.2237)))

    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = s / 2
    # A-B 参考线：水平，半透明
    d.line(line_at(c, c, s * 0.84, 0), fill=(255, 255, 255, 170),
           width=max(1, int(s * 0.045)))
    layer_lens = Image.new("RGBA", (s, s), (255, 255, 255, 0))
    layer_lens.putalpha(lens_mask(s, 17))
    layer = Image.alpha_composite(layer, layer_lens)

    base = Image.alpha_composite(base.convert("RGBA"), layer)
    return base.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT_MAC.mkdir(parents=True, exist_ok=True)
    OUT_WIN.mkdir(parents=True, exist_ok=True)

    master = render(BASE)
    (ROOT / "resources").mkdir(exist_ok=True)
    master.save(ROOT / "resources" / "icon_1024.png")

    # Windows .ico
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    master.save(OUT_WIN / "IOLTiltLabeler.ico", format="ICO",
                sizes=[(n, n) for n in ico_sizes])
    print("已生成", OUT_WIN / "IOLTiltLabeler.ico")

    # macOS .icns
    if sys.platform != "darwin":
        print("非 macOS，跳过 .icns")
        return 0
    iconset = OUT_MAC / "IOLTiltLabeler.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    for n in (16, 32, 128, 256, 512):
        render(n).save(iconset / f"icon_{n}x{n}.png")
        render(n * 2).save(iconset / f"icon_{n}x{n}@2x.png")
    icns = OUT_MAC / "IOLTiltLabeler.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
    shutil.rmtree(iconset)
    print("已生成", icns)
    return 0


if __name__ == "__main__":
    sys.exit(main())
