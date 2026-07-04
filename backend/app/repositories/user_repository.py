from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.domain.models import User
from app.schemas.auth import UserCreate


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return self.db.scalar(stmt)

    def create(self, data: UserCreate, role: str = "user") -> User:
        user = User(
            username=data.username,
            password_hash=hash_password(data.password),
            role=role,
        )
        self.db.add(user)
        self.db.flush()
        return user
