from app.schemas.cases import DiagnosisRead, PlanRead
from app.schemas.knowledge import KnowledgeEntry


class DiagnosisTool:
    def diagnose(
        self,
        entries: list[KnowledgeEntry],
        multimodal_observation: dict | None = None,
    ) -> DiagnosisRead:
        if not entries:
            return DiagnosisRead(
                suspected_problem="信息不足",
                likelihood="较低",
                evidence=["当前症状信息不足，暂不形成明确疑似问题。"],
                confusions=[],
            )

        top = entries[0]
        evidence = top.evidence_keywords[:3] or top.typical_symptoms[:3]
        vision_evidence = []
        candidate_evidence = []
        if multimodal_observation:
            vision = multimodal_observation.get("vision", {})
            if top.problem_name in vision.get("possible_problems", []):
                candidate_evidence.append(f"视觉候选问题指向：{top.problem_name}")
            vision_evidence = [
                f"视觉观察：{item}"
                for item in (
                    vision.get("observed_parts", [])[:2] + vision.get("visual_symptoms", [])[:3]
                )
            ]
        return DiagnosisRead(
            suspected_problem=top.problem_name,
            likelihood="较高" if candidate_evidence or len(evidence) >= 2 else "可能",
            evidence=(candidate_evidence + evidence + vision_evidence)[:6],
            confusions=top.confusions[:3],
        )


class PlanTool:
    def build_plan(
        self,
        entry: KnowledgeEntry | None,
        safety_warnings: list[str],
        weather_observation: dict | None = None,
    ) -> PlanRead:
        weather_actions = self._weather_actions(weather_observation or {})
        if entry is None:
            return PlanRead(
                summary="当前信息不足，建议先补充关键症状信息。",
                immediate_actions=["补充发生部位、症状形态、生长阶段和采收时间。", *weather_actions],
                observation_points=["是否出现新症状", "症状是否扩展"],
                escalation_conditions=["症状快速扩展", "果实受害", "多株同时受害"],
                safety_warnings=safety_warnings,
                followup_after_days=None,
            )

        actions = entry.non_chemical_actions or ["优先采用非化学措施，并继续观察症状变化。"]
        actions = [*actions, *weather_actions]
        observation_points = entry.observation_points or ["是否出现新症状", "症状是否继续扩展"]
        escalation = entry.escalation_conditions or ["症状快速扩展", "果实受害", "多株同时受害"]
        return PlanRead(
            summary=f"当前更像{entry.problem_name}，建议先采取保守处置并安排复查。",
            immediate_actions=actions[:5],
            observation_points=observation_points[:5],
            escalation_conditions=escalation[:5],
            safety_warnings=safety_warnings + entry.safety_notes[:3],
            followup_after_days=3,
        )

    def _weather_actions(self, weather_observation: dict) -> list[str]:
        actions: list[str] = []
        if weather_observation.get("humidity_risk") == "high":
            actions.append("当前湿度偏高，优先改善通风，避免叶面长时间潮湿。")
        if weather_observation.get("recent_rain"):
            actions.append("近期有降水或叶面潮湿，先减少叶片积水和过密遮挡。")
        if weather_observation.get("temperature_summary") == "偏高":
            actions.append("高温时段避免强刺激处理，优先选择清晨或傍晚观察和管理。")
        if weather_observation.get("temperature_summary") == "偏低":
            actions.append("低温时注意保温和减少水分波动，观察恢复速度。")
        return actions
