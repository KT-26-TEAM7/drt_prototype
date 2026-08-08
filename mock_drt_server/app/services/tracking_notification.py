from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrackingNotification:
    message: str
    tracking_url: str


def build_tracking_notification(
    tracking_url: str,
    departure_stop_name: str,
) -> TrackingNotification:
    message = (
        "DRT 예약이 완료되었습니다.\n"
        f"승차 장소: {departure_stop_name}\n"
        "아래 링크에서 차량 위치와 도착 예정시간을 확인해 주세요.\n"
        f"{tracking_url}"
    )
    return TrackingNotification(message=message, tracking_url=tracking_url)
