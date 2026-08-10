# 시스템 아키텍처 그림 — 학술논문용 프롬프트

논문 게재용 / 한글 라벨 / 영문 지시문.
발표 슬라이드용 컬러 버전은 [figure_prompt_architecture.md](figure_prompt_architecture.md)에 있습니다.

> **논문용이라 달라진 점**: 색 대신 선 굵기·채움 패턴으로 구분, 그림자·아이콘 제거,
> 흑백 인쇄 견딤, 2단 편집 컬럼 폭(약 88mm)에서도 라벨이 읽히는 글자 크기,
> 그림 안에는 제목을 넣지 않음(캡션은 본문 조판에서 붙임).

---

## PROMPT 1 — 메인 (전체 붙여넣기)

```
Create a scientific figure for an academic paper: a system architecture diagram.
Flat 2D vector line art, grayscale, publication quality. Aspect ratio 16:7,
intended to be printed at double-column width (about 180mm) in a journal.

SUBJECT
A voice-based elderly care-call AI that detects a travel intention during a routine
check-in phone call and dispatches a Demand-Responsive Transit (DRT) vehicle. Four
services communicate over HTTP only; they never import each other's code.

LAYOUT — a single left-to-right pipeline. Six elements in one horizontal row:
one actor at each end and four service boxes between them. All boxes share the same
height and vertical centerline.

[far left]  A minimal line-art icon of a telephone handset. Label below: 어르신
   │  arrow, label above the line: 안부 전화 (음성)
   ▼
[BOX ⓪]  메인 서버
         second line, smaller: 통화 소유 · 대화 상태
         bottom-right corner, monospace: :8002
   │  arrow label: 대화 턴
   ▼
[BOX ④]  케어콜 봇
         second line: 대화 · 의도 분석 (Gemini)
   │  arrow label: 분석 결과 JSON (계약)
   ▼
[BOX ①]  브릿지
         second line: 케어콜 ↔ DRT 접착제
         Inside the box, a horizontal strip of six small compartments separated by
         thin vertical rules, each containing one short label:
            게이트 | 검색어 | 좌표 | 호출 | 문장 | 문자
         Distinguish this box using LINE WEIGHT ONLY: draw its outline at roughly
         double the stroke width of the other boxes. Do not fill it with color and
         do not add a shadow.
   │  arrow label: HTTP  /api/plan · /api/reservations
   ▼
[BOX ②]  DRT 서비스
         second line: 정류장 · 경로 · 목적지 · 예약
         corner: :8001
   │  arrow label: HTTP  POST /calls
   ▼
[BOX ③]  가상 DRT 서버
         second line: 배차 · 차량 추적 · 조회 페이지
         corner: :8000
   │  arrow label: 실시간 조회 링크
   ▼
[far right] A minimal line-art smartphone outline containing a small map-pin glyph.
            Label below: 어르신 · 보호자 문자

INSET — one additional box placed below the 브릿지 box, connected to it by a short
vertical DASHED line. Same grayscale treatment; fill it with a light diagonal hatch
pattern to mark it as a constraint rather than a data path.
   Heading: 안전 게이트 — DRT 호출 차단
   Five short items, set as a compact bulleted list:
     응급 표현 감지 / 어르신이 거절 / 차량 호출 동의 없음 /
     목적지 미확정 / 위치정보 동의 없음

STYLE — ACADEMIC
- Strictly grayscale: white fills, black strokes, at most two intermediate grays
  (about 20% and 45%) for secondary text and the hatch pattern. No color anywhere.
- Encode emphasis with line weight and fill pattern, never with hue, so the figure
  survives black-and-white printing and is legible to colorblind readers.
- Thin uniform strokes (about 1pt for boxes, 0.75pt for connectors). Slightly
  rounded corners or square corners, consistent throughout.
- Arrows: straight orthogonal connectors with small open arrowheads. No curves,
  no crossings, no bidirectional arrows.
- No drop shadows, no gradients, no 3D, no glossy effects, no decorative icons
  beyond the two minimal glyphs specified above.
- Typography: a single clean sans-serif with full Hangul support, used at three
  sizes only — box title, secondary line, arrow label. Arrow labels sit directly
  above their connector, horizontally, never rotated.
- Generous uniform white space; equal gaps between all boxes. Transparent or white
  background, no outer frame, no page border.
- Do NOT draw a figure title or a caption inside the image. The caption is set by
  the manuscript typesetter.

TEXT RULES — CRITICAL
- Reproduce every label EXACTLY as given, in Korean, with no translation, no
  transliteration, no paraphrase, and no additional words.
- The only Latin/ASCII text permitted: HTTP, JSON, DRT, Gemini, /api/plan,
  /api/reservations, POST /calls, :8000, :8001, :8002.
- Do not add watermarks, signatures, legends, or annotations that are not listed.
```

---

## NEGATIVE PROMPT (분리 입력란이 있는 툴용)

```
color, colored fills, gradient, neon, 3D render, isometric, photorealistic,
drop shadow, glossy, hand-drawn sketchy stroke, marketing infographic style,
stock-photo people, decorative clip-art icons, cluttered background, dark mode,
garbled or mojibake Korean text, random English words, figure title inside image,
caption text inside image, watermark, signature, outer frame border
```

---

## 수정 프롬프트 (1차 결과 보고 골라 쓰기)

한 번에 하나씩만 넣어야 결과가 안정적입니다.

| 결과가 이러면 | 이 문장을 넣으세요 |
|---|---|
| 한글이 깨짐 | `The Korean labels are garbled. Re-render every label with a font that has complete Hangul coverage, preserving the exact character sequences from the previous prompt. Change nothing else.` |
| 색이 들어감 | `Remove all color. Convert to strict grayscale: white fills, black strokes, gray only for secondary text and the hatch pattern. Keep the layout and all labels identical.` |
| 브릿지 강조가 약함 | `Keep everything identical but increase the outline stroke weight of the 브릿지 box to roughly twice that of the other boxes. Do not add fill, color, or shadow.` |
| 화살표가 꼬임 | `Straighten every connector into a single horizontal left-to-right flow with orthogonal segments only. No diagonals, no crossings. Keep each arrow label above its own connector.` |
| 라벨이 인쇄에 작음 | `Increase all text sizes by 30% and enlarge the boxes to fit. Target legibility at 180mm printed width. Remove any non-essential graphic element to make room.` |
| 없는 라벨이 생김 | `Delete every text element that does not appear in this list: [라벨 대조표 항목 전부 나열]. Do not add explanatory captions or legends.` |
| 제목이 그림 안에 들어감 | `Remove the figure title and any caption text from inside the image. The image must contain only the diagram itself.` |
| 1단 컬럼용이 필요 | `Reflow into a vertical layout for single-column width (about 88mm): stack the four service boxes top to bottom with the actors at top and bottom. Keep all labels, arrow labels, and the safety inset unchanged.` |

---

## 스케치를 함께 올릴 때 (이미지 입력 지원 툴)

손그림을 첨부하고 아래를 프롬프트로 넣습니다.

```
Use the attached hand-drawn sketch ONLY as a layout reference: the number of boxes,
their positions, and the arrow directions. Redraw it as a clean grayscale vector
figure suitable for an academic journal, replacing my handwriting with typeset
Korean text. Remove all pencil texture, paper grain, and uneven strokes. Do not add
any component that is absent from the sketch, and do not omit any that is present.

[여기에 PROMPT 1의 STYLE / TEXT RULES 단락을 이어 붙이세요]
```

---

## 라벨 원문 대조표 (툴이 글자를 흘렸을 때 확인용)

| 위치 | 정확한 라벨 |
|---|---|
| 입력 | 어르신 / 안부 전화 (음성) |
| ⓪ | 메인 서버 / 통화 소유 · 대화 상태 / :8002 |
| 연결 | 대화 턴 |
| ④ | 케어콜 봇 / 대화 · 의도 분석 (Gemini) |
| 연결 | 분석 결과 JSON (계약) |
| ① | 브릿지 / 케어콜 ↔ DRT 접착제 / 게이트 · 검색어 · 좌표 · 호출 · 문장 · 문자 |
| 연결 | HTTP /api/plan · /api/reservations |
| ② | DRT 서비스 / 정류장 · 경로 · 목적지 · 예약 / :8001 |
| 연결 | HTTP POST /calls |
| ③ | 가상 DRT 서버 / 배차 · 차량 추적 · 조회 페이지 / :8000 |
| 연결 | 실시간 조회 링크 |
| 출력 | 어르신 · 보호자 문자 |
| 인셋 | 안전 게이트 — DRT 호출 차단 / 응급 표현 감지 · 어르신이 거절 · 차량 호출 동의 없음 · 목적지 미확정 · 위치정보 동의 없음 |

---

## 제출 전 점검

- [ ] 흑백으로 인쇄해서 브릿지 강조가 여전히 구분되는가 (색 없이 선 굵기만으로)
- [ ] 88mm로 축소했을 때 화살표 라벨이 읽히는가
- [ ] 그림 안에 "Figure 1" 같은 제목이 남아 있지 않은가
- [ ] 벡터(PDF/SVG/EPS)로 받았는가. 래스터만 가능하면 최소 600 dpi
- [ ] 라벨이 위 대조표와 글자 단위로 일치하는가

---

## 캡션 초안

> **그림 1.** 케어콜–DRT 통합 구조. 네 서비스는 같은 저장소에 있으나 서로를 import하지
> 않고 HTTP로만 통신하며, 브릿지(굵은 테두리)는 케어콜 분석기의 **출력 JSON만을 계약**으로
> 삼는다. 빗금 친 안전 게이트를 통과하지 못한 대화는 어떤 경우에도 DRT API를 호출하지 않는다.

> **Fig. 1.** Architecture of the care-call–DRT integration. The four services reside in
> one repository but never import one another; all inter-service communication is over
> HTTP. The bridge (bold outline) treats the analyzer's output JSON as its sole contract.
> Conversations that fail the hatched safety gate never reach the DRT API.
