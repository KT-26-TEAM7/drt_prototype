"""drt_service를 띄우지 않고 브릿지 흐름을 확인하기 위한 가짜 서버.

drt_service의 MockTmapClient와 같은 목적이다. 실제 서버가 돌려주는 응답 모양
(app/reservation/plan_route.py::serialize_result)을 그대로 흉내 내되, 검색어에 따라
결정적으로 답한다. 그래서 "후보가 여러 개일 때", "걸어가는 게 나을 때" 같은 분기를
네트워크 없이 전부 시연할 수 있다.

정류장 이름은 drt_service/data/stations_geo.csv(사당동 일대)에서 가져왔다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _station(station_id: int, name: str, walk_m: int, walk_s: int) -> dict[str, Any]:
    return {
        "station_id": station_id,
        "name": name,
        "station_type": "기존",
        "walk_distance_m": walk_m,
        "walk_duration_s": walk_s,
    }


def _ready_plan(destination: str, address: str = "서울 동작구 사당동") -> dict[str, Any]:
    boarding = _station(3, "남성역", 180, 150)
    alighting = _station(9, "사당종합복지관", 210, 175)
    vehicle_s = 420
    total = boarding["walk_duration_s"] + vehicle_s + alighting["walk_duration_s"]
    return {
        "status": "ready_for_confirmation",
        "mode": "category",
        "recommended_mode": "drt",
        "requires_user_confirmation": True,
        "destination": {"name": destination, "address": address,
                        "latitude": 37.4770, "longitude": 126.9798},
        "boarding": boarding,
        "alighting": alighting,
        "vehicle": {"distance_m": 2100, "duration_s": vehicle_s, "source": "catboost_regressor"},
        "direct_walk": {"distance_m": 2400, "duration_s": 2000, "source": "mock_pedestrian"},
        "total_travel_time_s": total,
        "total_travel_time_min": round(total / 60, 1),
        "score_s": 1500,
        "reason": "가중 보행·대기·차량시간 비교 결과 이동 차량이 유리",
    }


class FakeDrtService:
    """검색어를 보고 미리 정해 둔 응답을 돌려준다."""

    def __init__(self) -> None:
        self.plan_calls: list[dict[str, Any]] = []
        self.reserve_calls: list[dict[str, Any]] = []

    def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.plan_calls.append(payload)
        return {"ok": True, "plan": self._plan_body(payload)}

    def _plan_body(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "")

        if "치과" in query and not payload.get("is_specific"):
            # 대분류 검색인데 이름이 비슷한 곳이 여러 곳인 상황.
            return {
                "status": "needs_destination_confirmation",
                "mode": "specific",
                "recommended_mode": "needs_confirmation",
                "requires_user_confirmation": True,
                "candidates": [
                    {"name": "사당연세치과", "address": "서울 동작구 사당동",
                     "latitude": 37.4849, "longitude": 126.9711},
                    {"name": "남성역바른치과", "address": "서울 동작구 사당동",
                     "latitude": 37.4826, "longitude": 126.9654},
                ],
            }

        if "도서관" in query:
            # 아주 가까워서 걸어가는 편이 나은 목적지.
            return {
                "status": "walk_recommended",
                "mode": "specific",
                "recommended_mode": "walk",
                "destination": {"name": "사당솔밭도서관", "address": "서울 동작구 사당동",
                                "latitude": 37.4840, "longitude": 126.9671},
                "direct_walk": {"distance_m": 320, "duration_s": 300, "source": "mock_pedestrian"},
                "total_travel_time_s": 300,
                "reason": "목적지가 가까워 이동 차량보다 직접 도보가 적합",
            }

        if "우주정거장" in query:
            return {
                "status": "destination_not_found",
                "mode": "specific",
                "recommended_mode": "needs_confirmation",
                "requires_user_confirmation": True,
            }

        if "제주" in query:
            return {
                "status": "destination_outside_service_area",
                "mode": "specific",
                "recommended_mode": "other_transit",
                "reason": "이름이 일치하는 장소를 찾았지만 모두 서비스 범위 밖입니다.",
            }

        return _ready_plan(query or "목적지")

    def reserve(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.reserve_calls.append(payload)
        plan = self._plan_body(payload)
        if plan.get("recommended_mode") != "drt":
            return {"ok": True, "reservation": None, "plan": plan,
                    "reason": "도보 이동 추천 결과라 예약이 필요하지 않습니다."}
        # 배차 서버(mock-drt-server)가 붙어 있을 때 drt_service가 돌려주는 모양을 그대로 흉내 낸다.
        call_id = f"CALL-{uuid.uuid4().hex[:8].upper()}"
        tracking_url = f"http://localhost:8000/tracking?token={uuid.uuid4().hex}"
        boarding_name = plan["boarding"]["name"]
        return {
            "ok": True,
            "plan": plan,
            "reservation": {
                "call_id": call_id,
                "status": "accepted",
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "boarding_station_id": plan["boarding"]["station_id"],
                "alighting_station_id": plan["alighting"]["station_id"],
                "vehicle_id": "VEHICLE-001",
                "estimated_arrival_s": 132,
                "tracking_url": tracking_url,
                "tracking_message": (
                    "DRT 예약이 완료되었습니다.\n"
                    f"승차 장소: {boarding_name}\n"
                    "아래 링크에서 차량 위치와 도착 예정시간을 확인해 주세요.\n"
                    f"{tracking_url}"
                ),
                "dispatch_status": "DISPATCHED",
            },
            "reason": None,
        }
