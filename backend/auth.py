import jwt
import bcrypt
from datetime import datetime, timedelta
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import User, Role

JWT_SECRET = "super-secret-key-12345678-very-secure"
ALGORITHM = "HS256"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

hash_password = get_password_hash

def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

def get_current_user_payload(token: str = Cookie(None)) -> dict | None:
    if not token:
        return None
    return decode_token(token)

def get_current_user(
    token: str = Cookie(None),
    db: Session = Depends(get_db)
) -> User | None:
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    
    user_id = payload.get("userId")
    if not user_id:
        return None
        
    user = db.query(User).filter(User.id == user_id).first()
    return user
