import hashlib
import re
import secrets

from fastapi import Request, Response


def browser_owner(request: Request, response: Response) -> str:
    token = request.cookies.get("gm_session", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        token = secrets.token_urlsafe(32)
        response.set_cookie("gm_session", token, httponly=True, samesite="strict",
            max_age=31536000, path="/api", secure=request.url.scheme == "https")
    return hashlib.sha256(token.encode()).hexdigest()
