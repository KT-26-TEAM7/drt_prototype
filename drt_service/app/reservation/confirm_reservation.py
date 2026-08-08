"""이형주 담당(통합): 사용자 최종 확인 후 DRT 예약을 요청.

`plan_route()`가 돌려준 직렬화된 계획(dict)을 그대로 받는다. DRT 탑승이
필요한 경우에만 실제로 배차를 요청하고, 도보 추천이거나 확정 불가능한
상태면 예약 없이 이유만 반환한다.
"""
from __future__ import annotations

from app.clients.drt_client import DrtClient

CONFIRMABLE_STATUSES = {"ready_for_confirmation", "walk_recommended"}


async def confirm_reservation(plan: dict, drt_client: DrtClient) -> dict:
    plan_status = plan.get("status")
    if plan_status not in CONFIRMABLE_STATUSES:
        return {"ok": False, "reservation": None, "reason": f"확정할 수 없는 계획 상태입니다: {plan_status}"}

    if plan.get("recommended_mode") != "drt":
        return {"ok": True, "reservation": None, "reason": "도보 이동 추천 결과라 DRT 예약이 필요하지 않습니다."}

    boarding = plan.get("boarding")
    alighting = plan.get("alighting")
    if not boarding or not alighting:
        return {"ok": False, "reservation": None, "reason": "승·하차 정류장 정보가 없어 예약을 요청할 수 없습니다."}

    # 정류장 간 주행시간은 이미 계획 단계에서 ETA 모델이 예측해 둔 값이다.
    # 배차 서버가 이 값으로 운행 구간 시간을 잡으므로 그대로 넘긴다.
    vehicle = plan.get("vehicle") or {}
    call = await drt_client.request_call(
        boarding_station_id=boarding["station_id"],
        alighting_station_id=alighting["station_id"],
        expected_wait_s=plan.get("expected_wait_s", 300),
        stop_to_stop_travel_s=vehicle.get("duration_s"),
    )

    if call.status != "accepted":
        # 거절된 호출은 예약으로 남기지 않는다. 배차 서버가 거절할 때는 call_id가
        # 비어 있어서, 저장하면 call_id 유니크 제약에 걸린다.
        return {
            "ok": False,
            "reservation": None,
            "reason": call.reason or "DRT 배차 요청이 거절되었습니다.",
        }

    return {
        "ok": True,
        "reservation": {
            "call_id": call.call_id,
            "status": call.status,
            "requested_at": call.requested_at,
            "boarding_station_id": boarding["station_id"],
            "alighting_station_id": alighting["station_id"],
            # 아래는 배차 서버를 쓸 때만 채워진다(MOCK 모드에서는 None).
            "vehicle_id": call.vehicle_id,
            "estimated_arrival_s": call.estimated_arrival_s,
            "tracking_url": call.tracking_url,
            "tracking_message": call.tracking_message,
            "dispatch_status": call.dispatch_status,
        },
        "reason": None,
    }
