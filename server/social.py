"""
social.py - verify Sign in with Apple / Google identity tokens.

Both hand the app a JWT signed by the provider. We check the signature
against the provider's published keys (JWKS), the issuer, the audience
(our app), and expiry. Only then do we trust the subject / email in it.

Audiences come from the environment so the same code serves dev and store builds:
    APPLE_AUDIENCES    comma-separated; default: the app's bundle ID and Expo Go's
    GOOGLE_CLIENT_IDS  comma-separated OAuth client IDs (web + iOS + Android);
                       Google sign-in is off until this is set
"""
import os

import jwt

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS = "https://appleid.apple.com/auth/keys"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"

# bundle ID from app/app.json; host.exp.Exponent is what Expo Go signs in as
DEFAULT_APPLE_AUDIENCES = "com.subhash269.chores,host.exp.Exponent"

_jwks_clients = {}


class SocialAuthError(ValueError):
    pass


def _audiences(var, default=""):
    return [a.strip() for a in os.environ.get(var, default).split(",") if a.strip()]


def google_enabled():
    return bool(_audiences("GOOGLE_CLIENT_IDS"))


def _signing_key(token, jwks_url):
    """The provider key that signed this token (JWKS fetched and cached by PyJWT)."""
    client = _jwks_clients.get(jwks_url)
    if client is None:
        client = _jwks_clients[jwks_url] = jwt.PyJWKClient(jwks_url, cache_keys=True)
    return client.get_signing_key_from_jwt(token).key


def _decode(token, jwks_url, audiences, issuers):
    if not audiences:
        raise SocialAuthError("This sign-in method isn't configured on the server")
    try:
        key = _signing_key(token, jwks_url)
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=audiences,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except jwt.PyJWKClientError as e:
        raise SocialAuthError(f"Couldn't check the sign-in with the provider: {e}") from None
    except jwt.InvalidTokenError as e:
        raise SocialAuthError(f"Sign-in token rejected: {e}") from None
    if claims.get("iss") not in issuers:
        raise SocialAuthError("Sign-in token came from the wrong issuer")
    return claims


def _verified(value):
    # Apple sends "true"/"false" strings, Google sends booleans
    return value is True or value == "true"


def verify_apple(identity_token):
    """-> (subject, email or None, email_verified)"""
    c = _decode(identity_token, APPLE_JWKS, _audiences("APPLE_AUDIENCES", DEFAULT_APPLE_AUDIENCES), (APPLE_ISSUER,))
    return c["sub"], c.get("email"), _verified(c.get("email_verified"))


def verify_google(id_token):
    """-> (subject, email or None, email_verified, name or None)"""
    c = _decode(id_token, GOOGLE_JWKS, _audiences("GOOGLE_CLIENT_IDS"), GOOGLE_ISSUERS)
    return c["sub"], c.get("email"), _verified(c.get("email_verified")), c.get("name")
