from pydantic import BaseModel, Field

from app.schemas.cases import CaseResponse


class ConversationMessageInput(BaseModel):
    message: str
    user_id: str = "default"
    case_id: int | None = None
    image_urls: list[str] = Field(default_factory=list)


class ConversationMessageResponse(BaseModel):
    case_id: int
    created_case: bool
    response: CaseResponse
