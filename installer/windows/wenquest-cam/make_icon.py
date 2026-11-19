"""问渠CAM 的图标（ADR-0104 产品化）：深蓝底上一把白色立铣刀，刀下一条橙色刀路。生成 wenquest-cam.ico（16–256 像素）。

    python installer/windows/wenquest-cam/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
BG, FG, HOT = (22, 52, 96), (240, 246, 252), (255, 160, 50)


def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((32, 32, S - 32, S - 32), radius=180, fill=BG)
    d.rounded_rectangle((400, 130, 624, 300), radius=30, fill=FG)            # 刀柄
    d.rectangle((450, 300, 574, 640), fill=FG)                                 # 刀杆与刃部
    for y in range(330, 640, 90):                                              # 螺旋刃
        d.line((450, y + 60, 574, y), fill=BG, width=26)
    pts = [(170, 820), (330, 820), (420, 700), (604, 700), (694, 820), (860, 820)]
    d.line(pts, fill=HOT, width=46, joint="curve")                             # 刀路
    return im


if __name__ == "__main__":
    out = Path(__file__).with_name("wenquest-cam.ico")
    draw().save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)
