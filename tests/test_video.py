"""录制时的可选视频（ADR-0042，issue #147）：ffmpeg 命令组装、启动与正常收尾。用假 ffmpeg，不录真实屏幕。"""

from __future__ import annotations

import os
import stat
import sys
import textwrap

import pytest

from freecad_addon.core.video import Region, VideoRecorder, VideoUnavailable, command, find_ffmpeg

FAKE = textwrap.dedent("""\
    #!{python}
    import sys, time
    out = sys.argv[-1]
    if "--hang" in sys.argv:
        time.sleep(60)
    sys.stdin.read(1)  # 等 q
    open(out, "wb").write(b"fake-mp4")
""")


def _fake_ffmpeg(tmp_path, name="ffmpeg"):
    path = tmp_path / name
    path.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_linux_command_uses_window_region(tmp_path):
    cmd = command("ffmpeg", Region(10, 20, 1281, 801), tmp_path / "v.mp4", platform="linux", env={"DISPLAY": ":1"})
    assert cmd[cmd.index("-f") + 1] == "x11grab" and cmd[cmd.index("-video_size") + 1] == "1280x800"
    assert cmd[cmd.index("-i") + 1] == ":1+10,20" and cmd[-1].endswith("v.mp4")


def test_windows_command(tmp_path):
    cmd = command("ffmpeg.exe", Region(-8, 0, 1920, 1040), tmp_path / "v.mp4", platform="win32", env={})
    assert cmd[cmd.index("-f") + 1] == "gdigrab" and cmd[cmd.index("-offset_x") + 1] == "0"
    assert cmd[cmd.index("-i") + 1] == "desktop"


@pytest.mark.parametrize(("platform", "env", "region", "msg"), [
    ("darwin", {}, Region(0, 0, 800, 600), "暂不支持"),
    ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, Region(0, 0, 800, 600), "Wayland"),
    ("linux", {}, Region(0, 0, 800, 600), "DISPLAY"),
    ("linux", {"DISPLAY": ":0"}, Region(0, 0, 10, 600), "太小"),
])
def test_unsupported(tmp_path, platform, env, region, msg):
    with pytest.raises(VideoUnavailable, match=msg):
        command("ffmpeg", region, tmp_path / "v.mp4", platform=platform, env=env)


def test_find_ffmpeg(tmp_path, monkeypatch):
    assert find_ffmpeg({"FAP_FFMPEG": "/opt/ffmpeg"}) == "/opt/ffmpeg"
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(VideoUnavailable, match="ffmpeg"):
        find_ffmpeg({})


@pytest.mark.skipif(os.name == "nt", reason="假 ffmpeg 是 shebang 脚本")
def test_recorder_stops_gracefully(tmp_path):
    out = tmp_path / "v.mp4"
    rec = VideoRecorder([str(_fake_ffmpeg(tmp_path)), str(out)], out)
    rec.start()
    assert rec.stop() == (True, "")
    assert out.read_bytes() == b"fake-mp4"


@pytest.mark.skipif(os.name == "nt", reason="假 ffmpeg 是 shebang 脚本")
def test_recorder_kills_hung_ffmpeg(tmp_path):
    out = tmp_path / "v.mp4"
    rec = VideoRecorder([str(_fake_ffmpeg(tmp_path)), "--hang", str(out)], out)
    rec.start()
    ok, err = rec.stop(timeout_s=0.5)
    assert not ok and "强制" in err
    assert VideoRecorder(["x"], out).stop() == (False, "未开始")
