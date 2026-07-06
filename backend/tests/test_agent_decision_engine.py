import pytest

from app.agents.decision_engine import AgentDecisionEngine, AgentDecisionError
from app.core.config import get_settings
from app.domain.enums import AgentAction, CaseStatus
from app.schemas.agent import AgentDecisionContext, StructuredSymptoms
from app.tools.llm_adapter import LLMResult


class FakeLLM:
    def __init__(self, result: LLMResult):
        self.result = result
        self.prompts: list[str] = []

    def complete(self, prompt: str, model: str | None = None) -> LLMResult:
        self.prompts.append(prompt)
        return self.result


def _context() -> AgentDecisionContext:
    return AgentDecisionContext(
        case_status=CaseStatus.NEW,
        latest_user_message="下部老叶有褐色同心轮纹斑点，结果期，距离采收约 10 天。",
        structured_symptoms=StructuredSymptoms(
            crop="番茄",
            affected_parts=["下部老叶"],
            symptoms=["褐色同心轮纹斑点"],
            possible_categories=["病害"],
            missing_fields=[],
            raw={
                "growth_stage": "结果期",
                "days_to_harvest": 10,
                "recent_pesticide_use": "未用药",
            },
        ),
        available_actions=list(AgentAction),
    )


def test_llm_decision_payload_is_used_when_valid(monkeypatch):
    monkeypatch.setenv("AGENT_DECISION_MODE", "llm")
    get_settings.cache_clear()
    llm = FakeLLM(
        LLMResult(
            provider="openai",
            model="test-model",
            is_configured=True,
            content=(
                '{"next_action":"ASK_MORE_INFO","reason":"还缺少近期天气信息，先追问。",'
                '"confidence":"high","questions":["最近三天是否连续阴雨或湿度较高？"],'
                '"observations_used":["下部老叶","同心轮纹"],'
                '"tool_plan":["Questions","StateMachine","EventMemory"]}'
            ),
        )
    )

    decision = AgentDecisionEngine(llm=llm).decide(_context())

    assert decision.next_action == AgentAction.ASK_MORE_INFO
    assert decision.requested_state == CaseStatus.NEED_MORE_INFO
    assert decision.decision_source == "llm:openai:test-model"
    assert decision.questions == ["最近三天是否连续阴雨或湿度较高？"]
    assert decision.tool_plan == ["Questions", "StateMachine", "EventMemory"]
    assert llm.prompts


def test_llm_decision_raises_when_llm_is_unconfigured(monkeypatch):
    monkeypatch.setenv("AGENT_DECISION_MODE", "llm")
    get_settings.cache_clear()
    llm = FakeLLM(
        LLMResult(
            provider="openai",
            model="test-model",
            is_configured=False,
            content="openai API key is not configured.",
        )
    )

    with pytest.raises(AgentDecisionError, match="模型不可用"):
        AgentDecisionEngine(llm=llm).decide(_context())


def test_llm_decision_raises_when_action_is_unavailable(monkeypatch):
    monkeypatch.setenv("AGENT_DECISION_MODE", "llm")
    get_settings.cache_clear()
    context = _context()
    context.available_actions = [AgentAction.ASK_MORE_INFO]
    llm = FakeLLM(
        LLMResult(
            provider="openai",
            model="test-model",
            is_configured=True,
            content='{"next_action":"DIAGNOSE_AND_PLAN","reason":"直接诊断","confidence":"high"}',
        )
    )

    with pytest.raises(AgentDecisionError, match="不可用动作"):
        AgentDecisionEngine(llm=llm).decide(context)
