"""Registration, login, logout and the current user."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import hash_password, hash_token, new_session_token, verify_password
from app.models import AuthSession, User
from app.schemas import Credentials, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Brute-force protection without letting anyone lock a user out (SEC-02).
#
#   * Only FAILED logins are counted.
#   * A browser that has signed in to an account gets a signed "device cookie" and its own
#     failure budget for that account (OWASP "device cookies"). Failures from other clients,
#     e.g. an attacker hammering the email, never block a known device.
#   * Other clients: by default every request reaches the API from the Next.js container and the
#     proxy passes a client-supplied X-Forwarded-For through, so IPs are not trusted and these
#     clients share one budget per email. When the production ingress (deploy/Caddyfile) is in
#     front, it overwrites X-Auditor-Client-IP with the real peer address and
#     AUDITOR_TRUST_CLIENT_IP_HEADER=true; each IP then has its own budget per email, with a much
#     larger cap per email across all IPs (distributed guessing) and a cap per IP across all
#     emails (password spraying).
# Counters are per process and in memory (the API runs as one process in Compose).
_attempts: dict[str, deque[float]] = defaultdict(deque)
MAX_ATTEMPTS, WINDOW_SECONDS = 10, 300
MAX_PER_EMAIL_ALL_IPS = 100  # unknown clients, all IPs together, per email
MAX_PER_IP_ALL_EMAILS = 50  # unknown clients, one IP, all emails
CLIENT_IP_HEADER = "x-auditor-client-ip"
DEVICE_COOKIE = "auditor_device"
DEVICE_TTL_DAYS = 180
_PROCESS_SECRET = secrets.token_bytes(32)  # used when AUDITOR_SECRET_KEY is unset (dev/test)
# Pre-computed hash so unknown-email logins take as long as wrong-password logins.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def _secret() -> bytes:
    key = get_settings().secret_key
    return key.encode() if key else _PROCESS_SECRET


def _sign(email: str, nonce: str) -> str:
    return hmac.new(_secret(), f"{email}|{nonce}".encode(), hashlib.sha256).hexdigest()


def _device_nonce(request: Request, email: str) -> str | None:
    """The nonce of a valid device cookie for this email, else None."""
    raw = request.cookies.get(DEVICE_COOKIE, "")
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    cookie_email_hash, nonce, sig = parts
    if not hmac.compare_digest(cookie_email_hash, hashlib.sha256(email.encode()).hexdigest()[:16]):
        return None
    return nonce if hmac.compare_digest(sig, _sign(email, nonce)) else None


def _set_device_cookie(response: Response, email: str) -> None:
    nonce = secrets.token_urlsafe(16)
    value = f"{hashlib.sha256(email.encode()).hexdigest()[:16]}.{nonce}.{_sign(email, nonce)}"
    response.set_cookie(DEVICE_COOKIE, value, httponly=True, secure=get_settings().cookie_secure,
                        samesite="lax", max_age=DEVICE_TTL_DAYS * 86400, path="/api/auth")


def _client_ip(request: Request) -> str | None:
    """The client IP set by the trusted ingress, or None when it is not configured or not valid."""
    if not get_settings().trust_client_ip_header:
        return None
    try:
        return str(ipaddress.ip_address(request.headers.get(CLIENT_IP_HEADER, "").strip()))
    except ValueError:
        return None


def _buckets(request: Request, email: str) -> list[tuple[str, int]]:
    """Failure counters a login attempt is checked against, as (key, limit); the first is personal."""
    nonce = _device_nonce(request, email)
    if nonce:
        return [(f"login|{email}|device:{nonce}", MAX_ATTEMPTS)]
    ip = _client_ip(request)
    if ip is None:
        return [(f"login|{email}|unknown", MAX_ATTEMPTS)]
    return [(f"login|{email}|ip:{ip}", MAX_ATTEMPTS),
            (f"login|{email}|all-ips", MAX_PER_EMAIL_ALL_IPS),
            (f"login-ip|{ip}", MAX_PER_IP_ALL_EMAILS)]


def _recent(key: str) -> deque[float]:
    q = _attempts[key]
    now = time.monotonic()
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()
    return q


def _check(key: str, limit: int = MAX_ATTEMPTS) -> None:
    if len(_recent(key)) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts; try again later")


def _rate_limit(request: Request, email: str) -> None:
    """Registration: every attempt counts, per email (only affects that unregistered address)."""
    key = f"register|{email.lower()}"
    _check(key)
    _attempts[key].append(time.monotonic())


def _start_session(db: Session, user: User, response: Response) -> None:
    s = get_settings()
    token = new_session_token()
    db.add(AuthSession(user_id=user.id, token_hash=hash_token(token),
                       expires_at=datetime.now(UTC) + timedelta(hours=s.session_ttl_hours)))
    db.commit()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=s.cookie_secure, samesite="lax",
                        max_age=s.session_ttl_hours * 3600, path="/")
    _set_device_cookie(response, user.email)


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    if not get_settings().allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled")
    _rate_limit(request, body.email)
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    _start_session(db, user, response)
    return user


@router.post("/login", response_model=UserOut)
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    buckets = _buckets(request, email)
    for key, limit in buckets:
        _check(key, limit)
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(user.password_hash if user else _DUMMY_HASH, body.password) and user is not None
    if not ok:
        now = time.monotonic()
        for key, _ in buckets:
            _attempts[key].append(now)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    _attempts.pop(buckets[0][0], None)  # success clears this client's own counter only
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id,
                                         AuthSession.expires_at < datetime.now(UTC)))
    _start_session(db, user, response)
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
