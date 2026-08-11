# DRT JSON 계약

## 분석 결과 핵심 필드

```json
{
  "dialogue_stage": "reservation_info_collection",
  "drt_status": "needed",
  "destination_category": "medical_orthopedics",
  "destination_candidates": ["정형외과"],
  "specific_place": "",
  "place_preference": "nearby",
  "reservation_consent": "confirmed",
  "missing_slots": ["date", "time", "pickup_location"],
  "target_slot": "date",
  "next_question": "가실 날짜를 알려주실 수 있을까요?",
  "route_query": "정형외과",
  "is_specific": false,
  "ready_for_plan": true,
  "ready_for_reservation": false
}
```

## 목적지 분류

- 병원: `medical_general`
- 정형외과: `medical_orthopedics`
- 내과: `medical_internal`
- 안과: `medical_ophthalmology`
- 이비인후과: `medical_ent`
- 피부과: `medical_dermatology`
- 재활의학과: `medical_rehabilitation`
- 치과: `medical_dental`
- 약국: `pharmacy`
- 시장/마트/편의점: `shopping_*`
- 주민센터/구청/은행: `public_*`
- 복지관/경로당: `welfare_center`, `senior_center`
- 교회/성당/절: `religious_*`
- 가족/친구 방문: `social_*`

## Gemini가 반환할 수 있는 semantic

```json
{
  "visit_intent": true,
  "destination_category": "medical_orthopedics",
  "destination_candidates": ["정형외과"],
  "specific_place": "",
  "place_preference": "nearby",
  "extracted_keywords": ["무릎"]
}
```

Gemini는 다음 값을 만들지 않는다.

- `dialogue_stage`
- `drt_status`
- `missing_slots`
- `target_slot`
- `next_question`
- `reservation_consent`
- `date`
- `time`
- `pickup_location`

## drt-algo `/api/plan` 요청

```json
{
  "latitude": 37.4849,
  "longitude": 126.9710,
  "accuracy": 15,
  "max_walk_m": 500,
  "query": "정형외과",
  "is_specific": false,
  "expected_wait_s": 300
}
```

## 예약 원칙

1. `/api/plan`으로 목적지와 경로 계산
2. 서버가 `ready_for_confirmation`을 반환
3. 사용자에게 경로와 ETA 안내
4. 사용자가 “네”라고 동의
5. 동일 요청으로 `/api/reservations` 호출
