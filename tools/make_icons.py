"""PWA 아이콘 생성: python tools/make_icons.py  ->  public/icons/*.png
원자 궤도 모티프(한수원 로고 아님)를 파랑 그라데이션 위에 그린다.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
OUT.mkdir(parents=True, exist_ok=True)
SS = 4  # 안티앨리어싱용 확대 배율


def gradient(size):
    """대각선 남색 -> 파랑 -> 하늘색 그라데이션."""
    stops = [(0.0, (6, 48, 95)), (0.55, (10, 94, 176)), (1.0, (26, 163, 232))]
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
                if t <= t1:
                    k = (t - t0) / (t1 - t0)
                    px[x, y] = tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))
                    break
    return img


def atom(size, scale):
    """size x size 투명 레이어에 원자 궤도 3개와 핵을 그린다. scale: 그림이 차지하는 비율."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rx, ry = size * scale * 0.5, size * scale * 0.19
    lw = max(2, round(size * 0.028))
    cx = cy = size / 2
    for ang in (0, 60, 120):
        tmp = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=(255, 255, 255, 235), width=lw)
        layer = Image.alpha_composite(layer, tmp.rotate(ang, resample=Image.BICUBIC, center=(cx, cy)))
    d = ImageDraw.Draw(layer)
    r = size * 0.075
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
    # 궤도 위의 전자 점
    for ang, frac in ((20, 0.0), (140, 0.0), (260, 0.0)):
        import math
        a = math.radians(ang)
        ex, ey = cx + rx * math.cos(a), cy + ry * math.sin(a)
        # 궤도 0도 타원 위의 점을 같은 각도로 회전
        rot = math.radians(ang * 0 + 60 * (ang // 140))
        x = cx + (ex - cx) * math.cos(rot) - (ey - cy) * math.sin(rot)
        y = cy + (ex - cx) * math.sin(rot) + (ey - cy) * math.cos(rot)
        rr = size * 0.036
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(143, 211, 255, 255))
    return layer


def make(size, scale, name, rounded=True):
    big = size * SS
    img = gradient(big).convert("RGBA")
    img = Image.alpha_composite(img, atom(big, scale))
    if rounded:  # 둥근 모서리(일반 아이콘). maskable 은 OS 가 직접 자르므로 꽉 채운다.
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 0.22), fill=255)
        img.putalpha(mask)
    img = img.resize((size, size), Image.LANCZOS)
    img.save(OUT / name, optimize=True)
    print(name, size)


make(512, 0.80, "icon-512.png")
make(192, 0.80, "icon-192.png")
make(512, 0.62, "maskable-512.png", rounded=False)   # 안전 영역(중앙 80%) 안에 그림을 둔다
make(180, 0.78, "apple-touch-icon.png", rounded=False)  # iOS 가 직접 둥글게 자른다
make(64, 0.84, "favicon-64.png")
