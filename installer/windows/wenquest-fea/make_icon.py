"""问渠有限元的图标（ADR-0096 第 5 步）：深蓝底上一块白色的三角形网格。生成 wenquest-fea.ico（16–256 像素）。

    python installer/windows/wenquest-fea/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
BG, FG, HOT = (18, 52, 96), (240, 246, 252), (255, 170, 60)


def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((32, 32, S - 32, S - 32), radius=180, fill=BG)
    # 一块梁的三角形网格：左端固定，右端变红（应力集中的意思）
    x0, x1, y0, y1, n = 190, 834, 330, 694, 4
    xs = [x0 + (x1 - x0) * i / n for i in range(n + 1)]
    w = 22
    d.rectangle((x0, y0, x1, y1), outline=FG, width=w)
    for i in range(n):
        d.line((xs[i], y1, xs[i + 1], y0), fill=FG, width=w)
        if i:
            d.line((xs[i], y0, xs[i], y1), fill=FG, width=w)
    d.ellipse((x1 - 70, y0 - 70, x1 + 70, y0 + 70), fill=HOT)
    for k in range(5):                       # 固定端的斜线
        y = y0 + (y1 - y0) * (k + 0.5) / 5
        d.line((x0 - 90, y + 50, x0 - 20, y - 20), fill=FG, width=16)
    return im


if __name__ == "__main__":
    out = Path(__file__).with_name("wenquest-fea.ico")
    draw().save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)
