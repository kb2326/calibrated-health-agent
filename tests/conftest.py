import sys

import pytest


def pytest_collection_modifyitems(config, items):
    if sys.platform.startswith("linux"):
        return
    skip = pytest.mark.skip(reason="needs Linux resource limits")
    for item in items:
        if "linux_only" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _agent_db_in_tmp(tmp_path, monkeypatch):
    """No test may touch the laptop's real data/agent.db."""
    from health_agents import agent_db
    from health_core.settings import Settings

    monkeypatch.setattr(agent_db, "get_settings",
                        lambda: Settings.model_validate({"data_dir": tmp_path}))
