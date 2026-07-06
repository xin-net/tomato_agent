from app.domain.enums import CaseStatus, EventType
from app.domain.models import Reminder
from app.schemas.cases import CreateCaseInput, FollowupInput, ReplyInput
from app.services.case_orchestrator import CaseOrchestrator
from app.tools.semantic_observation_tool import SemanticObservation
from app.tools.vision_tool import VisionObservation


def semantic_stub(**overrides):
    defaults = {
        "status": "analyzed",
        "is_configured": True,
        "model": "test-semantic",
        "confidence": "high",
        "user_intent": "initial_diagnosis",
    }
    defaults.update(overrides)
    return SemanticObservation(**defaults)


def test_create_case_asks_more_info_when_input_is_sparse(db_session):
    response = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(symptoms="我的番茄叶子发黄，还有一些斑点，怎么办？")
    )

    assert response.status == CaseStatus.NEED_MORE_INFO
    assert response.response_type == "questions"
    assert response.decision is not None
    assert response.decision.questions
    assert response.advice is not None
    assert response.advice.information_sufficient is False
    assert "不建议直接用药" in response.advice.chemical_advice


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
    assert response.advice is not None
    assert response.advice.information_sufficient is True
    assert response.advice.problem_category == "病害"
    assert response.advice.immediate_actions
    assert response.advice.observation_points
    assert response.advice.escalation_conditions
    assert response.advice.followup_if_better
    assert response.advice.followup_if_worse

    detail = CaseOrchestrator(db_session).cases.get_detail(response.case_id)
    assert detail is not None
    assert detail.growth_stage == "结果期"
    assert detail.recent_weather == "连续阴雨"
    assert detail.days_to_harvest == 10
    assert db_session.query(Reminder).filter_by(case_id=response.case_id, status="pending").count() == 1
    assert any(event.event_type == EventType.DATE_OBSERVED for event in detail.events)
    assert any(event.event_type == EventType.WEATHER_OBSERVED for event in detail.events)
    tool_events = [event.system_output["tool"] for event in detail.events if event.event_type == EventType.TOOL_CALLED]
    assert "DateTool" in tool_events
    assert "LocationTool" in tool_events
    assert "WeatherTool" in tool_events
    assert "KnowledgeSearchTool" in tool_events
    assert "DiagnosisTool" in tool_events
    assert "SafetyChecker" in tool_events
    assert "PlanTool" in tool_events
    assert "CalendarReminderTool" in tool_events
    assert "ResponseComposer" in tool_events
    tool_outputs = {
        event.system_output["tool"]: event.system_output["output"]
        for event in detail.events
        if event.event_type == EventType.TOOL_CALLED
    }
    assert tool_outputs["DateTool"]["today"]
    assert tool_outputs["WeatherTool"]["risk_signals"]
    assert tool_outputs["CalendarReminderTool"]["due_date"]
    assert tool_outputs["CalendarReminderTool"]["calendar_url"]
    assert tool_outputs["CalendarReminderTool"]["ics_url"]


def test_weather_coordinates_affect_safety_and_plan(db_session, monkeypatch):
    def fake_weather(self, latitude, longitude):
        return {
            "temperature_2m": 33.2,
            "relative_humidity_2m": 91,
            "precipitation": 0.4,
            "wind_speed_10m": 5.1,
        }

    monkeypatch.setattr("app.tools.weather_tool.WeatherTool._fetch_open_meteo", fake_weather)

    response = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="叶背有小白虫，一碰有白色飞虫，结果期，距离采收大概 10 天。",
            affected_parts=["叶背"],
            days_to_harvest=10,
            latitude=30.67,
            longitude=104.06,
            location_label="成都附近",
        )
    )

    assert response.safety is not None
    assert any("实时相对湿度" in warning for warning in response.safety.warnings)
    assert response.plan is not None
    assert any("通风" in action for action in response.plan.immediate_actions)

    detail = CaseOrchestrator(db_session).cases.get_detail(response.case_id)
    weather_event = next(
        event
        for event in detail.events
        if event.event_type == EventType.TOOL_CALLED and event.system_output["tool"] == "WeatherTool"
    )
    location_event = next(
        event
        for event in detail.events
        if event.event_type == EventType.TOOL_CALLED and event.system_output["tool"] == "LocationTool"
    )
    assert location_event.system_output["output"]["location_source"] == "browser"
    assert weather_event.system_output["output"]["status"] == "live_weather"
    assert weather_event.system_output["output"]["current_relative_humidity"] == 91
    assert weather_event.system_output["output"]["location_source"] == "browser"
    assert weather_event.system_output["input_summary"]["has_coordinates"] is True


def test_user_explicit_location_and_weather_override_browser_location(db_session, monkeypatch):
    def fake_weather(self, latitude, longitude):
        raise AssertionError("explicit user location should not call browser-coordinate weather")

    monkeypatch.setattr("app.tools.weather_tool.WeatherTool._fetch_open_meteo", fake_weather)

    def fake_location_language(self, message):
        from app.tools.location_tool import LocationLanguageObservation

        return LocationLanguageObservation(
            explicit_location="成都市",
            confidence="high",
            evidence=["用户明确说在成都市的大棚番茄。"],
        )

    monkeypatch.setattr(
        "app.tools.location_tool.LocationTool._observe_language_location",
        fake_location_language,
    )

    response = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="帮朋友问，在成都市的大棚番茄叶背有白色飞虫，最近高湿，结果期，距离采收大概 10 天。",
            affected_parts=["叶背"],
            days_to_harvest=10,
            latitude=39.9,
            longitude=116.4,
            location_label="浏览器定位",
            location_source="browser",
        )
    )

    assert response.advice is not None
    assert "成都市" in (response.advice.environment_confirmation or "")

    detail = CaseOrchestrator(db_session).cases.get_detail(response.case_id)
    location_event = next(
        event
        for event in detail.events
        if event.event_type == EventType.TOOL_CALLED and event.system_output["tool"] == "LocationTool"
    )
    assert location_event.system_output["output"]["location"] == "成都市"
    assert location_event.system_output["output"]["location_source"] == "user_explicit"
    weather = detail.structured_data["weather_observation"]
    assert weather["location"] == "成都市"
    assert weather["location_source"] == "user_explicit"
    assert weather["status"] == "user_weather"
    assert weather["requires_confirmation"] is False
    assert "高湿" in detail.recent_weather


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


def test_followup_improving_moves_to_improving(db_session):
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
            description="病斑没有增加，新叶正常，整体稳定。",
            has_new_spots=False,
            spots_expanded=False,
            spread_to_new_parts=False,
        ),
    )

    assert response.status == CaseStatus.IMPROVING
    assert response.trend is not None
    assert db_session.query(Reminder).filter_by(case_id=created.case_id, status="cancelled").count() == 1


def test_pending_followup_does_not_make_every_reply_a_followup(db_session):
    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="叶背有小白虫，碰一下有白色飞虫，结果期，距离采收大概 10 天。",
            affected_parts=["叶背"],
            days_to_harvest=10,
        )
    )

    response = CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        data=ReplyInput(message="听说这应该是白粉虱"),
    )

    assert response.response_type == "diagnosis_and_plan"
    assert response.status == CaseStatus.FOLLOWUP_PENDING

    detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert detail is not None
    event_types = [event.event_type for event in detail.events]
    assert EventType.FOLLOWUP_SUBMITTED not in event_types
    assert EventType.FOLLOWUP_COMPARED not in event_types


def test_more_pests_reply_is_followup_change_not_location(db_session, monkeypatch):
    def fake_observe(self, **kwargs):
        message = kwargs.get("message", "")
        if "更多的小虫" in message:
            return semantic_stub(
                user_intent="followup_report",
                is_followup_report=True,
                followup_trend="WORSENING",
                followup_evidence=["用户表达虫量比之前更多。"],
                symptoms=["虫量增多"],
            )
        return semantic_stub(
            affected_parts=["叶背"],
            symptoms=["白色小虫"],
            possible_categories=["虫害"],
            mentioned_problems=["白粉虱"],
            growth_stage="结果期",
            days_to_harvest=10,
        )

    monkeypatch.setattr("app.tools.semantic_observation_tool.SemanticObservationTool.observe", fake_observe)

    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="叶片上很多白色小虫，叶背也能看到，结果期，距离采收大概 10 天。",
            affected_parts=["叶背"],
            days_to_harvest=10,
        )
    )

    response = CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        data=ReplyInput(message="现在长了更多的小虫了"),
    )

    assert response.response_type == "followup_result"
    assert response.status == CaseStatus.ESCALATED
    assert response.trend is not None

    detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert detail is not None
    location_events = [
        event
        for event in detail.events
        if event.event_type == EventType.TOOL_CALLED and event.system_output["tool"] == "LocationTool"
    ]
    assert location_events[-1].system_output["output"]["location"] != "长了更多的小虫"
    assert location_events[-1].system_output["output"]["location_source"] != "user_explicit"
    event_types = [event.event_type for event in detail.events]
    assert EventType.FOLLOWUP_SUBMITTED in event_types
    assert EventType.FOLLOWUP_COMPARED in event_types


def test_mold_and_yellow_spots_expanding_is_llm_followup_worsening(db_session, monkeypatch):
    def fake_observe(self, **kwargs):
        message = kwargs.get("message", "")
        if "霉层增多" in message:
            return semantic_stub(
                user_intent="followup_report",
                is_followup_report=True,
                followup_trend="WORSENING",
                followup_evidence=["霉层增多", "黄斑扩大"],
                symptoms=["霉层增多", "黄斑扩大"],
                possible_categories=["病害"],
            )
        return semantic_stub(
            affected_parts=["叶片"],
            symptoms=["霉层", "黄斑"],
            possible_categories=["病害"],
            growth_stage="结果期",
            days_to_harvest=10,
        )

    monkeypatch.setattr("app.tools.semantic_observation_tool.SemanticObservationTool.observe", fake_observe)

    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            symptoms="叶片有霉层和黄斑，结果期，距离采收大概 10 天。",
            affected_parts=["叶片"],
            days_to_harvest=10,
        )
    )

    response = CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        data=ReplyInput(message="现在忽然霉层增多了，黄斑扩大了"),
    )

    assert response.response_type == "followup_result"
    assert response.status == CaseStatus.ESCALATED
    assert response.trend is not None
    detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    compared = next(event for event in detail.events if event.event_type == EventType.FOLLOWUP_COMPARED)
    assert compared.system_output["trend"] == "WORSENING"


def test_followup_no_new_pests_and_healthy_is_not_worsening(db_session, monkeypatch):
    def fake_observe(self, **kwargs):
        message = kwargs.get("message", "")
        if "没有再长" in message:
            return semantic_stub(
                user_intent="followup_report",
                is_followup_report=True,
                followup_trend="IMPROVING",
                followup_evidence=["用户表示虫子没有继续增加，植株看起来健康。"],
                symptoms=["虫量未增加", "长势健康"],
                possible_categories=["虫害"],
            )
        return semantic_stub(
            affected_parts=["叶背"],
            symptoms=["白色小虫"],
            possible_categories=["虫害"],
            mentioned_problems=["白粉虱"],
        )

    monkeypatch.setattr("app.tools.semantic_observation_tool.SemanticObservationTool.observe", fake_observe)

    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="叶背有很多白色小虫，一碰有白色飞虫，结果期，距离采收大概 10 天。",
            affected_parts=["叶背"],
            days_to_harvest=10,
        )
    )

    response = CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        data=ReplyInput(message="现在虫子没有再长了，看起来很健康"),
    )

    assert response.response_type == "followup_result"
    assert response.status == CaseStatus.IMPROVING
    assert response.trend is not None
    assert response.trend.value == "IMPROVING"

    detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    compared = next(event for event in detail.events if event.event_type == EventType.FOLLOWUP_COMPARED)
    assert compared.system_output["trend"] == "IMPROVING"


def test_vision_candidate_takes_priority_over_weak_text_match(db_session, monkeypatch):
    def fake_analyze(self, image_urls, context=""):
        return VisionObservation(
            model="test-vision",
            observed_parts=["叶背"],
            visual_symptoms=["叶片发黄"],
            possible_problems=["白粉虱"],
            suggested_questions=[],
            confidence="high",
            is_configured=True,
        )

    monkeypatch.setattr("app.tools.vision_tool.VisionTool.analyze", fake_analyze)

    response = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            symptoms="这个叶子发黄，结果期，距离采收大概 10 天，帮我看看图片。",
            image_urls=["data:image/png;base64,whitefly"],
        )
    )

    assert response.diagnosis is not None
    assert response.diagnosis.suspected_problem == "白粉虱"
    assert response.advice is not None
    assert "白粉虱" in response.advice.plain_summary


def test_user_correction_changes_diagnosis_without_followup_compare(db_session):
    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            symptoms="下部老叶有点发黄，结果期，距离采收大概 10 天。",
            affected_parts=["下部老叶"],
            days_to_harvest=10,
        )
    )

    response = CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(message="这应该是白粉虱吧，叶背有小白虫，一碰就有白色飞虫。"),
    )

    assert response.response_type == "diagnosis_and_plan"
    assert response.diagnosis is not None
    assert response.diagnosis.suspected_problem == "白粉虱"

    detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert detail is not None
    event_types = [event.event_type for event in detail.events]
    assert EventType.FOLLOWUP_SUBMITTED not in event_types
    assert EventType.FOLLOWUP_COMPARED not in event_types


def test_followup_context_does_not_make_chemical_questions_repeat_initial_answer(db_session):
    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="叶背有小白虫，一碰有白色飞虫，结果期，大概还有一周收获。",
            affected_parts=["叶背"],
            days_to_harvest=7,
        )
    )

    safety_response = CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(message="大概还有一周就收获了，不过我想问问能不能用药呢"),
    )

    assert safety_response.decision is not None
    assert safety_response.decision.user_intent == "chemical_safety_question"
    assert safety_response.diagnosis is not None
    assert safety_response.diagnosis.suspected_problem == "白粉虱"
    assert "关于能不能用药" in safety_response.message
    assert "不能给具体药名" not in safety_response.message
    assert safety_response.message.count("白粉虱") <= 1

    detail_response = CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(message="如果用药的话，建议用什么药呢"),
    )

    assert detail_response.decision is not None
    assert detail_response.decision.user_intent == "pesticide_detail_question"
    assert "具体用什么药" in detail_response.message
    assert "具体农药名称、剂量、兑水比例或施药频次" in detail_response.message
    assert detail_response.message.count("白粉虱") <= 1


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
    assert response.advice is not None
    assert "不提供具体药剂" in response.advice.chemical_advice
    assert "临近采收" in response.advice.harvest_safety
    assert any("采收" in warning for warning in response.safety.warnings)


def test_image_evidence_runs_vision_tool_observation(db_session):
    response = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="下部老叶有褐色斑点，现在结果期，距离采收大概 10 天。",
            image_urls=["data:image/png;base64,abc123"],
        )
    )

    detail = CaseOrchestrator(db_session).cases.get_detail(response.case_id)
    assert detail is not None
    assert detail.structured_data["image_evidence"] == ["data:image/png;base64,abc123"]
    assert detail.structured_data["image_analysis_status"] == "not_configured"
    assert "vision_observation" in detail.structured_data
    assert any(event.event_type == EventType.VISION_ANALYZED for event in detail.events)


def test_deepseek_vision_provider_reports_not_supported(db_session, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("VISION_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_TEXT_MODEL", "deepseek-v4-pro")
    get_settings.cache_clear()

    response = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="下部老叶有褐色斑点，现在结果期，距离采收大概 10 天。",
            image_urls=["data:image/png;base64,abc123"],
        )
    )

    detail = CaseOrchestrator(db_session).cases.get_detail(response.case_id)
    assert detail is not None
    assert detail.structured_data["image_analysis_status"] == "not_supported"
    observation = detail.structured_data["vision_observation"]
    assert observation["provider"] == "deepseek"
    assert "未提供图片输入" in observation["uncertainties"][0]


def test_configured_vision_observation_participates_in_decision_and_diagnosis(
    db_session, monkeypatch
):
    def fake_analyze(self, image_urls, context=""):
        return VisionObservation(
            model="test-vision",
            observed_parts=["叶背"],
            visual_symptoms=["叶背有小白虫", "可见白色飞虫"],
            possible_problems=["白粉虱"],
            growth_stage_hint="结果期",
            harvest_hint="未见成熟果，采收时间仍需用户确认",
            suggested_questions=["当前是结果期还是采收期？"],
            confidence="high",
            is_configured=True,
        )

    monkeypatch.setattr("app.tools.vision_tool.VisionTool.analyze", fake_analyze)

    response = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            symptoms="帮我看看这张图，结果期，距离采收大概 10 天。",
            image_urls=["data:image/png;base64,vision123"],
        )
    )

    assert response.status == CaseStatus.FOLLOWUP_PENDING
    assert response.response_type == "diagnosis_and_plan"
    assert response.diagnosis is not None
    assert response.diagnosis.suspected_problem == "白粉虱"
    assert any("视觉观察" in evidence for evidence in response.diagnosis.evidence)

    detail = CaseOrchestrator(db_session).cases.get_detail(response.case_id)
    assert detail is not None
    assert detail.structured_data["image_analysis_status"] == "analyzed"
    assert detail.structured_data["multimodal_observation"]["fused"]["affected_parts"] == ["叶背"]
    assert "叶背有小白虫" in detail.structured_data["multimodal_observation"]["fused"]["symptoms"]
    assert detail.growth_stage == "结果期"
    assert detail.structured_data["raw"]["harvest_hint"] == "未见成熟果，采收时间仍需用户确认"


def test_agent_decision_event_contains_execution_trace(db_session):
    response = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(symptoms="番茄叶片有褐色斑点，帮我判断一下。")
    )

    detail = CaseOrchestrator(db_session).cases.get_detail(response.case_id)
    assert detail is not None
    decision_event = next(
        event for event in reversed(detail.events) if event.event_type == EventType.AGENT_DECISION
    )
    trace = decision_event.system_output["trace"]

    assert set(trace) == {"observe", "decide", "act", "guard", "memory"}
    assert trace["observe"]["latest_user_message"] == "番茄叶片有褐色斑点，帮我判断一下。"
    assert trace["decide"]["next_action"] == response.decision.next_action
    assert trace["decide"]["user_intent"] == response.decision.user_intent
    assert trace["decide"]["response_focus"] == response.decision.response_focus
    assert trace["act"]["planned_tools"]
    assert trace["guard"]["guardrails"]
    assert EventType.AGENT_DECISION.value in trace["memory"]["will_write_events"]
