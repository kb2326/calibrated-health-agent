import pytest
from health_eval import stats


def test_wilson_known_values():
    lo, hi = stats.wilson(34, 40)
    assert (round(lo, 3), round(hi, 3)) == (0.709, 0.929)
    lo, hi = stats.wilson(40, 40)
    assert hi == pytest.approx(1.0) and 0.9 < lo < 1.0


def test_wilson_n0():
    assert stats.wilson(0, 0) == (0.0, 1.0)


def test_mcnemar_exact_symmetric_and_known():
    assert stats.mcnemar_exact(0, 6) == pytest.approx(0.03125)
    assert stats.mcnemar_exact(6, 0) == stats.mcnemar_exact(0, 6)
    assert stats.mcnemar_exact(3, 3) == pytest.approx(1.0)
    assert stats.mcnemar_exact(0, 0) == 1.0
    assert stats.mcnemar_exact(2, 9) == pytest.approx(0.06543, abs=1e-5)


def test_bootstrap_seeded():
    a = [True] * 30 + [False] * 10
    b = [True] * 22 + [False] * 18
    first = stats.paired_bootstrap_diff(a, b)
    assert first == stats.paired_bootstrap_diff(a, b)
    point, lo, hi = first
    assert point == pytest.approx(0.2) and lo < point < hi and lo > 0
    assert stats.paired_bootstrap_diff(a, a) == (0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        stats.paired_bootstrap_diff(a, b[:-1])


def test_pass_hat_k():
    trials = [[True, True, True], [True, False, True], [True, True, True], [False] * 3]
    assert stats.pass_hat_k(trials) == 0.5
    assert stats.pass_hat_k([]) == 0.0


def test_mdd_shrinks_with_n():
    small, big = stats.min_detectable_diff(30), stats.min_detectable_diff(300)
    assert big < small < 1
    assert stats.min_detectable_diff(100) == pytest.approx(0.1585, abs=1e-3)
