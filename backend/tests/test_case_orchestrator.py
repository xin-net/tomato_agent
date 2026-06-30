from app.domain.enums import CaseStatus
from app.schemas.cases import CreateCaseInput, FollowupInput
from app.services.case_orchestrator import CaseOrchestrator


def test_create_case_asks_more_info_when_input_is_sparse(db_session):
    response = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(symptoms="我的番茄叶子发黄，还有一些斑点，怎么办？")
    )

    assert response.status == CaseStatus.NEED_MORE_INFO
    assert response.response_type == "questions"
    assert response.decision is not None
    assert response.decision.questions


def test_create_case_diagnoses_and_creates_followup_when_info_is_enough(db_session):
    response = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="下部老叶有褐色斑点，一圈一圈的，最近连续阴雨，现在结果期，距离采收大概 10 天。",
            affected_parts=["下部老叶"],
            recent_weather="连续阴雨",
            days_to_harvest=10,
        )
    )

    assert response.status == CaseStatus.FOLLOWUP_PENDING
    assert response.response_type == "diagnosis_and_plan"
    assert response.diagnosis is not None
    assert response.diagnosis.suspected_problem == "番茄早疫病"
    assert response.followup is not None


def test_followup_worsening_escalates_case(db_session):
    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="下部老叶有褐色斑点，一圈一圈的，最近连续阴雨，现在结果期，距离采收大概 10 天。",
            affected_parts=["下部老叶"],
            recent_weather="连续阴雨",
            days_to_harvest=10,
        )
    )

    response = CaseOrchestrator(db_session).submit_followup(
        created.case_id,
        FollowupInput(
            description="病斑变多了，上部叶片也开始有斑。",
            has_new_spots=True,
            spread_to_new_parts=True,
        ),
    )

    assert response.status == CaseStatus.ESCALATED
    assert response.trend is not None


def test_near_harvest_blocks_chemical_details(db_session):
    response = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="下部老叶有褐色斑点，一圈一圈的，结果期，还有 4 天采收。",
            affected_parts=["下部老叶"],
            days_to_harvest=4,
        )
    )

    assert response.safety is not None
    assert response.safety.chemical_detail_allowed is False
    assert any("采收" in warning for warning in response.safety.warnings)
