"""首次设置（ADR-0066 第 3 项）：密钥写本机用户目录、工厂地址测试连接。"""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

import llm_gateway
from freecad_addon.core import factory_link, first_run, library_choice


class FakeClient:
    def __init__(self, health=None, auth="enterprise", error=None):
        self.health, self._auth, self.error, self.args = health or {"ok": True}, auth, error, None

    def __call__(self, url, timeout=30, cafile=None):
        self.args = (url, timeout, cafile)
        return self

    def _req(self, path):
        if self.error:
            raise factory_link.FactoryError(self.error)
        assert path == "/api/health"
        return self.health

    def auth(self):
        return self._auth


def test_check_factory_ok_and_failures(tmp_path):
    c = FakeClient()
    ok, msg = first_run.check_factory("https://factory.example.com/", None, client=c)
    assert ok and "企业账号" in msg and c.args[0] == "https://factory.example.com/"
    assert first_run.check_factory("factory.example.com", client=FakeClient())[0] is False
    ok, msg = first_run.check_factory("https://x", str(tmp_path / "none.crt"), client=FakeClient())
    assert not ok and "根证书" in msg
    ok, msg = first_run.check_factory("https://x", client=FakeClient(error="连不上工厂 https://x"))
    assert not ok and "连不上" in msg
    assert first_run.check_factory("https://x", client=FakeClient(health={"ok": False}))[0] is False
    crt = tmp_path / "root.crt"
    crt.write_text("x")
    c = FakeClient(auth="local")
    ok, msg = first_run.check_factory("https://x", str(crt), client=c)
    assert ok and "填名字" in msg and c.args[2] == str(crt)


def test_save_writes_user_files_only(tmp_path):
    s, e = tmp_path / "settings.json", tmp_path / ".env"
    assert first_run.needed(library_choice.read_settings(s))
    done = first_run.save("deepseek", " sk-ds-1 ", "https://factory.example.com/", "", s, e)
    assert len(done) == 2
    assert llm_gateway.parse_env(e.read_text(encoding="utf-8")) == {"DEEPSEEK_API_KEY": "sk-ds-1"}
    if os.name != "nt":
        assert stat.S_IMODE(e.stat().st_mode) == 0o600
    settings = json.loads(s.read_text(encoding="utf-8"))
    assert settings["first_run_done"] is True and settings["factory_url"] == "https://factory.example.com"
    assert not first_run.needed(settings)
    # 再存另一家；空密钥不改原来的
    first_run.save("claude", "sk-ant-2", "", "", s, e)
    first_run.save("deepseek", "", "", "", s, e)
    assert llm_gateway.parse_env(e.read_text(encoding="utf-8")) == {"DEEPSEEK_API_KEY": "sk-ds-1",
                                                                     "ANTHROPIC_API_KEY": "sk-ant-2"}
    assert first_run.key_status({"ANTHROPIC_API_KEY": "x"}) == {"deepseek": False, "claude": True}


def test_gateway_reads_user_env(tmp_path, monkeypatch):
    e = tmp_path / ".env"
    llm_gateway.save_user_env({"DEEPSEEK_API_KEY": "sk-user"}, e)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    llm_gateway.load_dotenv(e)
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-user"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")       # 环境变量优先
    llm_gateway.load_dotenv(e)
    assert os.environ["DEEPSEEK_API_KEY"] == "from-env"
    llm_gateway.save_user_env({"DEEPSEEK_API_KEY": ""}, e)
    assert llm_gateway.parse_env(e.read_text(encoding="utf-8")) == {}


def test_is_standalone(tmp_path):
    assert first_run.is_standalone() is False                # 仓库里运行
    (tmp_path / "BUNDLE.json").write_text("{}")
    assert first_run.is_standalone(tmp_path)


@pytest.mark.freecad
def test_first_run_dialog(tmp_path, monkeypatch):
    import FreeCADGui

    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    FreeCADGui.showMainWindow()
    monkeypatch.setattr(library_choice, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(llm_gateway, "USER_ENV", tmp_path / ".env")
    from freecad_addon.gui.first_run import FirstRunDialog

    dlg = FirstRunDialog()
    dlg.url.setText("not-a-url")
    dlg._test()
    assert dlg.test_result.text().startswith("✗")
    dlg.provider.setCurrentIndex(dlg.provider.findData("claude"))
    dlg.key.setText("sk-ant-test")
    dlg.url.setText("")
    dlg._save()
    assert dlg.key.text() == "" and "ANTHROPIC_API_KEY=sk-ant-test" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert library_choice.read_settings()["first_run_done"] is True
    assert sys.modules["freecad_addon.gui.first_run"]
