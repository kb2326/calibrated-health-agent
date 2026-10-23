import sys

import pytest


def pytest_collection_modifyitems(config, items):
    if sys.platform.startswith("linux"):
        return
    skip = pytest.mark.skip(reason="needs Linux resource limits")
    for item in items:
        if "linux_only" in item.keywords:
            item.add_marker(skip)
