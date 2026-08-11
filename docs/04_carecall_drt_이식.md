# carecall_drt 이식 (2026-08-11)

팀원(재령/다솔)이 케어콜 대화 분석과 DRT 의도 분석을 하나로 통합한 새 패키지
`KT_CareCall_DRT_Integrated/carecall_drt`를 전달했다. 이 문서는 그것을 이
워크스페이스에 이식하면서 무엇을 대체했고 무엇을 남겼는지, 이식 과정에서
발견·수정한 문제를 정리한다. README가 언급한 `docs/05_기존레포_반영가이드.md`는
실제 전달본에 없었다 — 이 문서가 그 역할을 대신한다.

## 무엇이 바뀌었나

기존 구조는 4개 프로세스로 나뉘어 있었다: `main_server`(통화 소유·상태기계) →
`bridge`(케어콜 출력을 drt_service 계약으로 변환) → `drt_service` →
`mock_drt_server`. 케어콜 분석은 `care_call_bot/drt_analyzer.py`가, "최신 발화
한 마디만 분석 + 상태 누적" 워크어라운드는 `main_server/conversation.py`가
맡고 있었다.

`carecall_drt`는 케어콜 대화 분석 + 다중 턴 상태 관리 + DRT 계획/예약 호출을
하나의 오케스트레이터(`CareCallDRTOrchestrator`)로 재작성했고, 다음을 자체
해결했다(회귀 테스트 54/54, 유닛 테스트 83개 통과):

- `specific_place`가 출력에서 사라지던 문제 — 이제 `DRTAnalysis`의 1급 필드.
- Gemini 이중 호출(다솜이 응답 1회 + DRT 의미분석 1회) — `GeminiJointResponder`가
  구조화 JSON 한 번으로 응답+의미를 함께 반환.
- "집에 있을래" 후 예약 잠김 버그 — `main_server/conversation.py`가 우회했던
  문제를 `SessionState` 기반 `DRTAnalyzer`가 자체 해결(최신 발화 한 마디 + 상태
  슬롯 — 새로 별도 상태 기계를 둘 필요가 없어졌다).
- 날짜/시간/픽업위치가 `SessionState.date/time/pickup_location` 정식 슬롯으로
  수집됨.

## 대체된 것

| 이전 | 대체 |
|---|---|
| `care_call_bot/drt_analyzer.py` | `carecall_drt.analyzer.DRTAnalyzer` |
| `main_server/analyzer.py`, `conversation.py` (삭제됨) | `carecall_drt.schemas.SessionState` |
| `main_server/talk.py` (삭제됨, 2차 Gemini 세션) | `carecall_drt.responses.RuleCareResponder` / `carecall_drt.gemini_client.GeminiJointResponder`(1회 호출) |
| `care_call_bot/drt_analyzer.py`, `gemini_chat_demo.py`, `openai_chat_demo.py` (삭제됨) | carecall_drt 전체 |

`main_server`가 케어콜 흐름에서 쓰던 `bridge/contract.py`·`gate.py`·`mapping.py`·
`drt_client.py`·`orchestrator.py`·`session.py`·`fake_service.py`도 더 이상
호출되지 않는다 — carecall_drt가 필드 체계가 다른(`search_mode` 대신
`route_query`/`is_specific` 등) 같은 역할을 자체적으로 한다. **단, 이 파일들은
삭제하지 않았다** — `scripts/live_demo.py`·`scripts/run_handoff.py`가 여전히
브릿지 파이프라인만 단독으로 시연/점검하는 도구로 쓰고 있고, 전용 테스트 6개도
그대로 남아 있다.

## 새로 생긴 것

- `carecall_drt/` (워크스페이스 루트, `bridge/`와 같은 층위) — 이식된 패키지 +
  `carecall_drt/tests/`(83개) + `carecall_drt/data/test_utterances.json`.
- `main_server/care_bridge.py` — carecall_drt와 이 워크스페이스의 안전장치
  (`bridge/location.py`, `bridge/notify.py`, `bridge/speech.py`,
  `bridge/preflight.py`)를 잇는 어댑터. 자세한 설계는 그 파일 상단 docstring 참고.
- `scripts/run_rule_regression.py`, `demo_multiturn.py`, `backend_smoke_test.py`,
  `rule_demo.py` — carecall_drt에서 함께 이식된 데모/회귀 도구.

## 이식하며 고친 버그

carecall_drt를 이 워크스페이스의 실제 drt_service에 연결해 보는 과정에서 세
가지 문제를 발견해 고쳤다(원본 팀 패키지 자체의 결함, 이 워크스페이스에서만
드러남 — 팀에 공유할 가치가 있다):

1. **`carecall_drt/backend.py::interpret_reservation`이 읽던 필드명이 실제
   drt_service 응답과 달랐다.** `estimated_arrival_seconds`/`pickup_eta_sec`를
   찾고 있었지만 실제 필드는 `estimated_arrival_s`
   (`drt_service/app/reservation/confirm_reservation.py`)다 — 조용히 도착
   예정 시간 안내를 건너뛰고 있었다. 필드명을 맞추고, `call_id`/`vehicle_id`를
   말로 읽지 않도록 고쳤다(전화로 들으신 어르신이 받아 적을 수 없는 값 — 기존
   `bridge/speech.py`의 설계 원칙과 동일, 문자로만 안내).
2. **`carecall_drt/backend.py`가 만드는 안내 문장에 "DRT"가 영어 그대로 들어
   있었다**(`"DRT로 이동할 수 있습니다"` 등). `main_server/care_bridge.py`가
   모든 응답을 `bridge/speech.py::sanitize()`에 통과시켜 "이동 차량"으로
   치환한다.
3. **`carecall_drt.analyzer`의 `ready_for_plan`은 `state.location is not None`을
   분석기 내부에서 직접 검사한다.** 이 때문에 위치를 backend 호출 시점에
   지연 바인딩하면(처음 설계) 분석기가 "아직 안 끝났다"고 판단해 버려 backend가
   영원히 불리지 않는다. `care_bridge.py`가 **매 턴, `process_turn`을 부르기
   전에** 위치를 먼저 채우도록 고쳤다(어르신 프로필 자택 좌표 + 위치정보 동의,
   `bridge/location.py::resolve_origin`). 또한 `carecall_drt/orchestrator.py`의
   `DRTBackendError` 처리가 항상 "경로 서버 연결이 원활하지 않다"는 통짜
   메시지로 뭉개고 있어서, 위치정보 동의 거부 같은 실제 이유가 있는 오류만
   구분해 그대로 말하도록 고쳤다(네트워크/서버 오류는 여전히 통짜 메시지).

## 여전히 남은 갭 (기존 gap ③, 이번 이식으로 해결되지 않음)

drt_service는 여전히 예약 시각 필드가 없는 즉시 호출 모델이다. carecall_drt도
날짜/시간을 슬롯으로 **수집**만 하고 `backend.build_plan_request()`가
drt_service로 **전달하지는 않는다**. `docs/integration_design.md`의 권고(②
지원 안 하기로 하고 안 묻거나, ③ drt_service 스키마 확장)가 그대로 유효하다.

## 사용자 결정 사항

- **보호자 알림 문자는 항상 보내지 않는다**(2026-08-11). carecall_drt 스키마에
  보호자 알림 동의 슬롯(`guardian_notify_consent`)이 없어졌다. 필요해지면
  `carecall_drt/analyzer.py`·`schemas.py`에 슬롯을 다시 추가하는 별도 작업이
  필요하다.

## 설정

`carecall_drt.config.Settings`는 `GEMINI_API_KEY` 또는 `GEMINI_KEY`(기존 이름)를
읽으므로 `care_call_bot/.env`의 `GEMINI_KEY`를 그대로 쓴다. DRT 백엔드 연결은
워크스페이스 루트 `.env`에 `DRT_BACKEND_URL`/`DRT_RELAY_TOKEN`/
`DRT_BACKEND_ENABLED`로 추가했다(기존 `DRT_BASE_URL`/`RELAY_API_TOKEN`과 같은
값 — `scripts/setup.py` 5단계가 동기화한다).

## 검증

- `py -m pytest carecall_drt/tests` — 83개 통과.
- `py scripts/run_rule_regression.py` — 54/54 통과.
- `py -m pytest tests` — 브릿지 단독 파이프라인 테스트 76개 통과(main_server용
  `test_conversation_state.py`는 대상 모듈과 함께 삭제).
- `main_server/app.py`를 `TestClient`로 기동해 `/`, `/call/start`,
  `/call/utterance`, `/call/{id}/state`, `/call/end` 전 구간 확인.
- 위치정보 동의가 없는 프로필(`elder_demo_02`)로 목적지·날짜·시간·픽업위치를
  모두 답한 뒤 실제로 위치 동의 문구가 나오는지 확인(수정 ③ 검증).
- 위치정보 동의가 있는 프로필(`elder_demo_01`)로 같은 흐름을 실행해 drt_service
  미기동 시 통짜 오류 메시지로, 기동 시(§실측) 실제 배차까지 이어지는지 확인.
