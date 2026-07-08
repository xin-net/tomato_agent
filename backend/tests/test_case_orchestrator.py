from app.domain.enums import AgentAction, CaseStatus, EventType, FollowupTrend
from app.domain.models import Reminder
from app.schemas.agent import AgentDecision
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
    assert "SemanticObservationTool" in tool_events
    assert "KnowledgeSearchTool" not in tool_events
    assert "DiagnosisTool" not in tool_events
    assert "FollowupCompareTool" not in tool_events
    assert "SymptomExtractionTool" not in tool_events
    assert "SafetyChecker" in tool_events
    assert "PlanTool" not in tool_events
    assert "CalendarReminderTool" in tool_events
    assert "ResponseComposer" in tool_events
    tool_outputs = {
        event.system_output["tool"]: event.system_output["output"]
        for event in detail.events
        if event.event_type == EventType.TOOL_CALLED
    }
    assert tool_outputs["DateTool"]["today"]
    assert tool_outputs["WeatherTool"]["status"] == "live_weather"
    assert tool_outputs["WeatherTool"]["provider"] == "amap"
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
    assert response.plan is not None
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
    assert weather["status"] == "live_weather"
    assert weather["requires_confirmation"] is False
    assert detail.recent_weather


def test_location_is_resolved_once_and_reused_for_later_weather(db_session, monkeypatch):
    location_calls = []

    def fake_location_language(self, message):
        from app.tools.location_tool import LocationLanguageObservation

        location_calls.append(message)
        return LocationLanguageObservation(
            explicit_location="成都市成华区" if "成华区" in message else None,
            confidence="high" if "成华区" in message else "low",
            evidence=["用户明确说地点在成都成华区。"] if "成华区" in message else [],
        )

    def fake_geocode(self, address):
        return {
            "formatted_address": address,
            "adcode": "510108",
            "province": "四川省",
            "city": "成都市",
            "district": "成华区",
            "latitude": 30.67,
            "longitude": 104.10,
            "uncertainties": [],
        }

    def fake_weather(self, key, adcode):
        return {
            "weather": "阴",
            "temperature": "27",
            "winddirection": "东北",
            "windpower": "≤3",
            "humidity": "80",
            "reporttime": "2026-07-08 10:00:00",
        }

    monkeypatch.setattr("app.tools.location_tool.LocationTool._observe_language_location", fake_location_language)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._geocode", fake_geocode)
    monkeypatch.setattr("app.tools.weather_tool.WeatherTool._fetch_amap_weather", fake_weather)

    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="地点在成都成华区，叶背有小白虫，一碰有白色飞虫，结果期，距离采收大概 10 天。",
            affected_parts=["叶背"],
            days_to_harvest=10,
            latitude=30.64,
            longitude=104.04,
            location_label="武侯区附近",
            location_source="browser",
        )
    )

    CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(
            message="现在虫量差不多，继续观察一下",
            latitude=30.64,
            longitude=104.04,
            location_label="武侯区附近",
            location_source="browser",
        ),
    )

    detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert detail.structured_data["location_observation"]["location"] == "成都市成华区"
    assert detail.structured_data["location_observation"]["adcode"] == "510108"
    assert detail.structured_data["weather_observation"]["location"] == "成都市成华区"
    assert detail.structured_data["weather_observation"]["adcode"] == "510108"
    assert location_calls == [
        "地点在成都成华区，叶背有小白虫，一碰有白色飞虫，结果期，距离采收大概 10 天。"
    ]

    tool_events = [
        event
        for event in detail.events
        if event.event_type == EventType.TOOL_CALLED and event.system_output["tool"] == "LocationTool"
    ]
    assert len(tool_events) == 1


def test_unconfirmed_initial_location_can_be_replaced_once_then_locked(db_session, monkeypatch):
    from app.tools.semantic_observation_tool import SemanticObservation

    location_calls = []
    weather_adcodes = []

    def fake_semantic_observe(
        self,
        message,
        case_memory=None,
        active_followup=None,
        date_observation=None,
        history_summary=None,
    ):
        corrections = {}
        if "成华区" in message:
            corrections["location_text"] = "成都市成华区"
        return SemanticObservation(
            status="analyzed",
            is_configured=True,
            model="test-semantic",
            user_intent="location_update" if corrections else "initial_diagnosis",
            corrections=corrections,
            confidence="high",
        )

    def fake_location_language(self, message):
        from app.tools.location_tool import LocationLanguageObservation

        location_calls.append(message)
        return LocationLanguageObservation(
            explicit_location="成都市成华区" if "成华区" in message else None,
            confidence="high" if "成华区" in message else "low",
            evidence=["用户明确纠正种植地点为成华区。"] if "成华区" in message else [],
        )

    def fake_reverse_geocode(self, latitude, longitude):
        return {
            "formatted_address": "成都市武侯区",
            "adcode": "510107",
            "province": "四川省",
            "city": "成都市",
            "district": "武侯区",
            "uncertainties": [],
        }

    def fake_geocode(self, address):
        return {
            "formatted_address": address,
            "adcode": "510108",
            "province": "四川省",
            "city": "成都市",
            "district": "成华区",
            "latitude": 30.67,
            "longitude": 104.10,
            "uncertainties": [],
        }

    def fake_weather(self, key, adcode):
        weather_adcodes.append(adcode)
        return {
            "weather": "阴",
            "temperature": "27",
            "winddirection": "东北",
            "windpower": "≤3",
            "humidity": "80",
            "reporttime": "2026-07-08 10:00:00",
        }

    monkeypatch.setattr("app.tools.semantic_observation_tool.SemanticObservationTool.observe", fake_semantic_observe)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._observe_language_location", fake_location_language)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._reverse_geocode", fake_reverse_geocode)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._geocode", fake_geocode)
    monkeypatch.setattr("app.tools.weather_tool.WeatherTool._fetch_amap_weather", fake_weather)

    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            growth_stage="结果期",
            symptoms="叶背有很多白色小虫。",
            affected_parts=["叶背"],
            latitude=30.64,
            longitude=104.04,
            location_label="武侯区附近",
            location_source="browser",
        )
    )

    first_detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert first_detail.structured_data["location_observation"]["location"] == "成都市武侯区"
    assert first_detail.structured_data["location_observation"]["confirmation_needed"] is True
    assert first_detail.structured_data["location_observation"]["confirmation_prompt_count"] == 1

    CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(message="实际种植地点是成都市成华区。"),
    )
    second_detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert second_detail.structured_data["location_observation"]["location"] == "成都市成华区"
    assert second_detail.structured_data["location_observation"]["adcode"] == "510108"
    assert second_detail.structured_data["location_observation"]["confirmation_needed"] is True
    assert second_detail.structured_data["location_observation"]["confirmation_prompt_count"] == 2

    CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(
            message="现在虫量没有继续增加。",
            latitude=30.64,
            longitude=104.04,
            location_label="武侯区附近",
            location_source="browser",
        ),
    )
    final_detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert final_detail.structured_data["location_observation"]["location"] == "成都市成华区"
    assert final_detail.structured_data["location_observation"]["location_source"] == "user_explicit"
    assert final_detail.structured_data["location_observation"]["confirmation_needed"] is False
    assert final_detail.structured_data["location_observation"]["confirmation_prompt_count"] == 2
    assert final_detail.structured_data["weather_observation"]["location"] == "成都市成华区"
    assert final_detail.structured_data["weather_observation"]["adcode"] == "510108"
    assert weather_adcodes == ["510107", "510108", "510108"]
    assert len(location_calls) == 2


def test_location_confirmation_reply_uses_location_tool_when_semantics_misses_update(db_session, monkeypatch):
    from app.tools.semantic_observation_tool import SemanticObservation

    location_calls = []
    weather_adcodes = []

    def fake_semantic_observe(
        self,
        message,
        case_memory=None,
        active_followup=None,
        date_observation=None,
        history_summary=None,
    ):
        return SemanticObservation(
            status="analyzed",
            is_configured=True,
            model="test-semantic",
            user_intent="initial_diagnosis",
            corrections={},
            confidence="high",
        )

    def fake_location_language(self, message):
        from app.tools.location_tool import LocationLanguageObservation

        location_calls.append(message)
        return LocationLanguageObservation(
            explicit_location="天津市" if "天津" in message else None,
            confidence="high" if "天津" in message else "low",
            evidence=["用户在地点确认回复中明确说实际地点是天津市。"] if "天津" in message else [],
        )

    def fake_reverse_geocode(self, latitude, longitude):
        return {
            "formatted_address": "成都市武侯区",
            "adcode": "510107",
            "province": "四川省",
            "city": "成都市",
            "district": "武侯区",
            "uncertainties": [],
        }

    def fake_geocode(self, address):
        return {
            "formatted_address": address,
            "adcode": "120100",
            "province": "天津市",
            "city": "天津市",
            "district": None,
            "latitude": 39.08,
            "longitude": 117.20,
            "uncertainties": [],
        }

    def fake_weather(self, key, adcode):
        weather_adcodes.append(adcode)
        return {
            "weather": "多云",
            "temperature": "29",
            "winddirection": "东",
            "windpower": "≤3",
            "humidity": "65",
            "reporttime": "2026-07-08 11:00:00",
        }

    monkeypatch.setattr("app.tools.semantic_observation_tool.SemanticObservationTool.observe", fake_semantic_observe)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._observe_language_location", fake_location_language)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._reverse_geocode", fake_reverse_geocode)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._geocode", fake_geocode)
    monkeypatch.setattr("app.tools.weather_tool.WeatherTool._fetch_amap_weather", fake_weather)

    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            symptoms="叶背有很多白色小虫。",
            affected_parts=["叶背"],
            latitude=30.64,
            longitude=104.04,
            location_label="武侯区附近",
            location_source="browser",
        )
    )

    CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(message="实际种植地在天津市。"),
    )
    after_update = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert after_update.structured_data["location_observation"]["location"] == "天津市"
    assert after_update.structured_data["location_observation"]["adcode"] == "120100"
    assert after_update.structured_data["location_observation"]["confirmation_needed"] is True

    CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(
            message="确定了，就是天津市。",
            latitude=30.64,
            longitude=104.04,
            location_label="武侯区附近",
            location_source="browser",
        ),
    )
    final_detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert final_detail.structured_data["location_observation"]["location"] == "天津市"
    assert final_detail.structured_data["location_observation"]["confirmation_needed"] is False
    assert final_detail.structured_data["weather_observation"]["location"] == "天津市"
    assert final_detail.structured_data["weather_observation"]["adcode"] == "120100"
    assert weather_adcodes == ["510107", "120100", "120100"]
    assert location_calls == ["叶背有很多白色小虫。", "实际种植地在天津市。"]


def test_location_tool_accepts_llm_numeric_confidence_and_string_evidence(db_session, monkeypatch):
    from app.tools.llm_adapter import LLMResult
    from app.tools.semantic_observation_tool import SemanticObservation

    weather_adcodes = []

    def fake_semantic_observe(
        self,
        message,
        case_memory=None,
        active_followup=None,
        date_observation=None,
        history_summary=None,
    ):
        return SemanticObservation(
            status="analyzed",
            is_configured=True,
            model="test-semantic",
            user_intent="initial_diagnosis",
            corrections={},
            confidence="high",
        )

    def fake_llm_complete(self, prompt, model=None):
        if "天津" in prompt:
            content = '{"explicit_location":"天津市","confidence":0.99,"evidence":"用户明确说实际种植地在天津市。","uncertainties":[]}'
        else:
            content = '{"explicit_location":null,"confidence":0.2,"evidence":"用户没有提供实际种植地点。","uncertainties":[]}'
        return LLMResult(provider="openai", model="test", content=content, is_configured=True)

    def fake_ip_location(self):
        return {
            "location": "四川省 成都市",
            "province": "四川省",
            "city": "成都市",
            "adcode": "510100",
            "uncertainties": [],
        }

    def fake_geocode(self, address):
        return {
            "formatted_address": address,
            "adcode": "120100",
            "province": "天津市",
            "city": "天津市",
            "district": None,
            "latitude": 39.08,
            "longitude": 117.20,
            "uncertainties": [],
        }

    def fake_weather(self, key, adcode):
        weather_adcodes.append(adcode)
        return {
            "weather": "多云",
            "temperature": "29",
            "winddirection": "东",
            "windpower": "≤3",
            "humidity": "65",
            "reporttime": "2026-07-08 11:00:00",
        }

    monkeypatch.setattr("app.tools.semantic_observation_tool.SemanticObservationTool.observe", fake_semantic_observe)
    monkeypatch.setattr("app.tools.llm_adapter.OpenAIAdapter.complete", fake_llm_complete)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._ip_location", fake_ip_location)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._geocode", fake_geocode)
    monkeypatch.setattr("app.tools.weather_tool.WeatherTool._fetch_amap_weather", fake_weather)

    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            symptoms="叶背有很多白色小虫。",
            affected_parts=["叶背"],
        )
    )

    CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(message="实际种植地在天津市。"),
    )

    detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    location = detail.structured_data["location_observation"]
    assert location["location"] == "天津市"
    assert location["language_confidence"] == "high"
    assert location["evidence"] == ["用户明确说实际种植地在天津市。"]
    assert detail.structured_data["weather_observation"]["adcode"] == "120100"
    assert weather_adcodes == ["510100", "120100"]


def test_automatic_location_memory_does_not_become_user_confirmed(db_session, monkeypatch):
    from app.tools.llm_adapter import LLMResult
    from app.tools.semantic_observation_tool import SemanticObservation

    def fake_semantic_observe(
        self,
        message,
        case_memory=None,
        active_followup=None,
        date_observation=None,
        history_summary=None,
    ):
        return SemanticObservation(
            status="analyzed",
            is_configured=True,
            model="test-semantic",
            user_intent="initial_diagnosis",
            corrections={},
            confidence="high",
        )

    def fake_llm_complete(self, prompt, model=None):
        explicit = "天津市" if "天津" in prompt else None
        content = (
            '{"explicit_location":"天津市","confidence":0.99,"evidence":"用户明确说实际种植地在天津市。","uncertainties":[]}'
            if explicit
            else '{"explicit_location":null,"confidence":0.2,"evidence":"没有提供地点。","uncertainties":[]}'
        )
        return LLMResult(provider="openai", model="test", content=content, is_configured=True)

    def fake_ip_location(self):
        return {
            "location": "四川省 成都市",
            "province": "四川省",
            "city": "成都市",
            "adcode": "510100",
            "uncertainties": [],
        }

    def fake_geocode(self, address):
        return {
            "formatted_address": address,
            "adcode": "120100",
            "province": "天津市",
            "city": "天津市",
            "district": None,
            "latitude": 39.08,
            "longitude": 117.20,
            "uncertainties": [],
        }

    monkeypatch.setattr("app.tools.semantic_observation_tool.SemanticObservationTool.observe", fake_semantic_observe)
    monkeypatch.setattr("app.tools.llm_adapter.OpenAIAdapter.complete", fake_llm_complete)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._ip_location", fake_ip_location)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._geocode", fake_geocode)

    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(symptoms="叶背有很多白色小虫。")
    )
    CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(message="先不管地点，虫子还在。"),
    )
    after_memory_reuse = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert after_memory_reuse.structured_data["location_observation"]["location_source"] == "amap_ip"

    CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(message="实际种植地在天津市。"),
    )
    final_detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert final_detail.structured_data["location_observation"]["location"] == "天津市"
    assert final_detail.structured_data["location_observation"]["location_source"] == "user_explicit"


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


def test_followup_compare_uses_decision_trend_when_semantic_trend_is_missing(db_session, monkeypatch):
    def fake_observe(self, **kwargs):
        message = kwargs.get("message", "")
        if "虫量忽然增加" in message:
            return semantic_stub(
                user_intent="followup_report",
                is_followup_report=True,
                followup_trend=None,
                followup_evidence=[],
                symptoms=["虫量增加"],
                possible_categories=["虫害"],
            )
        return semantic_stub(
            affected_parts=["叶背"],
            symptoms=["白色小虫"],
            possible_categories=["虫害"],
            mentioned_problems=["白粉虱"],
            growth_stage="结果期",
            days_to_harvest=10,
        )

    def fake_decide(self, context):
        semantic = context.semantic_observation or {}
        if semantic.get("is_followup_report"):
            return AgentDecision(
                next_action=AgentAction.COMPARE_FOLLOWUP,
                requested_state=CaseStatus.FOLLOWUP_REVIEW,
                reason="用户描述虫量突然增加，按复查加重处理。",
                confidence="high",
                decision_source="llm:test",
                observations_used=["虫量忽然增加"],
                tool_plan=["SemanticObservationTool", "StateMachine", "CalendarReminderTool", "EventMemory"],
                user_intent="followup_report",
                response_focus=["判断加重趋势", "调整处置和复查"],
                followup_trend=FollowupTrend.WORSENING,
                followup_evidence=["用户说虫量忽然增加"],
            )
        return AgentDecision(
            next_action=AgentAction.DIAGNOSE_AND_PLAN,
            requested_state=CaseStatus.FOLLOWUP_PENDING,
            reason="初次判断并安排复查。",
            confidence="high",
            decision_source="llm:test",
            observations_used=["叶背白色小虫"],
            tool_plan=["SafetyChecker", "CalendarReminderTool", "ResponseComposer"],
            user_intent="initial_diagnosis",
            response_focus=["给出处置方向", "安排复查"],
            information_sufficient=True,
            problem_category="虫害",
            likely_causes=["白粉虱"],
            diagnosis_evidence=["叶背白色小虫"],
            confidence_label="较高",
            severity_label="轻到中等",
            immediate_actions=["先检查叶背并清理明显虫源"],
            observation_points=["虫量是否继续增加"],
            escalation_conditions=["虫量快速增加"],
            followup_after_days=3,
            plain_summary="当前更像白粉虱，先处理并复查。",
        )

    monkeypatch.setattr("app.tools.semantic_observation_tool.SemanticObservationTool.observe", fake_observe)
    monkeypatch.setattr("app.agents.decision_engine.AgentDecisionEngine.decide", fake_decide)

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
        data=ReplyInput(message="糟糕，虫量忽然增加了"),
    )

    assert response.response_type == "followup_result"
    assert response.status == CaseStatus.ESCALATED
    assert response.trend == FollowupTrend.WORSENING

    detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    compared = next(event for event in detail.events if event.event_type == EventType.FOLLOWUP_COMPARED)
    assert compared.system_output["trend"] == "WORSENING"
    assert compared.system_output["evidence"] == ["用户说虫量忽然增加"]


def test_llm_harvest_correction_string_days_is_normalized(db_session, monkeypatch):
    def fake_observe(self, **kwargs):
        message = kwargs.get("message", "")
        if "离采收还有10天" in message:
            return semantic_stub(
                user_intent="followup_report",
                is_followup_report=True,
                followup_trend="WORSENING",
                followup_evidence=["用户描述斑点变大变黄。"],
                affected_parts=["叶片"],
                symptoms=["斑点变大", "斑点变黄"],
                possible_categories=["病害"],
                severity="加重",
                corrections={
                    "growth_stage": "结果期",
                    "days_to_harvest": "10天",
                    "recent_fertilizer_use": "近期没有施肥用药",
                    "recent_pesticide_use": "近期没有施肥用药",
                },
            )
        return semantic_stub(
            affected_parts=["叶片"],
            symptoms=["斑点"],
            possible_categories=["病害"],
            growth_stage="结果期",
            days_to_harvest=10,
        )

    monkeypatch.setattr("app.tools.semantic_observation_tool.SemanticObservationTool.observe", fake_observe)

    created = CaseOrchestrator(db_session).create_case(
        CreateCaseInput(
            symptoms="叶片有斑点，结果期，距离采收大概 10 天。",
            affected_parts=["叶片"],
            days_to_harvest=10,
        )
    )

    response = CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        data=ReplyInput(message="现在已经是结果期，离采收还有10天，近期也没有施肥用药。现在斑点已经变大变黄了"),
    )

    assert response.status in {CaseStatus.ESCALATED, CaseStatus.FOLLOWUP_REVIEW}
    detail = CaseOrchestrator(db_session).cases.get_detail(created.case_id)
    assert detail.days_to_harvest == 10


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
    assert safety_response.message
    assert safety_response.message.count("白粉虱") <= 1

    detail_response = CaseOrchestrator(db_session).reply_to_case(
        created.case_id,
        ReplyInput(message="如果用药的话，建议用什么药呢"),
    )

    assert detail_response.decision is not None
    assert detail_response.decision.user_intent == "pesticide_detail_question"
    assert detail_response.message
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
