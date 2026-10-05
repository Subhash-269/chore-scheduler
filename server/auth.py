"""
auth.py - email + password accounts with bearer tokens. Standard library only.

Passwords: PBKDF2-HMAC-SHA256, per-user salt. Tokens: random, stored only as
a SHA-256 hash, so a leaked database doesn't leak working sessions.
"""
import base64
import hashlib
import hmac
import secrets

ITERATIONS = 240_000


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password, stored):
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iterations))
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def new_token():
    """Returns (token for the client, hash to store)."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def invite_code():
    """6 characters, no look-alikes (0/O, 1/I/L), shown as K7Q-2XM."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))
