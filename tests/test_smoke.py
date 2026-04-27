import hakobu


def test_version():
    assert hakobu.__version__ == "0.1.0"


def test_public_api():
    for name in hakobu.__all__:
        assert hasattr(hakobu, name)
