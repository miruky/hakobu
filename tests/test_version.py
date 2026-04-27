import pytest

from hakobu.errors import ConfigError
from hakobu.version import is_newer, latest, parse


class TestParse:
    def test_triple(self):
        assert parse("1.2.3") == (1, 2, 3)

    def test_single(self):
        assert parse("7") == (7,)

    @pytest.mark.parametrize("text", ["", "v1.0", "1.0-beta", "1..0", "1.0."])
    def test_invalid(self, text):
        with pytest.raises(ConfigError):
            parse(text)


class TestIsNewer:
    def test_patch_bump(self):
        assert is_newer("1.0.1", "1.0.0")

    def test_equal_is_not_newer(self):
        assert not is_newer("1.0.0", "1.0.0")

    def test_older(self):
        assert not is_newer("1.0.0", "1.0.1")

    def test_different_lengths(self):
        assert is_newer("1.0.1", "1.0")
        assert not is_newer("1.0", "1.0.0")

    def test_numeric_not_lexicographic(self):
        assert is_newer("1.10.0", "1.9.0")


class TestLatest:
    def test_picks_newest(self):
        assert latest(["1.0.0", "1.10.0", "1.2.0"]) == "1.10.0"

    def test_empty_raises(self):
        with pytest.raises(ConfigError):
            latest([])
