"""Role credentials for the driver and head-office mobility APIs."""
import base64
import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from transit.models import TransitAccount

basic = HTTPBasic(auto_error=False)


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return "pbkdf2_sha256$310000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def valid_password(password: str, encoded: str) -> bool:
    try:
        method, count, salt, digest = encoded.split("$")
        if method != "pbkdf2_sha256" or int(count) != 310_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(count))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


async def actor(credentials: HTTPBasicCredentials | None = Depends(basic),
                db: AsyncSession = Depends(get_db)) -> dict:
    if credentials is None:
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Basic"})
    if (hmac.compare_digest(credentials.username, settings.admin_username) and
            hmac.compare_digest(credentials.password, settings.admin_password)):
        return {"username": credentials.username, "role": "admin", "bus_id": None}
    account = await db.get(TransitAccount, credentials.username)
    if account is None or not account.active or not valid_password(credentials.password, account.password_hash):
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Basic"})
    return {"username": account.username, "role": account.role, "bus_id": account.bus_id}


def allowed(user: dict, roles: set[str], bus_id: str | None = None) -> None:
    if user["role"] not in roles:
        raise HTTPException(403, "This role cannot perform that action")
    if user["role"] == "driver" and bus_id != user["bus_id"]:
        raise HTTPException(403, "Driver account is assigned to a different bus")
