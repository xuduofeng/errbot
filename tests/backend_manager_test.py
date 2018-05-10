import unittest

import logging

from errbot.core import ErrBot
from errbot.bootstrap import CORE_BACKENDS
from errbot.specific_plugin_manager import SpecificPluginManager

logging.basicConfig(level=logging.DEBUG)


def test_builtins():
    bpm = SpecificPluginManager({}, "backends", ErrBot, CORE_BACKENDS, extra_search_dirs=())
    backend_plug = bpm.getPluginCandidates()
    names = [plug.name for (_, _, plug) in backend_plug]
    assert "Text" in names
    assert "Test" in names
    assert "Null" in names
