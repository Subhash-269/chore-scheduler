"""Sign in with Apple / Google: token checks and account linking.

Tokens are signed with a throwaway RSA key standing in for the provider's,
so signature, audience, issuer and expiry are all checked for real.
"""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from server import social
from server.db import DB
from server.main import app

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(social, "_signing_key", lambda token, url: KEY.public_key())
    monkeypatch.setenv("APPLE_AUDIENCES", "com.subhash269.chores")
    monkeypatch.delenv("GOOGLE_CLIENT_IDS", raising=False)
    old = app.state.db
    app.state.db = DB(str(tmp_path))
    try:
        yield TestClient(app)
    finally:
        app.state.db.close()
        app.state.db = old


def token(iss, aud, sub, key=KEY, ttl=600, **claims):
    t = int(time.time())
    return jwt.encode({"iss": iss, "aud": aud, "sub": sub, "iat": t, "exp": t + ttl, **claims}, key, algorithm="RS256")


def apple(sub="apple-001", aud="com.subhash269.chores", **claims):
    return token("https://appleid.apple.com", aud, sub, **claims)


def google(sub="google-001", aud="web-client.apps.googleusercontent.com", **claims):
    return token("https://accounts.google.com", aud, sub, **claims)


def test_apple_creates_then_reuses_the_account(client):
    first = client.post("/auth/apple", json={"identity_token": apple(email="dave@privaterelay.appleid.com", email_verified="true"),
                                             "name": "Dave"}).json()
    assert first["user"]["name"] == "Dave"
    # Apple omits name and email after the first sign-in: same subject -> same account
    again = client.post("/auth/apple", json={"identity_token": apple()}).json()
    assert again["user"]["id"] == first["user"]["id"]
    me = client.get("/me", headers={"Authorization": f"Bearer {again['token']}"})
    assert me.status_code == 200


def test_apple_without_email_still_works(client):
    r = client.post("/auth/apple", json={"identity_token": apple(sub="hidden")})
    assert r.status_code == 200 and r.json()["user"]["name"] == "New roommate"


@pytest.mark.parametrize("bad", [
    lambda: apple(aud="com.someone.else"),                           # token minted for another app
    lambda: apple(ttl=-60),                                          # expired
    lambda: token("https://evil.example", "com.subhash269.chores", "x"),  # wrong issuer
    lambda: apple(key=rsa.generate_private_key(public_exponent=65537, key_size=2048)),  # forged signature
    lambda: "not-a-jwt",
])
def test_bad_apple_tokens_are_rejected(client, bad):
    assert client.post("/auth/apple", json={"identity_token": bad()}).status_code == 401


def test_google_is_off_until_configured(client, monkeypatch):
    assert client.get("/auth/providers").json() == {"email": True, "apple": True, "google": False}
    assert client.post("/auth/google", json={"id_token": google()}).status_code == 503
    monkeypatch.setenv("GOOGLE_CLIENT_IDS", "web-client.apps.googleusercontent.com,ios-client.apps.googleusercontent.com")
    r = client.post("/auth/google", json={"id_token": google(email="dave@gmail.com", email_verified=True, name="Dave")})
    assert r.status_code == 200 and r.json()["user"]["email"] == "dave@gmail.com"
    assert client.post("/auth/google", json={"id_token": google(aud="other-client")}).status_code == 401


def test_password_accounts_are_never_auto_linked(client, monkeypatch):
    """Pre-hijacking guard: a password account registered with someone's email
    must not swallow their later Google sign-in."""
    monkeypatch.setenv("GOOGLE_CLIENT_IDS", "web-client.apps.googleusercontent.com")
    client.post("/auth/signup", json={"email": "victim@gmail.com", "password": "attacker knows", "name": "x"})
    r = client.post("/auth/google", json={"id_token": google(email="victim@gmail.com", email_verified=True)})
    assert r.status_code == 409


def test_same_verified_email_links_apple_and_google(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_IDS", "web-client.apps.googleusercontent.com")
    a = client.post("/auth/apple", json={"identity_token": apple(email="dave@gmail.com", email_verified="true"), "name": "Dave"}).json()
    g = client.post("/auth/google", json={"id_token": google(email="dave@gmail.com", email_verified=True)}).json()
    assert g["user"]["id"] == a["user"]["id"]


def test_provider_only_accounts_have_no_password(client):
    client.post("/auth/apple", json={"identity_token": apple(email="dave@icloud.com", email_verified="true")})
    for guess in ["!", "", "password"]:
        assert client.post("/auth/login", json={"email": "dave@icloud.com", "password": guess}).status_code == 401
