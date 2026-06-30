from dataclasses import dataclass

from app.domain.enums import CaseStatus


@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    current_status: CaseStatus
    requested_status: CaseStatus
    reason: str


class StateMachine:
    _allowed: dict[CaseStatus, set[CaseStatus]] = {
        CaseStatus.NEW: {CaseStatus.NEED_MORE_INFO, CaseStatus.FOLLOWUP_PENDING, CaseStatus.ESCALATED},
        CaseStatus.NEED_MORE_INFO: {
            CaseStatus.NEED_MORE_INFO,
            CaseStatus.FOLLOWUP_PENDING,
            CaseStatus.ESCALATED,
        },
        CaseStatus.DIAGNOSED: {CaseStatus.FOLLOWUP_PENDING, CaseStatus.ESCALATED},
        CaseStatus.FOLLOWUP_PENDING: {CaseStatus.FOLLOWUP_REVIEW, CaseStatus.ESCALATED},
        CaseStatus.FOLLOWUP_REVIEW: {
            CaseStatus.IMPROVING,
            CaseStatus.WORSENING,
            CaseStatus.ESCALATED,
            CaseStatus.NEED_MORE_INFO,
            CaseStatus.CLOSED,
        },
        CaseStatus.IMPROVING: {CaseStatus.FOLLOWUP_PENDING, CaseStatus.CLOSED, CaseStatus.ESCALATED},
        CaseStatus.WORSENING: {CaseStatus.ESCALATED, CaseStatus.FOLLOWUP_PENDING},
        CaseStatus.ESCALATED: {CaseStatus.CLOSED},
        CaseStatus.CLOSED: set(),
    }

    def transition(
        self, current: CaseStatus | str, requested: CaseStatus | str, reason: str
    ) -> TransitionResult:
        current_status = CaseStatus(current)
        requested_status = CaseStatus(requested)
        allowed = requested_status in self._allowed[current_status]
        return TransitionResult(
            allowed=allowed,
            current_status=current_status,
            requested_status=requested_status,
            reason=reason
            if allowed
            else f"非法状态流转：{current_status.value} -> {requested_status.value}",
        )

    def apply(self, case, requested: CaseStatus, reason: str) -> TransitionResult:
        result = self.transition(case.status, requested, reason)
        if result.allowed:
            case.status = requested.value
        return result
