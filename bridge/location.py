"""어르신의 출발 좌표를 확보한다.

케어콜은 전화 통화라 브라우저 위치 API를 쓸 수 없다. 분석기가 뽑아 주는 것은
"집 앞" 같은 표현이나 텍스트 주소뿐인데, drt_service는 위도·경도와 정확도(m),
측정 시각을 요구한다(app/schemas.py::validate_location_quality). 그래서 브릿지는
사전에 등록된 **어르신 프로필의 자택 좌표**를 출발지로 쓴다.

위치정보 이용 동의는 care-call-bot의 consent.py가 "DRT 파트 담당"이라며 범위 밖으로
남겨 둔 항목이다(docs/personal_info_consent_report.md). 그래서 여기서 확인한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCATION_CONSENT_QUESTION = (
    "차를 부르려면 어르신 댁 위치를 이용해야 해요. 그렇게 해도 괜찮으실까요?"
)


@dataclass(frozen=True, slots=True)
class Origin:
    """drt_service에 보낼 출발 위치."""

    latitude: float
    longitude: float
    accuracy_m: float
    source: str  # profile_home | device_gps

    def to_payload(self) -> dict[str, Any]:
        # captured_at은 호출 직전 시각으로 채운다. drt_service가 120초보다 오래된
        # 위치를 422로 거절하기 때문이다. 등록 좌표는 시간에 따라 변하지 않으므로
        # "지금 이 좌표를 쓰겠다"는 의미의 시각으로 보는 것이 맞다.
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "accuracy": self.accuracy_m,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }


@dataclass(frozen=True, slots=True)
class LocationUnavailable:
    code: str
    spoken: str = ""


@dataclass(frozen=True, slots=True)
class UserProfile:
    user_id: str
    name: str
    home_latitude: float | None
    home_longitude: float | None
    home_address: str = ""
    location_consent: bool = False
    contact: str = ""  # 어르신 본인 번호(예약 확인 문자 수신)
    guardian_name: str = ""
    guardian_contact: str = ""

    @classmethod
    def from_dict(cls, user_id: str, payload: dict[str, Any]) -> "UserProfile":
        def _coord(key: str) -> float | None:
            value = payload.get(key)
            return float(value) if isinstance(value, (int, float)) else None

        return cls(
            user_id=user_id,
            name=str(payload.get("name") or ""),
            home_latitude=_coord("home_latitude"),
            home_longitude=_coord("home_longitude"),
            home_address=str(payload.get("home_address") or ""),
            location_consent=bool(payload.get("location_consent")),
            contact=str(payload.get("contact") or ""),
            guardian_name=str(payload.get("guardian_name") or ""),
            guardian_contact=str(payload.get("guardian_contact") or ""),
        )


class ProfileStore:
    """데모용 어르신 프로필 저장소(JSON 파일).

    실제 서비스에서는 가입 시 등록한 주소를 지오코딩해 둔 사용자 DB가 이 자리에 온다.
    """

    def __init__(self, profiles: dict[str, UserProfile]) -> None:
        self._profiles = profiles

    @classmethod
    def load(cls, path: str | Path) -> "ProfileStore":
        file_path = Path(path)
        if not file_path.exists():
            return cls({})
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        return cls({
            user_id: UserProfile.from_dict(user_id, payload)
            for user_id, payload in raw.items()
            if isinstance(payload, dict)
        })

    def get(self, user_id: str) -> UserProfile | None:
        return self._profiles.get(user_id)


def resolve_origin(
    profile: UserProfile | None,
    *,
    accuracy_m: float,
    device_location: Origin | None = None,
) -> Origin | LocationUnavailable:
    """출발 좌표를 정한다. 단말 실측 위치가 있으면 그쪽이 우선이다."""
    if device_location is not None:
        return device_location

    if profile is None:
        return LocationUnavailable("profile_not_found")

    if not profile.location_consent:
        return LocationUnavailable("location_consent_missing", _LOCATION_CONSENT_QUESTION)

    if profile.home_latitude is None or profile.home_longitude is None:
        return LocationUnavailable(
            "home_coordinates_missing",
            "어르신 댁 주소가 아직 등록되어 있지 않아요. 담당자가 확인 후 다시 연락드릴게요.",
        )

    return Origin(
        latitude=profile.home_latitude,
        longitude=profile.home_longitude,
        accuracy_m=accuracy_m,
        source="profile_home",
    )
