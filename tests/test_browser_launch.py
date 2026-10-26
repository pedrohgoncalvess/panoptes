from unittest.mock import Mock

import pytest
from panoptes_backend import launch


def test_linux_display_is_ready_before_api_and_closed_afterwards(monkeypatch):
    monkeypatch.setattr(launch.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("BROWSER_MERCADO_LIVRE_HEADLESS", raising=False)
    monkeypatch.setenv("PORT", "8000")
    display = Mock()
    display.stdout.readline.return_value = "42\n"
    popen = Mock(return_value=display)
    monkeypatch.setattr(launch.subprocess, "Popen", popen)

    def run(*args, **kwargs):
        assert launch.os.environ["DISPLAY"] == ":42"
        assert kwargs["port"] == 8000

    monkeypatch.setattr(launch.uvicorn, "run", run)
    # Restore the environment mutation made by the launcher after this test.
    monkeypatch.setenv("DISPLAY", "")
    launch.main()
    assert "-nolisten" in popen.call_args.args[0]
    display.terminate.assert_called_once()
    display.wait.assert_called_once()


def test_existing_display_is_not_replaced(monkeypatch):
    monkeypatch.setattr(launch.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":7")
    popen = Mock()
    monkeypatch.setattr(launch.subprocess, "Popen", popen)
    monkeypatch.setattr(launch.uvicorn, "run", Mock())
    launch.main()
    popen.assert_not_called()


@pytest.mark.parametrize("retail_headless", ["true", "false"])
def test_retail_headed_mode_also_requires_virtual_display(monkeypatch, retail_headless):
    monkeypatch.setattr(launch.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", "")
    monkeypatch.setenv("BROWSER_MERCADO_LIVRE_HEADLESS", "true")
    monkeypatch.setenv("BROWSER_RETAIL_HEADLESS", retail_headless)
    display = Mock()
    display.stdout.readline.return_value = "43\n"
    popen = Mock(return_value=display)
    monkeypatch.setattr(launch.subprocess, "Popen", popen)
    monkeypatch.setattr(launch.uvicorn, "run", Mock())
    launch.main()
    assert popen.called is (retail_headless == "false")
