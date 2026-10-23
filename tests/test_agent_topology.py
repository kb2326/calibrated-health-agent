import importlib

from health_core.settings import get_settings


def _load_agent():
    from health_agents import agent

    return importlib.reload(agent)


def test_root_agent_is_the_configured_workflow():
    assert _load_agent().root_agent.name == f"health_agent_{get_settings().topology}"


def test_agents_use_configured_model(monkeypatch):
    from health_agents import workflow

    monkeypatch.setenv("CHA_MODEL_DEFAULT", "gemini-test-model")
    get_settings.cache_clear()
    try:
        for agent in workflow.specialists(get_settings().model_default).values():
            assert agent.model == "gemini-test-model", agent.name
        assert _load_agent().MODEL == "gemini-test-model"
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        _load_agent()
