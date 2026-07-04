from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from app.core.config import Settings
from app.core.security import make_random_token


@dataclass(frozen=True)
class OAuthProfile:
    provider: str
    subject: str
    email: str | None
    name: str | None
    avatar_url: str | None


class OAuthService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def authorize_url(self, provider: str) -> tuple[str, str]:
        state = make_random_token(18)
        if provider == "github":
            self._require(self.settings.github_client_id, self.settings.github_client_secret, "GitHub")
            query = urlencode(
                {
                    "client_id": self.settings.github_client_id,
                    "redirect_uri": self.callback_url("github"),
                    "scope": "read:user user:email",
                    "state": state,
                }
            )
            return f"https://github.com/login/oauth/authorize?{query}", state

        if provider == "google":
            self._require(self.settings.google_client_id, self.settings.google_client_secret, "Google")
            query = urlencode(
                {
                    "client_id": self.settings.google_client_id,
                    "redirect_uri": self.callback_url("google"),
                    "response_type": "code",
                    "scope": "openid email profile",
                    "state": state,
                    "access_type": "online",
                    "prompt": "select_account",
                }
            )
            return f"https://accounts.google.com/o/oauth2/v2/auth?{query}", state

        raise HTTPException(status_code=404, detail="Unsupported OAuth provider")

    def callback_url(self, provider: str) -> str:
        return f"{self.settings.public_base_url}/api/auth/oauth/{provider}/callback"

    async def fetch_profile(self, provider: str, code: str) -> OAuthProfile:
        if provider == "github":
            return await self._fetch_github_profile(code)
        if provider == "google":
            return await self._fetch_google_profile(code)
        raise HTTPException(status_code=404, detail="Unsupported OAuth provider")

    async def _fetch_github_profile(self, code: str) -> OAuthProfile:
        async with httpx.AsyncClient(timeout=12) as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.settings.github_client_id,
                    "client_secret": self.settings.github_client_secret,
                    "code": code,
                    "redirect_uri": self.callback_url("github"),
                },
            )
            token = self._access_token(token_response)
            user_response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            user_response.raise_for_status()
            user = user_response.json()
            email = user.get("email")
            if not email:
                email_response = await client.get(
                    "https://api.github.com/user/emails",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
                if email_response.status_code == 200:
                    for item in email_response.json():
                        if item.get("primary") and item.get("verified"):
                            email = item.get("email")
                            break
            return OAuthProfile(
                provider="github",
                subject=str(user["id"]),
                email=email,
                name=user.get("name") or user.get("login"),
                avatar_url=user.get("avatar_url"),
            )

    async def _fetch_google_profile(self, code: str) -> OAuthProfile:
        async with httpx.AsyncClient(timeout=12) as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.settings.google_client_id,
                    "client_secret": self.settings.google_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.callback_url("google"),
                },
            )
            token = self._access_token(token_response)
            user_response = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {token}"},
            )
            user_response.raise_for_status()
            user = user_response.json()
            return OAuthProfile(
                provider="google",
                subject=str(user["sub"]),
                email=user.get("email"),
                name=user.get("name") or user.get("email"),
                avatar_url=user.get("picture"),
            )

    def _access_token(self, response: httpx.Response) -> str:
        if response.status_code >= 400:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=response.text)
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="OAuth token missing")
        return token

    def _require(self, client_id: str | None, client_secret: str | None, provider: str) -> None:
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"{provider} OAuth is not configured",
            )
