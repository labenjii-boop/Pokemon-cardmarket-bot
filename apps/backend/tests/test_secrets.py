"""This sandbox has no OS keyring backend (no macOS Keychain, no Linux Secret Service daemon),
so get_secret/set_secret exercise the graceful-fallback path here rather than a real backend —
that fallback (log + return None/False instead of crashing) is exactly the behavior worth
locking in, since it's what keeps the app usable in dev/CI and on a machine with no keyring
configured. Real Keychain read/write on macOS itself isn't something this test suite can verify.
"""
from app.secrets import delete_secret, get_secret, set_secret


def test_get_secret_returns_none_without_a_backend():
    assert get_secret("does-not-exist") is None


def test_set_secret_does_not_raise_without_a_backend():
    assert set_secret("some-key", "some-value") is False


def test_delete_secret_does_not_raise_without_a_backend():
    delete_secret("does-not-exist")  # must not raise
