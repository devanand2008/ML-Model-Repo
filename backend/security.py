"""Single-operator authentication and bounded inference admission."""
import secrets
import time
from collections import defaultdict, deque
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from config import settings
from database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

basic = HTTPBasic(auto_error=False)
attempts = defaultdict(deque)

async def require_user(credentials: HTTPBasicCredentials | None = Depends(basic),
                       db: AsyncSession = Depends(get_db)):
    if not settings.auth_enabled:
        return "local"
    if credentials and (
        secrets.compare_digest(credentials.username.encode(), settings.admin_username.encode())
        and secrets.compare_digest(credentials.password.encode(), settings.admin_password.encode())
    ):
        return credentials.username
    if credentials:
        from transit.models import TransitAccount
        from transit.accounts import valid_password
        account = await db.get(TransitAccount, credentials.username)
        if account and account.active and account.role in {"admin", "head_office"} and valid_password(credentials.password, account.password_hash):
            return account.username
    raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Basic"})

async def require_admin(credentials: HTTPBasicCredentials | None = Depends(basic),
                        db: AsyncSession = Depends(get_db)):
    username = await require_user(credentials, db)
    if username == "local" or username == settings.admin_username:
        return username
    from transit.models import TransitAccount
    account = await db.get(TransitAccount, username)
    if not account or account.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return username

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
