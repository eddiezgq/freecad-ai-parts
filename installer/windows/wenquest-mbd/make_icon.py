"""问渠多体动力学的图标（ADR-0102 第 4 步）：深绿底上一个白色的曲柄滑块机构，铰点是橙色。生成 wenquest-mbd.ico（16–256 像素）。

    python installer/windows/wenquest-mbd/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
BG, FG, HOT = (16, 78, 72), (240, 248, 246), (255, 170, 60)


def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((32, 32, S - 32, S - 32), radius=180, fill=BG)
    o, a, b = (300, 600), (420, 360), (760, 600)          # 曲柄转心、曲柄销、滑块销
    w = 48
    d.line((*o, *a), fill=FG, width=w)                     # 曲柄
    d.line((*a, *b), fill=FG, width=w)                     # 连杆
    d.rounded_rectangle((b[0] - 110, b[1] - 75, b[0] + 110, b[1] + 75), radius=24, outline=FG, width=36)   # 滑块
    d.line((170, b[1] + 120, 900, b[1] + 120), fill=FG, width=20)                                       # 导轨
    for p in (o, a, b):
        d.ellipse((p[0] - 52, p[1] - 52, p[0] + 52, p[1] + 52), fill=HOT)
    return im


if __name__ == "__main__":
    out = Path(__file__).with_name("wenquest-mbd.ico")
    draw().save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)
