"""Explicit per-route authorization policies.

The global middleware authenticates browser sessions and enforces CSRF/Origin.
Every mutating route declares its required role independently of URL patterns.
"""
from fastapi import HTTPException, Request

ROLE_ORDER = {"viewer": 0, "editor": 1, "admin": 2}

def require_authenticated(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user

def require_editor(request: Request) -> dict:
    user = require_authenticated(request)
    if ROLE_ORDER[user["role"]] < ROLE_ORDER["editor"]:
        raise HTTPException(status_code=403, detail="Editor role required.")
    return user

def require_admin(request: Request) -> dict:
    user = require_authenticated(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required.")
    return user
