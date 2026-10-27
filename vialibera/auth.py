"""Verify Auth0 access tokens (EU tenant). Active only when AUTH0_DOMAIN is set.

Claims used: sub (user), org_id (company, set by Auth0 Organizations),
and a roles claim under AUTH0_ROLES_CLAIM (default https://vialibera/roles).
"""
import os

import jwt


class AuthError(Exception):
    pass


def enabled():
    return bool(os.environ.get("AUTH0_DOMAIN"))


_jwks = None


def _key_for(token):
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(f"https://{os.environ['AUTH0_DOMAIN']}/.well-known/jwks.json", cache_keys=True)
    return _jwks.get_signing_key_from_jwt(token).key


def verify(authorization, key_for=None):
    """Return {user, org, roles} or raise AuthError. key_for is injectable for tests."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing token")
    token = authorization.split(None, 1)[1].strip()
    try:
        claims = jwt.decode(token, (key_for or _key_for)(token), algorithms=["RS256"],
                            audience=os.environ["AUTH0_AUDIENCE"],
                            issuer=f"https://{os.environ['AUTH0_DOMAIN']}/",
                            options={"require": ["exp", "iss", "aud", "sub"]})
    except Exception as e:
        raise AuthError(type(e).__name__)
    org = claims.get("org_id")
    if not org:
        raise AuthError("no organization")
    roles = claims.get(os.environ.get("AUTH0_ROLES_CLAIM", "https://vialibera/roles"), [])
    return {"user": claims["sub"], "org": org, "roles": roles}
