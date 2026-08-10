# 시스템 아키텍처 그림 — AI 일러스트 툴 프롬프트

발표 슬라이드용 컬러 / 한글 라벨 / 영문 지시문.
아래 **PROMPT 1**을 그대로 복사해 넣으세요. 결과가 어긋나면 §수정 프롬프트를 이어서 씁니다.

---

## PROMPT 1 — 메인 (전체 붙여넣기)

```
Create a clean, presentation-quality system architecture diagram for a conference
slide. Vector-style flat illustration, 16:9 landscape, generous white space.

SUBJECT
A voice-based elderly care-call AI that detects a travel intention during a friendly
phone call and dispatches a Demand-Responsive Transit (DRT) vehicle. Four services
talk to each other over HTTP only — they never import each other's code.

LAYOUT — left-to-right pipeline, four rounded rectangular service boxes in one
horizontal row, plus a human figure on the far left and a phone/SMS output on the
far right.

[far left]  An elderly person holding a landline phone, simple line-art figure,
            no facial detail. Caption below: 어르신
   │  arrow labeled: 안부 전화 (음성)
   ▼
[BOX ⓪]  Title: 메인 서버      Subtitle: 통화 소유 · 대화 상태
         Badge in corner: :8002
   │  arrow labeled: 대화 턴
   ▼
[BOX ④]  Title: 케어콜 봇      Subtitle: 대화 · 의도 분석 (Gemini)
         Small caption under the box: 매 턴 분석 JSON 생성
   │  thick arrow labeled: 분석 결과 JSON (계약)
   ▼
[BOX ①]  Title: 브릿지        Subtitle: 케어콜 ↔ DRT 접착제
         HIGHLIGHT THIS BOX — it is the core contribution. Use a slightly larger
         size, a stronger fill, and a soft drop shadow so the eye lands here first.
         Inside the box show six small numbered chips stacked in two columns:
            ① 게이트   ② 검색어   ③ 좌표
            ④ 호출     ⑤ 문장     ⑥ 문자
   │  arrow labeled: HTTP  /api/plan · /api/reservations
   ▼
[BOX ②]  Title: DRT 서비스     Subtitle: 정류장 · 경로 · 목적지 · 예약
         Badge in corner: :8001
   │  arrow labeled: HTTP  POST /calls
   ▼
[BOX ③]  Title: 가상 DRT 서버   Subtitle: 배차 · 차량 추적 · 조회 페이지
         Badge in corner: :8000
   │  arrow labeled: 실시간 조회 링크
   ▼
[far right] A smartphone outline showing a small map pin and a moving car icon.
            Caption below: 어르신 · 보호자 문자

CALLOUT — a separate small box, placed below the 브릿지 box and connected to it with
a short dashed line. Red/warm accent color, warning-triangle icon.
   Title: 안전 게이트 — DRT 호출 차단
   Bulleted items, small text:
     · 응급 표현 감지
     · 어르신이 거절
     · 차량 호출 동의 없음
     · 목적지 미확정
     · 위치정보 동의 없음

STYLE
- Flat vector, no gradients, no 3D, no glossy or neon effects.
- Palette: one calm blue as the base for boxes, one warm orange reserved ONLY for
  the 브릿지 box and its arrows, one muted red ONLY for the safety callout.
  Everything else neutral gray. Maximum three accent hues total.
- Rounded corners (~8px radius), 2px strokes, thin arrows with small solid heads.
- Typography: a clean Korean-supporting sans-serif. Titles bold and large enough to
  read from the back of a lecture hall; subtitles one step smaller in gray.
- White or transparent background. No frame, no border, no title bar, no logo.
- Every arrow is labeled. Arrows flow strictly left to right; no crossing lines.

TEXT RULES — CRITICAL
- Render all labels EXACTLY as written above, in Korean, with no translation,
  no transliteration, no invented extra words, and no spelling drift.
- The only Latin text allowed is: HTTP, JSON, DRT, Gemini, /api/plan,
  /api/reservations, POST /calls, :8000, :8001, :8002.
- Do not add any label, caption, watermark, or annotation that is not listed above.
```

---

## NEGATIVE PROMPT (분리 입력란이 있는 툴용)

```
photorealistic, 3D render, isometric, drop-shadow-heavy skeuomorphism, neon glow,
gradient mesh, hand-drawn sketchy lines, stock-photo people, cluttered background,
decorative icons unrelated to the labels, garbled or mojibake Korean text,
random English words, watermark, signature, frame border, dark background
```

---

## 수정 프롬프트 (1차 결과 보고 골라 쓰기)

증상별로 **한 번에 하나씩만** 넣는 편이 결과가 안정적입니다.

| 결과가 이러면 | 이 문장을 넣으세요 |
|---|---|
| 한글이 깨짐 | `The Korean labels are garbled. Re-render every label using a font with full Hangul support, keeping the exact character sequences from the previous prompt. Change nothing else.` |
| 브릿지가 안 튐 | `Keep the layout identical but make the 브릿지 box visually dominant: 1.3× larger, filled with the orange accent, white bold title, and a soft shadow. Desaturate the other four boxes to light gray-blue.` |
| 화살표가 꼬임 | `Straighten all connectors into a single horizontal left-to-right flow. No diagonal or crossing lines. Keep every arrow label in place.` |
| 글자가 너무 작음 | `Increase all title text by 40% and all subtitle text by 20%. Remove decorative elements to make room. This will be projected on a large screen.` |
| 없는 라벨이 생김 | `Remove every text element that is not in this list: [필요한 라벨 전부 나열]. Do not add explanatory captions.` |
| 여백이 답답함 | `Add 15% more padding around the whole diagram and increase the gap between service boxes. Do not resize the boxes themselves.` |
| 흑백 논문 버전 필요 | `Convert to a black-and-white version for print. Replace color coding with line weight and fill patterns: 브릿지 = solid black fill with white text, safety callout = diagonal hatch fill, others = white fill with black outline. Keep all labels identical.` |

---

## 스케치를 함께 올릴 때 (이미지 입력 지원 툴)

손그림을 첨부하고 아래를 프롬프트로 넣습니다.

```
Use the attached hand-drawn sketch ONLY as the layout reference: box positions,
box count, and arrow directions. Redraw it as a clean flat-vector presentation
diagram in the style described below, replacing my handwriting with typeset Korean
text. Do not preserve any sketchy stroke texture, paper grain, or pencil shading.
Do not invent components that are absent from the sketch.

[여기에 PROMPT 1의 STYLE / TEXT RULES 단락을 이어 붙이세요]
```

---

## 라벨 원문 대조표 (툴이 글자를 흘렸을 때 확인용)

| 위치 | 정확한 라벨 |
|---|---|
| 입력 | 어르신 / 안부 전화 (음성) |
| ⓪ | 메인 서버 / 통화 소유 · 대화 상태 / :8002 |
| ④ | 케어콜 봇 / 대화 · 의도 분석 (Gemini) |
| 연결 | 분석 결과 JSON (계약) |
| ① | 브릿지 / 케어콜 ↔ DRT 접착제 / 게이트 · 검색어 · 좌표 · 호출 · 문장 · 문자 |
| 연결 | HTTP /api/plan · /api/reservations |
| ② | DRT 서비스 / 정류장 · 경로 · 목적지 · 예약 / :8001 |
| 연결 | HTTP POST /calls |
| ③ | 가상 DRT 서버 / 배차 · 차량 추적 · 조회 페이지 / :8000 |
| 출력 | 실시간 조회 링크 / 어르신 · 보호자 문자 |
| 콜아웃 | 안전 게이트 — DRT 호출 차단 / 응급 표현 감지 · 어르신이 거절 · 차량 호출 동의 없음 · 목적지 미확정 · 위치정보 동의 없음 |

---

## 캡션 초안 (슬라이드 하단 / 논문 Figure 1)

> **그림 1.** 케어콜–DRT 통합 구조. 네 서비스는 같은 저장소에 있으나 서로를 import하지
> 않고 HTTP로만 통신하며, 브릿지는 케어콜 분석기의 **출력 JSON만을 계약**으로 삼는다.
> 안전 게이트를 통과하지 못한 대화는 어떤 경우에도 DRT API를 호출하지 않는다.
