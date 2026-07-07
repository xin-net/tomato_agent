import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.config import get_settings
from app.domain.enums import AgentAction, CaseStatus
from app.schemas.agent import AgentDecision
from app.tools.semantic_observation_tool import SemanticObservation


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def disable_external_api_keys(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("VISION_PROVIDER", "openai")
    monkeypatch.setenv("AGENT_DECISION_MODE", "llm")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("WEATHER_API_KEY", "")
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-amap-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def mock_response_composer(monkeypatch):
    def fake_compose(self, response):
        return response.message or (response.advice.plain_summary if response.advice else "测试回复")

    monkeypatch.setattr("app.tools.response_composer.ResponseComposer.compose", fake_compose)


@pytest.fixture(autouse=True)
def mock_external_tools(monkeypatch):
    def fake_geocode(self, address):
        return {
            "formatted_address": address,
            "adcode": "510100",
            "province": "四川省",
            "city": "成都市",
            "district": None,
            "latitude": 30.67,
            "longitude": 104.06,
            "uncertainties": [],
        }

    def fake_reverse_geocode(self, latitude, longitude):
        return {
            "formatted_address": "成都附近",
            "adcode": None,
            "province": "四川省",
            "city": "成都市",
            "district": None,
            "uncertainties": [],
        }

    def fake_ip_location(self):
        return {
            "location": "四川省 成都市",
            "province": "四川省",
            "city": "成都市",
            "adcode": "510100",
            "uncertainties": [],
        }

    def fake_amap_weather(self, key, adcode):
        return {
            "weather": "阴",
            "temperature": "26",
            "winddirection": "东北",
            "windpower": "≤3",
            "humidity": "82",
            "reporttime": "2026-07-07 10:00:00",
        }

    monkeypatch.setattr("app.tools.location_tool.LocationTool._geocode", fake_geocode)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._reverse_geocode", fake_reverse_geocode)
    monkeypatch.setattr("app.tools.location_tool.LocationTool._ip_location", fake_ip_location)
    monkeypatch.setattr("app.tools.weather_tool.WeatherTool._fetch_amap_weather", fake_amap_weather)


@pytest.fixture(autouse=True)
def mock_llm_semantics_and_decisions(monkeypatch, request):
    if request.node.fspath.basename == "test_agent_decision_engine.py":
        return

    def fake_semantic_observe(
        self,
        message,
        case_memory=None,
        active_followup=None,
        date_observation=None,
        history_summary=None,
    ):
        mentioned = []
        symptoms = []
        categories = []
        affected_parts = []
        corrections = {}
        user_intent = "initial_diagnosis"
        is_followup = False
        trend = None
        evidence = []
        severity = None

        if "白粉虱" in message or "小白虫" in message or "飞虫" in message:
            mentioned.append("白粉虱")
            symptoms.extend(["白色小虫", "白色飞虫"])
            categories.append("虫害")
        if "叶背" in message:
            affected_parts.append("叶背")
        if "叶片" in message or "叶子" in message:
            affected_parts.append("叶片")
        if "斑" in message or "褐色" in message or "霉层" in message:
            symptoms.append("斑点或霉层")
            categories.append("病害")
        if "结果期" in message:
            corrections["growth_stage"] = "结果期"
        if "10 天" in message or "10天" in message:
            corrections["days_to_harvest"] = 10
        elif "一周" in message or "7 天" in message or "7天" in message:
            corrections["days_to_harvest"] = 7
        elif "4 天" in message or "4天" in message:
            corrections["days_to_harvest"] = 4
        if "连续阴雨" in message:
            corrections["recent_weather"] = "连续阴雨"
        elif "高湿" in message:
            corrections["recent_weather"] = "高湿"
        if "没有施肥用药" in message or "没有施肥" in message or "没有用药" in message:
            corrections["recent_fertilizer_use"] = "近期没有施肥用药"
            corrections["recent_pesticide_use"] = "近期没有施肥用药"
        if "能不能用药" in message:
            user_intent = "chemical_safety_question"
        if "用什么药" in message:
            user_intent = "pesticide_detail_question"
        if active_followup and any(text in message for text in ["变多", "更多", "扩大", "增多", "上部叶片也开始", "变大变黄"]):
            user_intent = "followup_report"
            is_followup = True
            trend = "WORSENING"
            evidence = [message]
            severity = "快速扩展"
        if active_followup and any(text in message for text in ["没有增加", "没有再长", "稳定", "健康"]):
            user_intent = "followup_report"
            is_followup = True
            trend = "IMPROVING"
            evidence = [message]

        return SemanticObservation(
            status="analyzed",
            is_configured=True,
            model="test-semantic",
            user_intent=user_intent,
            is_followup_report=is_followup,
            followup_trend=trend,
            followup_evidence=evidence,
            affected_parts=affected_parts,
            symptoms=symptoms,
            possible_categories=list(dict.fromkeys(categories)),
            mentioned_problems=mentioned,
            severity=severity,
            corrections=corrections,
            confidence="high",
        )

    def fake_decide(self, context):
        semantic = context.semantic_observation or {}
        raw = context.structured_symptoms.raw or {}
        vision = context.vision_observation or {}
        message = context.latest_user_message

        if semantic.get("is_followup_report"):
            return AgentDecision(
                next_action=AgentAction.COMPARE_FOLLOWUP,
                requested_state=CaseStatus.FOLLOWUP_REVIEW,
                reason="语义观察显示本轮是复查变化描述。",
                confidence="high",
                decision_source="llm:test",
                observations_used=semantic.get("followup_evidence", []) or [message],
                tool_plan=["SemanticObservationTool", "DateTool", "StateMachine", "CalendarReminderTool", "EventMemory"],
                user_intent=semantic.get("user_intent", "followup_report"),
                response_focus=["判断变化趋势", "调整处置和复查"],
                information_sufficient=True,
                problem_category=(semantic.get("possible_categories") or [None])[0],
                likely_causes=semantic.get("mentioned_problems", []),
                diagnosis_evidence=semantic.get("followup_evidence", []),
                confidence_label="较高",
                severity_label=semantic.get("severity"),
                guardrails=["动作必须来自 AgentAction 白名单"],
            )

        if "怎么办" in message and not raw.get("growth_stage") and raw.get("days_to_harvest") is None:
            return AgentDecision(
                next_action=AgentAction.ASK_MORE_INFO,
                requested_state=CaseStatus.NEED_MORE_INFO,
                reason="关键信息不足，先追问。",
                confidence="medium",
                questions=["主要发生在叶背、叶面还是果实？", "现在是苗期、开花期还是结果期？", "距离采收大概还有几天？"],
                decision_source="llm:test",
                observations_used=["用户描述较少"],
                tool_plan=["Questions", "StateMachine", "EventMemory"],
                user_intent="initial_diagnosis",
                response_focus=["补齐关键信息"],
                information_sufficient=False,
                guardrails=["动作必须来自 AgentAction 白名单"],
            )

        vision_problem = (vision.get("possible_problems") or [None])[0]
        mentioned = (raw.get("mentioned_problems") or semantic.get("mentioned_problems") or [])
        if vision_problem:
            problem = vision_problem
        elif "白粉虱" in mentioned or any("白粉虱" in str(item) for item in mentioned):
            problem = "白粉虱"
        elif any(text in message for text in ["小白虫", "飞虫", "叶背"]):
            problem = "白粉虱"
        elif any(text in message for text in ["褐色", "一圈一圈", "斑"]):
            problem = "番茄早疫病"
        else:
            problem = "番茄异常"
        category = "虫害" if problem == "白粉虱" else "病害" if "病" in problem else "生理性或环境问题"
        user_intent = semantic.get("user_intent") or "initial_diagnosis"
        if "能不能用药" in message:
            user_intent = "chemical_safety_question"
        if "用什么药" in message:
            user_intent = "pesticide_detail_question"

        return AgentDecision(
            next_action=AgentAction.DIAGNOSE_AND_PLAN,
            requested_state=CaseStatus.FOLLOWUP_PENDING,
            reason="信息足以形成保守处置和复查计划。",
            confidence="high",
            decision_source="llm:test",
            observations_used=["用户文字", "工具观察", "病例记忆"],
            tool_plan=["SafetyChecker", "CalendarReminderTool", "ResponseComposer"],
            user_intent=user_intent,
            response_focus=["回答本轮问题", "给出处置方向", "安排复查"],
            information_sufficient=True,
            problem_category=category,
            likely_causes=[problem],
            diagnosis_evidence=[
                f"当前观察更支持{problem}",
                *([f"视觉观察：{item}" for item in vision.get("visual_symptoms", [])]),
            ],
            confidence_label="较高",
            severity_label="轻到中等",
            immediate_actions=["先清理明显受害叶片或虫源", "改善通风和叶背检查", "暂停自行混用药或加肥"],
            observation_points=["是否继续增多", "是否扩散到新叶或果实", "处理后 2-3 天是否稳定"],
            escalation_conditions=["数量快速增加", "扩散到多株或果实", "叶片明显萎蔫或坏死"],
            followup_after_days=3,
            chemical_safety_note="涉及用药时需核对当地登记标签和采前安全间隔期。",
            harvest_safety_note="临近采收时优先非化学处理，不给具体用药处方。",
            plain_summary=f"当前更像{problem}，先按保守方式处理并短期复查。",
            guardrails=["动作必须来自 AgentAction 白名单", "处置建议必须经过 SafetyChecker"],
        )

    monkeypatch.setattr("app.tools.semantic_observation_tool.SemanticObservationTool.observe", fake_semantic_observe)
    monkeypatch.setattr("app.agents.decision_engine.AgentDecisionEngine.decide", fake_decide)
