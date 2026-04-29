import pytest

from hakobu import keys
from hakobu.errors import VerificationError


def test_sign_verify_round_trip(signing_key):
    public = keys.public_from_text(keys.public_text(signing_key))
    signature = keys.sign(signing_key, b"payload")
    keys.verify(public, b"payload", signature)


def test_tampered_data_fails(signing_key):
    public = keys.public_from_text(keys.public_text(signing_key))
    signature = keys.sign(signing_key, b"payload")
    with pytest.raises(VerificationError):
        keys.verify(public, b"payl0ad", signature)


def test_wrong_key_fails(signing_key):
    other = keys.generate()
    public = keys.public_from_text(keys.public_text(other))
    signature = keys.sign(signing_key, b"payload")
    with pytest.raises(VerificationError):
        keys.verify(public, b"payload", signature)


def test_garbage_signature_fails(signing_key):
    public = keys.public_from_text(keys.public_text(signing_key))
    with pytest.raises(VerificationError):
        keys.verify(public, b"payload", "そもそもbase64でない")


def test_garbage_public_key_fails():
    with pytest.raises(VerificationError):
        keys.public_from_text("not-a-key")


def test_private_key_file_round_trip(tmp_path, signing_key):
    path = tmp_path / "signing.key"
    keys.save_private(signing_key, path)
    assert path.stat().st_mode & 0o777 == 0o600
    loaded = keys.load_private(path)
    assert keys.public_text(loaded) == keys.public_text(signing_key)


def test_fingerprint_is_stable_and_key_specific(signing_key):
    public = signing_key.public_key()
    fp = keys.fingerprint(public)
    assert keys.fingerprint(public) == fp
    assert fp.count(":") == 3
    assert keys.fingerprint(keys.generate().public_key()) != fp


def test_fingerprint_survives_text_round_trip(signing_key):
    restored = keys.public_from_text(keys.public_text(signing_key))
    assert keys.fingerprint(restored) == keys.fingerprint(signing_key.public_key())
