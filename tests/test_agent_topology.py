import importlib

from health_core.settings import get_settings


def _load_agent():
    from health_agents import agent

    return importlib.reload(agent)


def test_sub_agent_modes_are_explicit():
    agent = _load_agent()
    subs = agent.root_agent.sub_agents
    assert [s.name for s in subs] == ["data_scientist", "domain_expert", "health_coach"]
    for sub in subs:
        assert sub.mode is not None, f"{sub.name} must set mode explicitly"
        assert sub.mode == "single_turn"


def test_agents_use_configured_model(monkeypatch):
    monkeypatch.setenv("CHA_MODEL_DEFAULT", "gemini-test-model")
    get_settings.cache_clear()
    try:
        agent = _load_agent()
        for a in [agent.root_agent, *agent.root_agent.sub_agents]:
            assert a.model == "gemini-test-model", a.name
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        _load_agent()
