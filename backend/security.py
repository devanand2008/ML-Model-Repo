"""Single-operator authentication and bounded inference admission."""
import secrets
import time
from collections import defaultdict, deque
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from config import settings

basic = HTTPBasic(auto_error=False)
attempts = defaultdict(deque)

def require_user(credentials: HTTPBasicCredentials | None = Depends(basic)):
    if not settings.auth_enabled:
        return "local"
    if not credentials or not (
        secrets.compare_digest(credentials.username.encode(), settings.admin_username.encode())
        and secrets.compare_digest(credentials.password.encode(), settings.admin_password.encode())
    ):
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

def require_admin(credentials: HTTPBasicCredentials | None = Depends(basic)):
    # Local development is a trusted single-operator installation.
    return require_user(credentials)

def inference_limit(request: Request, user=Depends(require_user)):
    key = (request.client.host if request.client else "local", user)
    now = time.monotonic()
    for old in list(attempts):
        if not attempts[old] or attempts[old][-1] < now - 60:
            del attempts[old]
    bucket = attempts[key]
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    if len(bucket) >= 30:
        raise HTTPException(429, "Inference limit reached. Retry in one minute.", headers={"Retry-After": "60"})
    bucket.append(now)
