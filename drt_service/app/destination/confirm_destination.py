"""사용자의 목적지 확정 또는 취소 요청을 처리한다.

/api/plan(plan_category)이 requires_user_confirmation=True로 후보를 돌려준 뒤,
사용자가 그 후보를 최종 확정하거나 취소하는 단계를 위한 가벼운(무상태) 엔드포인트다.
DB나 provider에 의존하지 않으며, dev(app/services/destination/confirmation.py)의
confirm_destination과 동일한 규칙을 prod 스키마(app/schemas.py)에 맞춰 재구현한다.
"""
from __future__ import annotations

from app.schemas import DestinationConfirmRequest, DestinationConfirmResponse


class DestinationConfirmationError(ValueError):
    """목적지 확인 요청 처리 중 발생한 오류."""


def confirm_destination(request: DestinationConfirmRequest) -> DestinationConfirmResponse:
    if not request.confirmed:
        return DestinationConfirmResponse(
            status="cancelled",
            message="목적지 선택을 취소했습니다. 다른 목적지를 말씀해주세요.",
            destination=None,
        )

    if request.destination is None:
        raise DestinationConfirmationError("확인할 목적지 정보가 없습니다.")

    return DestinationConfirmResponse(
        status="confirmed",
        message=f"{request.destination.name}을(를) 목적지로 설정했습니다.",
        destination=request.destination,
    )
