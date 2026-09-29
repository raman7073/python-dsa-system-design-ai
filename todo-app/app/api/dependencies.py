from typing import Annotated
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.session import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")
DatabaseSession = Annotated[Session, Depends(get_db)]

def current_user(token: Annotated[str, Depends(oauth2_scheme)], db: DatabaseSession):
    unauthorized = HTTPException(401, "Invalid or expired credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"],
                             issuer="todo-api", audience="todo-api",
                             options={"require": ["sub", "exp", "iat", "iss", "aud"]})
        subject = payload["sub"]
        if not isinstance(subject, str) or not subject.isascii() or not subject.isdecimal() or len(subject) > 18:
            raise unauthorized
        user = db.get(User, int(subject))
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized
    if user is None:
        raise unauthorized
    return user

CurrentUser = Annotated[User, Depends(current_user)]
