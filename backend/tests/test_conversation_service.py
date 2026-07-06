from app.schemas.conversation import ConversationMessageInput
from app.services.conversation_service import ConversationService


def test_conversation_message_creates_case_when_no_active_case_exists(db_session):
    response = ConversationService(db_session).handle_message(
        ConversationMessageInput(
            user_id="u1",
            message="我的番茄叶子发黄，还有一些斑点，怎么办？",
        )
    )

    assert response.created_case is True
    assert response.case_id == 1
    assert response.response.response_type == "questions"


def test_conversation_message_without_case_id_starts_new_case(db_session):
    service = ConversationService(db_session)
    first = service.handle_message(
        ConversationMessageInput(user_id="u1", message="我的番茄叶子发黄，还有一些斑点，怎么办？")
    )

    second = service.handle_message(
        ConversationMessageInput(
            user_id="u1",
            message="主要是下部老叶，有褐色斑点，有同心轮纹，现在结果期，距离采收大概 10 天。",
        )
    )

    assert second.created_case is True
    assert second.case_id != first.case_id


def test_conversation_message_continues_explicit_case(db_session):
    service = ConversationService(db_session)
    first = service.handle_message(
        ConversationMessageInput(user_id="u1", message="我的番茄叶子发黄，还有一些斑点，怎么办？")
    )

    second = service.handle_message(
        ConversationMessageInput(
            user_id="u1",
            case_id=first.case_id,
            message="主要是下部老叶，有褐色斑点，有同心轮纹，现在结果期，距离采收大概 10 天。",
        )
    )

    assert second.created_case is False
    assert second.case_id == first.case_id


def test_conversation_message_records_image_evidence(db_session):
    response = ConversationService(db_session).handle_message(
        ConversationMessageInput(
            user_id="u1",
            message="下部老叶有褐色斑点，现在结果期，距离采收大概 10 天。",
            image_urls=["data:image/png;base64,abc123"],
        )
    )

    case = ConversationService(db_session).cases.get_detail(response.case_id)
    assert case is not None
    assert case.structured_data["image_evidence"] == ["data:image/png;base64,abc123"]
    assert any(event.event_type == "IMAGE_EVIDENCE_ADDED" for event in case.events)
    user_message = next(event for event in case.events if event.event_type == "USER_MESSAGE")
    assert user_message.structured_data["image_urls"] == ["data:image/png;base64,abc123"]
    assert any(event.event_type == "AGENT_RESPONSE" for event in case.events)
