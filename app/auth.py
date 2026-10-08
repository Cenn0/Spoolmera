"""Cookie-session authentication, CSRF and role-based account administration.

No anonymous inventory API. Session tokens are stored as hashes, not bearer
credentials; all mutating requests use a session-bound CSRF header.
"""
import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.database import session, utc_now

COOKIE = "filament_session"
SESSION_SECONDS = 7 * 24 * 3600
DUMMY_SALT = b"filament-manager-dummy"
ROLE_ORDER = {"viewer": 0, "editor": 1, "admin": 2}


class LoginForm(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=128)


class SetupForm(LoginForm):
    password: str = Field(min_length=14, max_length=128)


class NewUser(LoginForm):
    password: str = Field(min_length=14, max_length=128)
    role: Literal["admin", "editor", "viewer"] = "viewer"


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["admin", "editor", "viewer"] | None = None
    enabled: bool | None = None
    password: str | None = Field(default=None, min_length=14, max_length=128)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=14, max_length=128)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$16384$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(derived).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    try:
        if hashed:
            algorithm, rounds, salt_text, derived_text = hashed.split("$")
            if algorithm != "scrypt" or rounds != "16384":
                raise ValueError("Unsupported credential scheme")
            salt = base64.b64decode(salt_text, validate=True)
            expected = base64.b64decode(derived_text, validate=True)
        else:
            salt, expected = DUMMY_SALT, b"\0" * 32
        attempt = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
        return bool(hashed) and hmac.compare_digest(expected, attempt)
    except (ValueError, UnicodeError):
        return False


def auth_user(db_path: Path, request: Request):
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 200:
        return None
    digest = hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()
    with session(db_path) as db:
        row = db.execute(
            """SELECT u.id, u.username, u.role, u.enabled, s.csrf_token
               FROM auth_sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token_hash=? AND s.expires_at>?""",
            (digest, int(time.time())),
        ).fetchone()
    return dict(row) if row is not None and row["enabled"] else None


def issue_session(db, user_id: int, response: JSONResponse) -> str:
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    db.execute("INSERT INTO auth_sessions(token_hash,user_id,csrf_token,expires_at) VALUES(?,?,?,?)",
               (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, int(time.time()) + SESSION_SECONDS))
    response.set_cookie(
        COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=os.getenv("FILAMENT_COOKIE_SECURE", "0") == "1",
        samesite="lax", path="/",
    )
    return csrf


def public_user(row, csrf: str | None = None) -> dict:
    data = {key: row[key] for key in ("id", "username", "role") }
    if csrf is not None:
        data["csrf_token"] = csrf
    return data


def audit(db, actor: int | None, action: str, entity: str, entity_id: int | None = None):
    db.execute("INSERT INTO audit_events(actor_id,action,entity,entity_id,created_at) VALUES(?,?,?,?,?)",
               (actor, action, entity, entity_id, utc_now()))


def protect(app: FastAPI, db_path: Path) -> None:
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        method = request.method.upper()
        # This is a same-origin JSON API. Cross-site form or fetch writes are never accepted.
        if method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
                return JSONResponse({"detail": "Cross-site requests are forbidden."}, status_code=403)
            origin = request.headers.get("origin")
            if origin:
                from urllib.parse import urlsplit
                expected = os.getenv("FILAMENT_PUBLIC_BASE_URL", "").rstrip("/")
                self_origin = str(request.base_url).rstrip("/")
                if origin not in (expected, self_origin):
                    return JSONResponse({"detail": "Origin not permitted."}, status_code=403)
        public = path in {"/api/health", "/api/auth/status", "/api/auth/setup", "/api/auth/login"}
        api = path.startswith("/api/")
        protected_page = path.startswith("/labels/") or path in {"/docs", "/redoc", "/openapi.json"}
        if (api and not public) or protected_page:
            user = auth_user(db_path, request)
            if not user:
                return JSONResponse({"detail": "Authentication required."}, status_code=401,
                                    headers={"Cache-Control": "no-store"})
            request.state.user = user
            if path.startswith("/api/auth/users") and user["role"] != "admin":
                return JSONResponse({"detail": "Administrator role required."}, status_code=403)
            if path.startswith("/api/printers") and method not in {"GET", "HEAD"}:
                # Editors may request a read-only status poll; only admins configure devices.
                poll = method == "POST" and path.endswith("/poll")
                required = "editor" if poll else "admin"
                if ROLE_ORDER[user["role"]] < ROLE_ORDER[required]:
                    return JSONResponse({"detail": required + " role required."}, status_code=403)
            elif method not in {"GET", "HEAD", "OPTIONS"} and ROLE_ORDER[user["role"]] < ROLE_ORDER["editor"]:
                # Password/logout for viewer must still be allowed.
                if path not in ("/api/auth/logout", "/api/auth/password"):
                    return JSONResponse({"detail": "Editor role required."}, status_code=403)
            if method not in {"GET", "HEAD", "OPTIONS"} and (
                not hmac.compare_digest(request.headers.get("x-csrf-token", ""), user["csrf_token"])
            ):
                return JSONResponse({"detail": "Invalid CSRF token."}, status_code=403)
        response = await call_next(request)
        if api or protected_page:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/auth/status")
    def status():
        with session(db_path) as db:
            count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return {"needs_setup": count == 0}

    @app.post("/api/auth/setup")
    def setup(payload: SetupForm, request: Request):
        secret = os.getenv("FILAMENT_BOOTSTRAP_TOKEN", "")
        provided = request.headers.get("x-bootstrap-token", "")
        if len(secret) < 24 or not hmac.compare_digest(secret, provided):
            raise HTTPException(status_code=403, detail="A configured bootstrap token is required.")
        with session(db_path, write=True) as db:
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise HTTPException(status_code=409, detail="Initial setup already completed.")
            user_id = db.execute(
                "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,'admin',?)",
                (payload.username, hash_password(payload.password), utc_now()),
            ).lastrowid
            response = JSONResponse({"id": user_id, "username": payload.username, "role": "admin"})
            csrf = issue_session(db, user_id, response)
            audit(db, user_id, "bootstrap", "user", user_id)
            data = {"id": user_id, "username": payload.username, "role": "admin", "csrf_token": csrf}
            response.body = response.render(data)
            response.headers["content-length"] = str(len(response.body))
        return response

    @app.post("/api/auth/login")
    def login(payload: LoginForm, request: Request):
        subject = hashlib.sha256((payload.username.casefold() + "|" +
                   (request.client.host if request.client else "unknown")).encode()).hexdigest()
        now = int(time.time())
        with session(db_path, write=True) as db:
            db.execute("DELETE FROM auth_failures WHERE created_at < ?", (now - 900,))
            count = db.execute("SELECT COUNT(*) FROM auth_failures WHERE subject=?", (subject,)).fetchone()[0]
            if count >= 5:
                raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
            row = db.execute("SELECT * FROM users WHERE username=?", (payload.username,)).fetchone()
            valid = verify_password(payload.password, row["password_hash"] if row is not None else None)
            if not valid or not row["enabled"]:
                db.execute("INSERT INTO auth_failures(subject,created_at) VALUES(?,?)", (subject, now))
                raise HTTPException(status_code=401, detail="Invalid credentials.")
            db.execute("DELETE FROM auth_failures WHERE subject=?", (subject,))
            response = JSONResponse({"id": row["id"], "username": row["username"], "role": row["role"]})
            csrf = issue_session(db, row["id"], response)
            response.body = response.render(public_user(row, csrf))
            response.headers["content-length"] = str(len(response.body))
            audit(db, row["id"], "login", "user", row["id"])
            return response

    @app.get("/api/auth/me")
    def me(request: Request):
        return public_user(request.state.user, request.state.user["csrf_token"])

    @app.post("/api/auth/logout")
    def logout(request: Request):
        token = request.cookies.get(COOKIE, "")
        with session(db_path, write=True) as db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash=?",
                       (hashlib.sha256(token.encode()).hexdigest(),))
        response = JSONResponse({"logged_out": True})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.post("/api/auth/password")
    def password_change(request: Request, payload: PasswordChange):
        actor = request.state.user["id"]
        with session(db_path, write=True) as db:
            row = db.execute("SELECT password_hash FROM users WHERE id=?", (actor,)).fetchone()
            if not row or not verify_password(payload.old_password, row["password_hash"]):
                raise HTTPException(status_code=403, detail="Current password incorrect.")
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(payload.new_password), actor))
            db.execute("DELETE FROM auth_sessions WHERE user_id=?", (actor,))
            response = JSONResponse({"id": actor})
            csrf = issue_session(db, actor, response)
            response.body = response.render({"id": actor, "csrf_token": csrf})
            response.headers["content-length"] = str(len(response.body))
            audit(db, actor, "password_change", "user", actor)
        return response

    @app.get("/api/auth/users")
    def list_users():
        with session(db_path) as db:
            return [dict(row) for row in db.execute(
                "SELECT id,username,role,enabled,created_at FROM users ORDER BY username COLLATE NOCASE"
            ).fetchall()]

    @app.post("/api/auth/users", status_code=201)
    def create_user(request: Request, payload: NewUser):
        with session(db_path, write=True) as db:
            if db.execute("SELECT 1 FROM users WHERE username=?", (payload.username,)).fetchone():
                raise HTTPException(status_code=409, detail="Username already exists.")
            user_id = db.execute(
                "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                (payload.username, hash_password(payload.password), payload.role, utc_now())
            ).lastrowid
            audit(db, request.state.user["id"], "user_create", "user", user_id)
        return {"id": user_id}

    @app.patch("/api/auth/users/{user_id}")
    def update_user(user_id: int, payload: UserUpdate, request: Request):
        changes = payload.model_dump(exclude_unset=True)
        if not changes or any(value is None for value in changes.values()):
            raise HTTPException(status_code=422, detail="At least one non-null field is required.")
        if "password" in changes:
            changes["password_hash"] = hash_password(changes.pop("password"))
        if "enabled" in changes:
            changes["enabled"] = int(changes["enabled"])
        with session(db_path, write=True) as db:
            row = db.execute("SELECT id,role,enabled FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User not found.")
            if row["role"] == "admin" and row["enabled"] and (
                changes.get("role", row["role"]) != "admin" or changes.get("enabled", row["enabled"]) == 0
            ):
                active = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[0]
                if active <= 1:
                    raise HTTPException(status_code=409, detail="At least one active admin must remain.")
            assignments = ", ".join(f"{key}=?" for key in changes)
            db.execute(f"UPDATE users SET {assignments} WHERE id=?", (*changes.values(), user_id))
            db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
            audit(db, request.state.user["id"], "user_update", "user", user_id)
        return {"id": user_id}
