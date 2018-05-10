# coding=utf-8
from datetime import timedelta
import pytest

from errbot.backends.test import ShallowConfig
from errbot.bootstrap import CORE_STORAGE, bot_config_defaults
from errbot.specific_plugin_manager import SpecificPluginManager
from errbot.storage.base import StoragePluginBase
from errbot.utils import *
from errbot.storage import StoreMixin

log = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "v1,v2",
    [
        ("2.0.0", "2.0.1"),
        ("2.0.0", "2.1.0"),
        ("2.0.0", "3.0.0"),
        ("2.0.0-alpha", "2.0.0-beta"),
        ("2.0.0-beta", "2.0.0-rc1"),
        ("2.0.0-rc1", "2.0.0-rc2"),
        ("2.0.0-rc2", "2.0.0-rc3"),
        ("2.0.0-rc2", "2.0.0"),
        ("2.0.0-beta", "2.0.1"),
    ],
)
def test_version_check(v1, v2):
    assert version2array(v1) < version2array(v2)


@pytest.mark.parametrize("version", ["1.2.3.4", "1.2", "1.2.-beta", "1.2.3-toto", "1.2.3-rc"])
def test_version_check_negative(version):
    with pytest.raises(ValueError):
        version2array(version)


def test_formattimedelta():
    td = timedelta(0, 60 * 60 + 13 * 60)
    assert "1 hours and 13 minutes" == format_timedelta(td)


def unescape_test():
    assert unescape_xml("&#32;") == " "


def test_storage():
    key = "test"

    __import__("errbot.config-template")
    config = ShallowConfig()
    config.__dict__.update(sys.modules["errbot.config-template"].__dict__)
    bot_config_defaults(config)

    spm = SpecificPluginManager(config, "storage", StoragePluginBase, CORE_STORAGE, None)
    storage_plugin = spm.get_plugin_by_name("Memory")

    persistent_object = StoreMixin()
    persistent_object.open_storage(storage_plugin, "test")
    persistent_object[key] = "à value"
    assert persistent_object[key] == "à value"
    assert key in persistent_object
    del persistent_object[key]
    assert key not in persistent_object
    assert len(persistent_object) == 0


def test_split_string_after_returns_original_string_when_chunksize_equals_string_size():
    str_ = "foobar2000" * 2
    splitter = split_string_after(str_, len(str_))
    split = [chunk for chunk in splitter]
    assert [str_] == split


def test_split_string_after_returns_original_string_when_chunksize_equals_string_size_plus_one():
    str_ = "foobar2000" * 2
    splitter = split_string_after(str_, len(str_) + 1)
    split = [chunk for chunk in splitter]
    assert [str_] == split


def test_split_string_after_returns_two_chunks_when_chunksize_equals_string_size_minus_one():
    str_ = "foobar2000" * 2
    splitter = split_string_after(str_, len(str_) - 1)
    split = [chunk for chunk in splitter]
    assert ["foobar2000foobar200", "0"] == split


def test_split_string_after_returns_two_chunks_when_chunksize_equals_half_length_of_string():
    str_ = "foobar2000" * 2
    splitter = split_string_after(str_, int(len(str_) / 2))
    split = [chunk for chunk in splitter]
    assert ["foobar2000", "foobar2000"] == split
