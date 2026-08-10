# 케어콜 ↔ DRT 연결 설계

두 파트를 실제로 이어 보면서 정한 규칙과, 이어 보니 드러난 문제들을 정리했습니다.
표에 적힌 "권고"는 브릿지에서 우회한 것들이며, 원래는 각 파트에서 고치는 편이 낫습니다.

- 케어콜 파트: `care-call-bot` (`drt_analyzer.py`가 매 턴 JSON을 생성)
- DRT 파트: `drt_service` (FastAPI, `/api/plan`·`/api/reservations`)

---

## 1. 무엇을 계약으로 삼았나

브릿지는 `drt_analyzer.analyze_conversation()`의 **출력 JSON만** 입력으로 받습니다.
care-call-bot의 코드를 import하지 않습니다.

| 이유 | 설명 |
|---|---|
| 의존성 | 분석기 쪽은 google-genai가 필요하고 TTS가 macOS 전용입니다 |
| 버전 | 분석기 출력에서 `search_mode` 등 일부 필드가 빠져도 키가 없어도 동작해야 합니다 |
| 시험 | 모델·네트워크 없이 테스트가 돌아가야 합니다 |

`bridge/contract.py::CareCallResult`가 이 흡수를 담당합니다. 모르는 키는 버리고,
없는 키는 기본값을 씁니다.

---

## 2. 대화 단계 → DRT 호출 여부 (`bridge/gate.py`)

이 게이트를 통과하지 못하면 어떤 경우에도 DRT API가 호출되지 않습니다.

| `dialogue_stage` / 조건 | 브릿지 동작 | 이유 |
|---|---|---|
| `emergency` 또는 `emergency_risk=true` | **호출 안 함**, 보호자·119 안내 | 배차보다 구조가 우선 |
| `not_needed`, `reservation_consent=refused` | 호출 안 함 | 원치 않는 배차 방지 |
| `need_detection` | 호출 안 함, 분석기 질문을 그대로 되물음 | 방문 의향조차 미확인 |
| `reservation_confirm` | 호출 안 함, 예약 동의를 먼저 여쭘 | **동의 없이 TMAP 쿼터를 쓰지 않기 위함** |
| `reservation_info_collection` + 동의 + 목적지 확정 | **호출함** | 정상 경로 |
| `reservation_completed` | 호출 안 함 | 이미 예약됨 |
| `guardian_notification` | 호출 안 함, 보호자 문구만 생성 | drt_service에 보호자 알림 API가 없음 |

### 어떤 `missing_slots`이 호출을 막는가

| 슬롯 | 막는가 | 이유 |
|---|---|---|
| `medical_department` | 막음 | 진료과가 정해져야 검색어가 나옴 |
| `place_resolution_method` | 막음 | "가까운 곳"인지 "늘 가시던 곳"인지 미정 |
| `exact_destination` | 막음 | 목적지 이름 미확보 |
| `date`, `time` | 막지 않음 | drt_service는 예약 시각을 받지 않는 즉시 호출 모델 (→ 3-③) |
| `pickup_location` | 막지 않음 | 텍스트 대신 등록 좌표를 사용 (→ 3-①) |
| `origin_full_address`, `destination_full_address` | 막지 않음 | 같은 이유. 좌표가 주소보다 정확함 |

---

## 3. 알려진 갭과 브릿지의 우회

이어 붙이면서 드러난, **어느 한쪽을 고쳐야 깔끔해지는** 지점들입니다.

### ① 좌표가 없다 — 케어콜은 전화, DRT는 GPS 전제

drt_service는 위도·경도와 정확도(100m 이내), 측정 시각(120초 이내)을 요구합니다
(`app/schemas.py::validate_location_quality`). 케어콜은 전화 통화라 브라우저 위치 API를
쓸 수 없고, 분석기가 주는 것은 "집 앞" 또는 텍스트 주소뿐입니다.

- **브릿지 우회**: 사전 등록된 어르신 프로필의 자택 좌표를 출발지로 사용
  (`bridge/location.py`). 실측이 아니므로 `accuracy`를 등록 주소 정밀도(기본 30m)로
  명시해 보냅니다.
- **권고**: 실제 서비스에서는 가입 시 주소를 지오코딩해 사용자 DB에 넣어 두는 것이
  맞습니다. drt_service에 주소→좌표 변환은 없습니다(역지오코딩만 있음).

### ② `specific_place`가 출력에서 사라진다

`drt_analyzer.py`는 내부적으로 정확한 장소명("사당솔밭도서관")을 계산하지만
`OUTPUT_KEYS`에 넣지 않아 결과 JSON에서 사라집니다. 그런데 `search_mode`는
`exact_place`로 나오기 때문에, 받는 쪽은 "정확명 검색을 해야 하는데 이름이 없는" 상태가
됩니다.

- **브릿지 우회**: `extracted_keywords`에서 장소 접미사(치과·도서관 등)를 단서로 복원
  (`bridge/contract.py::recover_specific_place`).
- **권고(케어콜 파트)**: `OUTPUT_KEYS`에 `specific_place`를 추가하면 복원 로직이
  통째로 필요 없어집니다. **가장 먼저 고치면 좋은 항목입니다.**

### ③ 예약 시각을 DRT가 받지 못한다

분석기는 "내일 오전 10시"를 수집하지만, drt_service의 `PlanRequest`에는 예약 일시
필드가 없습니다. `expected_wait_s`(예상 대기시간)만 있는 **즉시 호출** 모델입니다.

- **브릿지 우회**: 호출을 막지는 않되, 시각이 이미 수집된 경우
  `schedule_hint_present` 경고를 결과와 감사 로그에 남깁니다.
- **권고**: 팀에서 결정이 필요합니다. (가) 예약 기능을 지원하지 않기로 하고 케어콜
  프롬프트에서 시각을 묻지 않거나, (나) drt_service에 예약 일시를 추가해야 합니다.
  **지금 상태로는 "내일 10시에 불러줘"라고 하셔도 지금 배차됩니다.**

### ④ `/api/reservations`가 어느 후보를 골랐는지 받지 못한다

`/api/plan`이 `needs_destination_confirmation`으로 후보 여러 곳을 돌려준 뒤, 어르신이
한 곳을 고르셔도 그 선택을 전달할 방법이 없습니다. `/api/reservations`는 `PlanRequest`를
받아 **계획을 처음부터 다시 세웁니다.**

- **브릿지 우회**: 고르신 후보의 이름으로 `is_specific=true` 재검색을 돌려 한 곳으로
  좁힌 뒤 예약합니다(`orchestrator._handle_choice`).
- **권고(DRT 파트)**: `/api/reservations`가 확정된 목적지 좌표를 직접 받게 하면
  재검색이 사라집니다. 지금은 계획 시점과 예약 시점의 결과가 달라질 수 있고
  TMAP 호출도 두 배로 듭니다.

### ⑤ 보호자 알림 경로가 없다

분석기는 `guardian_notify_consent`와 `guardian_message`를 만들지만, drt_service에는
보호자에게 보내는 API가 없습니다.

- **브릿지 우회**: 문구만 생성해 `HandoffOutcome.guardian_message`로 돌려줍니다.
  실제 발송은 브릿지 밖(알림 채널)의 몫입니다.
- **권고**: 알림 채널 담당과 인터페이스를 정해야 합니다.

### ⑥ 동의 항목이 두 파트에 갈라져 있다

케어콜의 `consent.py`는 음성·STT·건강 발화 동의만 받고, 위치정보·보호자 제공·배차
동의는 "DRT 파트 담당"으로 명시적으로 남겨 두었습니다
(`docs/personal_info_consent_report.md`).

- **브릿지 처리**: 좌표를 보내기 전에 프로필의 `location_consent`를 확인하고, 없으면
  호출하지 않고 동의를 여쭙니다.
- **권고**: 통화 시작 시 케어콜의 동의 안내에 위치정보 항목을 함께 넣을지, 필요한
  시점에 따로 여쭐지 팀에서 정해야 합니다. 지금 브릿지는 후자입니다.

### ⑦ 음성 규칙과 영어 표기

`prompts/system_prompt.txt`는 영어·한자·이모지를 금지합니다(TTS로 읽히기 때문). 그런데
"DRT"는 영어입니다.

- **브릿지 처리**: 어르신께 드리는 말에서는 "이동 차량"으로 바꿔 읽습니다.
  한자·이모지는 제거하고, 목적지 이름에 든 영문은 뜻이 사라지므로 지우지 않고
  위반으로 보고만 합니다(`speech.tts_violations`).
- 배경: 모델 비교 과정에서 LLM이 답변 끝에 한자를 흘린 사례가 있어, 문장 검사를
  넣어 두었습니다.

---

## 4. 필드 매핑 요약

| 분석기 출력 | drt_service 요청 | 변환 규칙 |
|---|---|---|
| `search_mode = nearby_search` | `is_specific: false` | `search_keywords[0]` → `query` |
| `search_mode = exact_place` | `is_specific: true` | `specific_place`(복원) → `query` |
| `search_mode = ask_frequent_or_nearby` 등 | 호출 안 함 | `place_resolution_question`을 되물음 |
| `destination_category` | (검색어 폴백) | `mapping.PLACE_WORD`로 장소 이름 생성 |
| (없음) | `latitude`/`longitude`/`accuracy`/`captured_at` | 프로필 등록 좌표 + 호출 시각 |
| (없음) | `expected_wait_s` | 브릿지 설정값(기본 300초) |

> `PlanRequest`는 `extra="forbid"`입니다. 정의되지 않은 키를 하나라도 넣으면 422가
> 납니다. 테스트로 고정해 두었습니다(`test_요청_본문에_drt_service가_모르는_키를_넣지_않는다`).

---

## 5. DRT 응답 → 어르신께 드리는 말

| `plan.status` | 브릿지 처리 | 다음에 기다리는 답 |
|---|---|---|
| `ready_for_confirmation` | 소요 시간·승차 정류장 안내 후 예약 확인 | 예/아니오 |
| `walk_recommended` | 걸어가셔도 된다고 안내, 예약하지 않음 | 없음 |
| `needs_destination_confirmation` | 후보 이름을 최대 3곳 읽어 드림 | 후보 선택 |
| `destination_not_found` | 이름을 다시 여쭘 | 목적지 |
| `destination_outside_service_area` | 다른 곳을 여쭘 | 목적지 |
| `no_feasible_destination` | 다른 곳을 여쭘 | 목적지 |
| `outside_service_area` | 서비스 지역이 아님을 안내 | 없음 |
| `no_accessible_boarding_station` | 승차 장소가 멀다고 안내 | 없음 |
| `route_api_failed` | 잠시 뒤 다시 안내 | 없음 |

예약 응답에서 `call_id`는 **읽지 않습니다.** 전화로 들으신 어르신이 받아 적을 수 없는
값이기 때문입니다.

---

## 6. 다음에 할 일

우선순위 순입니다.

1. **케어콜 파트**: `OUTPUT_KEYS`에 `specific_place` 추가 (→ ②). 가장 작고 효과가 큽니다.
2. **팀 결정**: 예약 시각을 지원할 것인지 (→ ③). 지원한다면 drt_service 스키마 변경이 필요합니다.
3. **DRT 파트**: `/api/reservations`가 확정 목적지를 직접 받도록 (→ ④).
4. **팀 결정**: 위치정보 동의를 언제 받을지 (→ ⑥), 보호자 알림 채널 인터페이스 (→ ⑤).
5. 어르신 프로필(자택 좌표) 저장소를 데모용 JSON에서 실제 사용자 DB로 교체 (→ ①).
