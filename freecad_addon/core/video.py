"""录制时可选的视频（ADR-0042，issue #147）：用 ffmpeg 只录 FreeCAD 主窗口所在区域。只用标准库。

- Linux（X11）：x11grab；Windows：gdigrab。macOS 与 Wayland 暂不支持，说明原因后照常录制其他内容
- ffmpeg 路径：环境变量 FAP_FFMPEG，否则在 PATH 中查找
- 停止时向 ffmpeg 发送 q，让它正常收尾写完文件；超时再强制结束
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

FRAMERATE = 10


class VideoUnavailable(RuntimeError):
    """录不了视频；消息说明原因。"""


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    width: int
    height: int

    def even(self) -> Region:
        """H.264（yuv420p）要求宽高为偶数。"""
        w, h = self.width - self.width % 2, self.height - self.height % 2
        if w < 16 or h < 16:
            raise VideoUnavailable(f"窗口太小（{self.width}×{self.height}）")
        return Region(max(0, self.x), max(0, self.y), w, h)


def find_ffmpeg(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    path = env.get("FAP_FFMPEG") or shutil.which("ffmpeg")
    if not path:
        raise VideoUnavailable("没有找到 ffmpeg：请安装 ffmpeg，或用环境变量 FAP_FFMPEG 指定路径")
    return path


def command(ffmpeg: str, region: Region, out: Path, *, platform: str | None = None,
            env: Mapping[str, str] | None = None) -> list[str]:
    """组装 ffmpeg 命令（纯函数）。"""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    r = region.even()
    if platform.startswith("linux"):
        if env.get("WAYLAND_DISPLAY") and not env.get("DISPLAY"):
            raise VideoUnavailable("Wayland 下 ffmpeg 不能直接录屏，暂不支持视频")
        display = env.get("DISPLAY")
        if not display:
            raise VideoUnavailable("没有显示环境（DISPLAY），录不了视频")
        source = ["-f", "x11grab", "-video_size", f"{r.width}x{r.height}", "-framerate", str(FRAMERATE),
                  "-i", f"{display}+{r.x},{r.y}"]
    elif platform.startswith("win"):
        source = ["-f", "gdigrab", "-framerate", str(FRAMERATE), "-offset_x", str(r.x), "-offset_y", str(r.y),
                  "-video_size", f"{r.width}x{r.height}", "-i", "desktop"]
    else:
        raise VideoUnavailable(f"{platform} 上暂不支持录视频（只支持 Linux X11 与 Windows）")
    return [ffmpeg, "-loglevel", "error", "-y", *source, "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", str(out)]


class VideoRecorder:
    def __init__(self, cmd: list[str], out: Path):
        self.cmd, self.out = cmd, Path(out)
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE)

    def stop(self, timeout_s: float = 15.0) -> tuple[bool, str]:
        """结束录制；返回（视频文件是否生成, 出错信息）。"""
        if self.proc is None:
            return False, "未开始"
        err = ""
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.write(b"q")
                    self.proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
            _, stderr = self.proc.communicate(timeout=timeout_s)
            err = (stderr or b"").decode("utf-8", "replace").strip()
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.communicate()
            err = "ffmpeg 没有按时结束，已强制停止"
        ok = self.out.is_file() and self.out.stat().st_size > 0
        return ok, err[-500:]
