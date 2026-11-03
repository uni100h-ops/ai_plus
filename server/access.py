"""Password gate with expiring signed cookies; no credentials in browser storage."""
import hashlib
import hmac
import os
import secrets
import time

COOKIE = 'mq_access'
TTL = 12 * 3600


def password():
    return os.getenv('APP_PASSWORD', '')


def require_configuration():
    if not 12 <= len(password()) <= 256:
        raise RuntimeError('Set APP_PASSWORD on Render to a password of 12 to 256 characters.')


def matches(candidate):
    return bool(password()) and hmac.compare_digest(candidate.encode(), password().encode())


def signature(payload, session_key):
    key = hashlib.sha256((session_key + '\0' + password()).encode()).digest()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def issue(session_key):
    payload = str(int(time.time()) + TTL) + '.' + secrets.token_hex(16)
    return payload + '.' + signature(payload, session_key)


def valid(token, session_key):
    if not password() or not isinstance(token, str) or len(token) > 150:
        return False
    try:
        expiry, nonce, sig = token.split('.')
        now = int(time.time())
        if not now < int(expiry) <= now + TTL or len(nonce) != 32:
            return False
        expected = signature(expiry + '.' + nonce, session_key)
        return hmac.compare_digest(expected.encode(), sig.encode())
    except (TypeError, ValueError):
        return False
