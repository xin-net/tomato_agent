from dataclasses import dataclass, field


@dataclass(frozen=True)
class SafetyContext:
    days_to_harvest: int | None = None
    recent_pesticide_use: str | None = None
    environment: str | None = None
    suspected_problem: str | None = None
    severity: str | None = None
    uncertain: bool = False


@dataclass(frozen=True)
class SafetyResult:
    chemical_detail_allowed: bool
    risk_level: str
    warnings: list[str] = field(default_factory=list)
    must_escalate: bool = False

    def to_dict(self) -> dict:
        return {
            "chemical_detail_allowed": self.chemical_detail_allowed,
            "risk_level": self.risk_level,
            "warnings": self.warnings,
            "must_escalate": self.must_escalate,
        }


class SafetyChecker:
    def check(self, context: SafetyContext) -> SafetyResult:
        warnings: list[str] = []
        chemical_detail_allowed = False
        risk_level = "low"
        must_escalate = False

        if context.days_to_harvest is not None and context.days_to_harvest <= 7:
            risk_level = "medium"
            warnings.append("距离采收较近，不提供具体药剂、剂量、兑水比例或施药频次。")

        if context.recent_pesticide_use in {"有", "yes", "true", "近期有"}:
            risk_level = "medium"
            warnings.append("近期已有用药记录，不提供混用或叠加用药建议。")

        if context.environment == "阳台":
            warnings.append("家庭阳台场景优先采用非化学措施。")

        if context.uncertain:
            risk_level = "medium"
            warnings.append("当前诊断仍有不确定性，不能给出确定性处方。")

        if context.severity in {"大面积", "严重", "快速扩展", "果实受害"}:
            risk_level = "high"
            must_escalate = True
            warnings.append("症状严重或快速扩展，建议联系当地农技人员或专业人员确认。")

        if not warnings:
            warnings.append("本系统仅提供家庭种植和学习场景下的辅助建议。")

        return SafetyResult(
            chemical_detail_allowed=chemical_detail_allowed,
            risk_level=risk_level,
            warnings=warnings,
            must_escalate=must_escalate,
        )
