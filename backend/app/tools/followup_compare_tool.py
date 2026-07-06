from app.domain.enums import FollowupTrend
from app.schemas.cases import FollowupInput
from app.tools.llm_adapter import OpenAIAdapter
from app.tools.semantic_observation_tool import SemanticObservationTool


class FollowupCompareTool:
    def __init__(self, llm: OpenAIAdapter | None = None):
        self.semantic_tool = SemanticObservationTool(llm)

    def compare(self, data: FollowupInput) -> tuple[FollowupTrend, list[str]]:
        observation = self.semantic_tool.observe(
            message=data.description,
            active_followup={"present": True},
        )
        if observation.is_configured and observation.followup_trend:
            evidence = observation.followup_evidence or observation.uncertainties
            return observation.followup_trend, evidence or ["大模型已判断本次复查趋势。"]
        return self._fallback_compare(data, observation.uncertainties)

    def _fallback_compare(
        self,
        data: FollowupInput,
        uncertainties: list[str] | None = None,
    ) -> tuple[FollowupTrend, list[str]]:
        evidence: list[str] = []
        if uncertainties:
            evidence.extend(uncertainties)
        improving_text = any(
            word in data.description
            for word in ["没有新的", "没有增加", "无新增", "未新增", "稳定", "好多了", "好转", "少了", "减少"]
        )
        worsening_signals = [
            data.has_new_spots is True,
            data.spots_expanded is True,
            data.spread_to_new_parts is True,
            data.fruit_affected is True,
            (not improving_text)
            and any(word in data.description for word in ["变多", "更多", "增加", "长了", "扩散", "上部", "更严重", "果实"]),
        ]
        improving_signals = [
            improving_text,
            data.has_new_spots is False,
            data.spots_expanded is False,
            data.spread_to_new_parts is False,
        ]

        if any(worsening_signals):
            evidence.append("复查描述出现新增、扩大、扩展到新部位或果实受害等恶化信号。")
            return FollowupTrend.WORSENING, evidence

        if sum(1 for signal in improving_signals if signal) >= 2:
            evidence.append("复查描述显示无新增或症状稳定。")
            return FollowupTrend.IMPROVING, evidence

        if len(data.description.strip()) < 8:
            evidence.append("复查描述过短，无法可靠判断趋势。")
            return FollowupTrend.INSUFFICIENT_INFO, evidence

        evidence.append("复查信息未显示明显好转或恶化。")
        return FollowupTrend.UNCHANGED, evidence
