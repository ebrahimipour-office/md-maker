import pytest


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path_factory, monkeypatch):
    """Ignore the developer's own settings and never call a real model,
    unless a test opts in."""
    home = tmp_path_factory.mktemp("home")
    for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(home / var.lower()))
    monkeypatch.delenv("MD_MAKER_CONFIG", raising=False)
    monkeypatch.setenv("MD_MAKER_AI", "off")
