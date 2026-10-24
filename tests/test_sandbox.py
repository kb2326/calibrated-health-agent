"""The sandbox: model-written code computes over handed-in data and can do nothing else."""
from __future__ import annotations

import pytest
from health_agents import sandbox
from health_agents.sandbox import policy, run

B = {"frames": {"days": [{"x": 1}, {"x": 3}]}}


def test_computes_a_mean():
    r = run("result = float(days.x.mean())", B)
    assert r.ok and r.result == 2.0


def test_numpy_scalars_and_prints_come_back():
    r = run("print('hello')\nresult = {'m': days.x.mean(), 'n': len(days)}", B)
    assert r.ok and r.result == {"m": 2.0, "n": 2} and "hello" in r.stdout


def test_nan_becomes_null():
    r = run("result = float('nan')", B)
    assert r.ok and r.result is None


def test_allowed_import_works():
    r = run("import math\nimport statistics\nresult = statistics.median([1, 2, 3]) + math.floor(0.5)", B)
    assert r.ok and r.result == 2


def test_refuses_socket_import():
    r = run("import socket", B)
    assert not r.ok and "import" in (r.error or "")


def test_refuses_os_import():
    assert not run("import os", B).ok


def test_refuses_dunder_escape():
    assert not run("result = ().__class__.__bases__[0].__subclasses__()", B).ok


def test_refuses_dunder_name():
    assert not run("result = __builtins__", B).ok


def test_refuses_open():
    assert not run("open('x', 'w')", B).ok


def test_refuses_format_attribute_escape():
    assert not run("result = '{0.__class__}'.format(1)", B).ok


def test_audit_hook_blocks_pandas_file_write(tmp_path):
    r = run("days.to_csv('out.csv')", B)
    assert not r.ok


def test_audit_hook_blocks_network_via_pandas():
    r = run("pandas.read_csv('http://127.0.0.1:9/a.csv')", B)
    assert not r.ok


def test_infinite_loop_times_out():
    r = run("while True: pass", B, timeout_s=3)
    assert not r.ok and "timeout" in (r.error or "")


@pytest.mark.linux_only
def test_memory_bomb_is_killed():
    assert not run("x = [0] * (2**31)", B, timeout_s=20).ok


def test_child_env_has_no_credentials(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/secret")
    monkeypatch.setenv("CHA_DB_BUCKET", "b")
    env = sandbox._child_env()
    assert not any(k.startswith(("GOOGLE", "CHA_", "CLOUDSDK")) for k in env)


def test_output_cap():
    assert run("result = 'x' * 50000", B).error == "output too large"


def test_unserialisable_result_is_an_error():
    r = run("result = days", B)
    assert not r.ok and "JSON" in (r.error or "")


def test_runtime_error_is_reported_without_crashing():
    r = run("result = days.nope.mean()", B)
    assert not r.ok and "AttributeError" in (r.error or "")


def test_policy_allows_plain_pandas_code():
    assert policy.check("result = days.groupby('x').size().to_dict()") is None


def test_set_order_is_reproducible_across_runs():
    """Receipts must re-run to the same value: string hashing is seeded in the child."""
    code = "result = list({'Alcohol', 'Late meal', 'High stress', 'Hard training', 'Caffeine'})"
    results = {tuple(run(code, B).result) for _ in range(4)}
    assert len(results) == 1


@pytest.mark.parametrize("code", [
    "result = pd.io.common.os.listdir('.')",
    "import pandas\nresult = pandas.io.common.os.getcwd()",
    "from pandas.io import common\nresult = common.os.getcwd()",
    "result = np.ctypeslib.ctypes.sizeof(1)",
    "g = (x for x in [1])\nresult = len(g.gi_frame.f_globals)",
    "result = days.x.tolist.__self__",
    "days.to_sql('t', 'sqlite:///x.db')",
    "days.x.to_numpy().tofile('x.bin')",
    "result = np.load('x.npy')",
    "result = pd.read_pickle('x.pkl')",
])
def test_escape_routes_are_refused(code):
    r = run(code, B)
    assert not r.ok, (code, r.result)


def test_reflective_exec_through_frames_is_blocked():
    code = ("g = (x for x in [1])\n"
            "b = g.gi_frame.f_builtins\n"
            "b['exec']('result = 42')")
    assert not run(code, B).ok


def test_sqlite_is_blocked_by_the_audit_hook_even_if_reached():
    from health_agents.sandbox import runner
    assert "sqlite3" in runner.DENY_MODULES and "importlib" in runner.DENY_MODULES
    assert any(p.startswith("sqlite3") for p in runner.DENY_PREFIXES)


def test_numpy_submodules_still_work():
    r = run("result = float(np.linalg.norm([3, 4])) + float(np.random.default_rng(1).integers(0, 1))", B)
    assert r.ok and r.result == 5.0
