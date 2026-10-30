"""SPESEMED - Test decoder JWT con supporto HS256 (legacy) + ES256 (modern via JWKS).

Copre:
  - HS256 happy path + invalid sig + expired + missing config.
  - ES256 happy path + wrong key + unknown kid + expired + missing config.
  - Algoritmi non-whitelist ('none', HS512, RS256) -> 401 senza verifica.
  - Routing corretto HS256 <-> ES256 in base all'header del token.

NB: i test ES256 generano al volo una coppia EC P-256 con `cryptography`,
poi mockano il JWKS client via monkeypatch di `_get_jwks_client` per evitare
network round-trip. END-TO-END behavior della verifica PyJWT e' preservata.
"""
from __future__ import annotations

import base64
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from spesemed.api import jwt_decoder
from spesemed.api.config import settings


# =============================================================================
# Helpers
# =============================================================================


def _generate_ec_keypair() -> tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    """Genera una coppia di chiavi EC P-256 (SECP256R1) al volo."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _public_key_to_jwk(public_key: ec.EllipticCurvePublicKey, kid: str) -> dict:
    """Converte una EC public key cryptography in un JWK dict (RFC 7517)."""
    pub_numbers = public_key.public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(pub_numbers.x.to_bytes(32, "big")),
        "y": _b64url(pub_numbers.y.to_bytes(32, "big")),
        "kid": kid,
        "use": "sig",
        "alg": "ES256",
    }


def _sign_es256(private_key: ec.EllipticCurvePrivateKey, kid: str, sub: str = "user-uuid-es256",
                exp_in: int = 3600, role: str = "authenticated",
                iss: str = "https://test.supabase.co/auth/v1") -> str:
    """Firma un JWT con EC P-256 usando la private key PEM.

    Default iss = "https://test.supabase.co/auth/v1" matcha il default
    `supabase_url` impostato dal setup TestES256.
    """
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    now = int(time.time())
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "exp": now + exp_in,
        "iat": now,
        "role": role,
        "iss": iss,
    }
    return jwt.encode(payload, pem, algorithm="ES256", headers={"kid": kid})


def _hs256_token(sub: str = "user-uuid-hs256", secret: str | None = None,
                 exp_in: int = 3600, role: str = "authenticated",
                 iss: str | None = None) -> str:
    """Genera un JWT HS256 valido.

    `iss` e' None di default: il test che vuole iss deve passarlo esplicitamente.
    Quando SUPABASE_URL e' vuoto (default TestHS256 setup), iss non e' richiesto
    dal decoder quindi il token senza iss passa comunque.
    """
    secret = secret or "test-secret"
    now = int(time.time())
    payload = {
        "sub": sub, "aud": "authenticated",
        "exp": now + exp_in, "iat": now, "role": role,
    }
    if iss is not None:
        payload["iss"] = iss
    return jwt.encode(payload, secret, algorithm="HS256")


def _fake_jwks_client(jwk: dict):
    """Restituisce un mock di `jwt.PyJWKClient` che serve sempre il JWK dato.

    Simula `get_signing_key_from_jwt(token)` facendo match sul `kid`
    dell'header (comportamento reale di Supabase JWKS).
    """
    from jwt import PyJWK
    from jwt.exceptions import PyJWKClientError

    class FakeClient:
        def __init__(self, jwk: dict) -> None:
            self._jwk = jwk

        def get_signing_key_from_jwt(self, token: str):  # noqa: D401
            header = jwt.get_unverified_header(token)
            if header.get("kid") != self._jwk["kid"]:
                raise PyJWKClientError(
                    f"kid mismatch: header={header.get('kid')!r} "
                    f"vs jwks={self._jwk['kid']!r}"
                )
            return PyJWK(self._jwk)

    return FakeClient(jwk)


# =============================================================================
# HS256 (legacy Supabase con symmetric JWT_SECRET)
# =============================================================================


class TestHS256:
    def test_valid_returns_sub(self, monkeypatch):
        # NB: settings e _hs256_token devono concordare sul secret.
        # _hs256_token firmato con "test-secret" (default).
        monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")
        monkeypatch.setattr(settings, "supabase_url", "")  # no iss check
        token = _hs256_token(sub="alice-uuid")
        payload = jwt_decoder.decode_supabase_jwt(token)
        assert payload["sub"] == "alice-uuid"

    def test_invalid_signature_raises_401(self, monkeypatch):
        monkeypatch.setattr(settings, "supabase_jwt_secret", "correct-secret")
        monkeypatch.setattr(settings, "supabase_url", "")
        token = _hs256_token(sub="alice-uuid", secret="wrong-secret")
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 401

    def test_expired_raises_401(self, monkeypatch):
        monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")
        monkeypatch.setattr(settings, "supabase_url", "")
        token = _hs256_token(exp_in=-10)
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 401
        assert "scaduto" in exc.value.detail.lower()

    def test_iss_mismatch_raises_401(self, monkeypatch):
        """iss != <supabase_url>/auth/v1 deve essere rifiutato (se URL configurato)."""
        monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")
        monkeypatch.setattr(settings, "supabase_url", "https://my.supabase.co")
        now = int(time.time())
        token = jwt.encode(
            {
                "sub": "alice-uuid", "aud": "authenticated",
                "iss": "https://OTHER-PROJECT.supabase.co/auth/v1",
                "exp": now + 3600, "iat": now, "role": "authenticated",
            },
            "test-secret", algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 401

    def test_role_service_role_rejected(self, monkeypatch):
        """CRITICAL: service_role bypassea RLS Supabase server-side. Mai accettare."""
        monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")
        monkeypatch.setattr(settings, "supabase_url", "")
        token = _hs256_token(sub="attacker", role="service_role")
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 401
        assert "Token JWT" in exc.value.detail

    def test_role_anon_rejected(self, monkeypatch):
        """anon role (Supabase anonymous sign-in) deve essere rifiutato."""
        monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")
        monkeypatch.setattr(settings, "supabase_url", "")
        token = _hs256_token(sub="anon-user", role="anon")
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 401
        assert "Token JWT" in exc.value.detail

    def test_missing_secret_raises_503(self, monkeypatch):
        """403/503: FAIL-CLOSED su config mancante, non 401 che sembrerebbe bug client."""
        monkeypatch.setattr(settings, "supabase_jwt_secret", "")
        monkeypatch.setattr(settings, "supabase_url", "")
        token = _hs256_token()
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 503


# =============================================================================
# ES256 (modern Supabase con EC P-256 JWKS)
# =============================================================================


class TestES256:
    def _setup(self, monkeypatch, kid: str = "test-key-1"):
        """Setup standard: EC keypair + JWK mock + auto-derived JWKS URL."""
        priv, pub = _generate_ec_keypair()
        jwk = _public_key_to_jwk(pub, kid)
        # Reset cache per garantire fresh state tra test.
        jwt_decoder.reset_jwks_cache()
        monkeypatch.setattr(settings, "supabase_jwt_secret", "")
        monkeypatch.setattr(settings, "supabase_url", "https://test.supabase.co")
        monkeypatch.setattr(settings, "supabase_jwks_url", "")  # auto-derive
        monkeypatch.setattr(
            jwt_decoder, "_get_jwks_client",
            lambda url: _fake_jwks_client(jwk),
        )
        return priv, kid

    def test_valid_returns_sub(self, monkeypatch):
        priv, kid = self._setup(monkeypatch)
        token = _sign_es256(priv, kid=kid, sub="bob-es256-uuid")
        payload = jwt_decoder.decode_supabase_jwt(token)
        assert payload["sub"] == "bob-es256-uuid"

    def test_wrong_key_raises_401(self, monkeypatch):
        """Firma con una private key DIVERSA, stesso kid: la firma non valida."""
        priv, kid = self._setup(monkeypatch)
        other_priv, _ = _generate_ec_keypair()
        token = _sign_es256(other_priv, kid=kid)
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 401

    def test_unknown_kid_raises_401(self, monkeypatch):
        """kid nell'header non presente nel JWKS: errore look-up."""
        priv, _ = self._setup(monkeypatch, kid="kid-A")
        token = _sign_es256(priv, kid="kid-unknown")
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 401

    def test_expired_raises_401(self, monkeypatch):
        priv, kid = self._setup(monkeypatch)
        token = _sign_es256(priv, kid=kid, exp_in=-10)
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 401

    def test_missing_jwks_url_raises_503(self, monkeypatch):
        """FAIL-CLOSED: ES256 senza SUPABASE_URL/SUPABASE_JWKS_URL -> 503."""
        priv, _ = _generate_ec_keypair()  # 2-tuple: (priv, pub); pub non serve qui.
        kid = "any-kid"
        monkeypatch.setattr(settings, "supabase_jwt_secret", "")
        monkeypatch.setattr(settings, "supabase_url", "")
        monkeypatch.setattr(settings, "supabase_jwks_url", "")
        token = _sign_es256(priv, kid=kid)
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 503

    def test_explicit_jwks_url_used(self, monkeypatch):
        """Se SUPABASE_JWKS_URL e' settato, sovrascrive l'auto-derive."""
        priv, pub = _generate_ec_keypair()
        jwk = _public_key_to_jwk(pub, "explicit-kid")
        jwt_decoder.reset_jwks_cache()
        monkeypatch.setattr(settings, "supabase_jwt_secret", "")
        monkeypatch.setattr(settings, "supabase_url", "https://test.supabase.co")
        monkeypatch.setattr(
            settings, "supabase_jwks_url",
            "https://custom-cdn.example.com/jwks.json",
        )
        monkeypatch.setattr(
            jwt_decoder, "_get_jwks_client",
            lambda url: (_fake_jwks_client(jwk) if "custom-cdn" in url
                         else pytest.fail(f"unexpected client URL: {url}")),
        )
        token = _sign_es256(priv, kid="explicit-kid")
        assert jwt_decoder.decode_supabase_jwt(token)["sub"] == "user-uuid-es256"


# =============================================================================
# Algoritmi non-whitelist (security: 'none', HS512, RS256, ...) -> 401 senza verifica
# =============================================================================


class TestUnsupportedAlgorithms:
    def test_none_alg_rejected(self, monkeypatch):
        """CVE-2015-2951: token con 'alg: none' deve essere rifiutato."""
        def _b64(d):  # noqa: ANN001
            return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
        header = {"alg": "none", "typ": "JWT"}
        payload = {
            "sub": "attacker", "aud": "authenticated",
            "exp": int(time.time()) + 3600, "role": "authenticated",
        }
        # Firmato con stringa vuota: classic none-alg bypass attempt.
        token = f"{_b64(header)}.{_b64(payload)}."
        monkeypatch.setattr(settings, "supabase_jwt_secret", "any-secret")
        monkeypatch.setattr(settings, "supabase_url", "")
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 401
        assert "Token JWT" in exc.value.detail

    def test_hs512_rejected(self, monkeypatch):
        """HS512 non e' in whitelist: deve essere rifiutato SENZA verifica."""
        monkeypatch.setattr(settings, "supabase_jwt_secret", "any-secret")
        monkeypatch.setattr(settings, "supabase_url", "")
        now = int(time.time())
        token = jwt.encode(
            {"sub": "x", "aud": "authenticated", "exp": now + 3600, "iss": "https://x.supabase.co/auth/v1"},
            "any-secret", algorithm="HS512",
        )
        with pytest.raises(HTTPException) as exc:
            jwt_decoder.decode_supabase_jwt(token)
        assert exc.value.status_code == 401
        assert "Token JWT" in exc.value.detail


# =============================================================================
# Routing HS256 / ES256 dall'header del token (NO algorithm confusion)
# =============================================================================


class TestAlgorithmRouting:
    def test_hs256_token_routes_to_secret_even_if_es256_configured(self, monkeypatch):
        """Se il token dichiara HS256, usa il secret (non tenta JWKS)."""
        priv, pub = _generate_ec_keypair()
        jwk = _public_key_to_jwk(pub, "es256-kid")
        jwt_decoder.reset_jwks_cache()
        monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")
        monkeypatch.setattr(settings, "supabase_url", "https://both.supabase.co")
        monkeypatch.setattr(
            jwt_decoder, "_get_jwks_client",
            lambda url: pytest.fail("HS256 token non dovrebbe interrogare JWKS"),
        )
        # Iss esplicito per matchare il supabase_url='https://both.supabase.co'.
        token = _hs256_token(
            sub="routed-hs256", iss="https://both.supabase.co/auth/v1",
        )
        assert jwt_decoder.decode_supabase_jwt(token)["sub"] == "routed-hs256"

    def test_es256_token_routes_to_jwks_even_if_hs256_configured(self, monkeypatch):
        """Se il token dichiara ES256, usa JWKS (non tenta HMAC con secret)."""
        priv, pub = _generate_ec_keypair()
        jwk = _public_key_to_jwk(pub, "routing-kid")
        jwt_decoder.reset_jwks_cache()
        monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")  # presente
        monkeypatch.setattr(settings, "supabase_url", "https://both.supabase.co")
        # Se l'helper tentasse HS256 qui, fallirebbe (la stringa PEM non e' HMAC valida).
        monkeypatch.setattr(
            jwt_decoder, "_get_jwks_client", lambda url: _fake_jwks_client(jwk),
        )
        # Iss esplicito per matchare il supabase_url='https://both.supabase.co'.
        token = _sign_es256(
            priv, kid="routing-kid", sub="routed-es256",
            iss="https://both.supabase.co/auth/v1",
        )
        assert jwt_decoder.decode_supabase_jwt(token)["sub"] == "routed-es256"
