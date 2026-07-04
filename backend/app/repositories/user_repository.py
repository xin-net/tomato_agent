from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, make_random_token
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

    def get_by_provider(self, provider: str, provider_subject: str) -> User | None:
        stmt = select(User).where(
            User.auth_provider == provider,
            User.provider_subject == provider_subject,
        )
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

    def get_or_create_oauth_user(
        self,
        provider: str,
        provider_subject: str,
        email: str | None,
        display_name: str | None,
        avatar_url: str | None,
    ) -> User:
        existing = self.get_by_provider(provider, provider_subject)
        if existing:
            existing.email = email or existing.email
            existing.avatar_url = avatar_url or existing.avatar_url
            self.db.flush()
            return existing

        base_username = self._normalize_username(display_name or email or f"{provider}_{provider_subject}")
        username = base_username
        while self.get_by_username(username):
            username = f"{base_username}_{make_random_token(4)}"

        user = User(
            username=username,
            password_hash=None,
            email=email,
            avatar_url=avatar_url,
            auth_provider=provider,
            provider_subject=provider_subject,
            role="user",
        )
        self.db.add(user)
        self.db.flush()
        return user

    def _normalize_username(self, value: str) -> str:
        normalized = "".join(char.lower() if char.isalnum() else "_" for char in value)
        normalized = "_".join(part for part in normalized.split("_") if part)
        return (normalized or "oauth_user")[:60]
