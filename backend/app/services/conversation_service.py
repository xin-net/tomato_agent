from sqlalchemy.orm import Session

from app.domain.enums import CaseStatus
from app.repositories.case_repository import CaseRepository
from app.schemas.cases import CreateCaseInput, ReplyInput
from app.schemas.conversation import ConversationMessageInput, ConversationMessageResponse
from app.services.case_orchestrator import CaseOrchestrator


class ConversationService:
    def __init__(self, db: Session):
        self.db = db
        self.cases = CaseRepository(db)
        self.orchestrator = CaseOrchestrator(db)

    def handle_message(self, data: ConversationMessageInput) -> ConversationMessageResponse:
        case_id = data.case_id
        created_case = False

        if case_id is None:
            active_case = self.cases.latest_active_for_user(data.user_id)
            case_id = active_case.id if active_case else None

        if case_id is None:
            response = self.orchestrator.create_case(
                CreateCaseInput(
                    user_id=data.user_id,
                    symptoms=data.message,
                    image_urls=data.image_urls,
                )
            )
            created_case = True
        else:
            case = self.cases.get(case_id)
            if case is None:
                response = self.orchestrator.create_case(
                    CreateCaseInput(
                        user_id=data.user_id,
                        symptoms=data.message,
                        image_urls=data.image_urls,
                    )
                )
                created_case = True
            elif case.status == CaseStatus.CLOSED.value:
                response = self.orchestrator.create_case(
                    CreateCaseInput(
                        user_id=data.user_id,
                        symptoms=data.message,
                        image_urls=data.image_urls,
                    )
                )
                created_case = True
            else:
                response = self.orchestrator.reply_to_case(
                    case_id,
                    ReplyInput(message=data.message, image_urls=data.image_urls),
                )

        return ConversationMessageResponse(
            case_id=response.case_id,
            created_case=created_case,
            response=response,
        )
