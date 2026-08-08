# 어르신 안부 케어콜 챗봇 (Mi:dm 2.0)

"LLM 기반 어르신 상담 & DRT 호출" 서비스 중 **LLM이 어르신께 먼저 말을 걸어 안부를 확인하는 파트**의 프롬프트와 데모입니다.
음성(TTS) 케어콜을 전제로 설계했습니다. (DRT 이동 의도 감지·호출 파트는 별도 담당)

## 구성

| 파일 | 설명 |
|---|---|
| `prompts/system_prompt.txt` | 케어콜 페르소나 "다솜이" 시스템 프롬프트 (Few-shot 예시 대화 내장) |
| `chat_demo.py` | Mi:dm 2.0으로 터미널에서 대화해 보는 데모 스크립트 (`--voice`로 마이크 음성 입력 지원) |

## 사용 모델

- [K-intelligence/Midm-2.0-Mini-Instruct](https://huggingface.co/K-intelligence/Midm-2.0-Mini-Instruct) (2B, 기본값)
- [K-intelligence/Midm-2.0-Base-Instruct](https://huggingface.co/K-intelligence/Midm-2.0-Base-Instruct) (12B, `--base` 옵션)

## 실행

```bash
# 가상환경 (Python 3.12 권장 — 3.14는 torch/ctranslate2 호환 문제 있음)
uv venv --python 3.12 .venv        # uv가 없으면: python3.12 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
source .venv/bin/activate

python chat_demo.py          # Mini (2B), 키보드 입력
python chat_demo.py --base   # Base (12B)
```

봇이 먼저 인사를 건네고, `종료`를 입력하면 대화가 끝납니다.

### 음성 입력 (STT)

STT는 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)(로컬 Whisper, 오프라인·무료)를 사용하며 requirements.txt에 포함되어 있습니다.

```bash
python chat_demo.py --voice                    # 마이크로 말하기
python chat_demo.py --voice --stt-model base   # 더 가벼운 STT 모델 (tiny/base/small/medium)
```

- `(말씀하세요...)`가 뜨면 말하면 되고, **말을 멈추고 1.5초가 지나면 자동으로 녹음이 끝나** 인식 결과가 대화에 들어갑니다.
- macOS는 처음 실행 시 터미널(또는 VSCode)에 **마이크 접근 권한**을 허용해야 합니다.
- 주변이 시끄러워 녹음이 안 끊기면 `chat_demo.py`의 `SILENCE_THRESHOLD` 값을 올려 보세요.

### 음성 출력 (TTS)

다솜이의 답변은 macOS 내장 `say` 명령(한국어 음성 **Yuna**)으로 읽어줍니다. 별도 설치가 필요 없고, 끄려면 `--no-tts` 옵션을 주면 됩니다.

### 대화 종료

- **자동 종료**: 어르신이 "이제 끊을게", "들어가 봐야겠다"처럼 대화를 마치는 말을 하면, 모델이 작별 인사 뒤에 `[통화종료]` 표식을 붙이도록 프롬프트에 지시되어 있고, 코드가 이를 감지해 통화를 끝냅니다 (표식은 화면·음성에 노출되지 않음).
- **수동 종료**: "종료"라고 말하거나 입력, 또는 Ctrl+C.

## 프롬프트 설계 요점

1. **음성 전제 규칙** — 한 번에 1~2문장, 질문은 하나만, 이모지·특수문자·영어 금지 (TTS로 읽히기 때문)
2. **대화 흐름 가이드** — 인사 → 식사 → 수면 → 건강 → 기분 → 나들이 순서를 *참고용*으로 제시. 어르신이 꺼낸 주제를 우선 경청
3. **Few-shot 예시 내장** — 중소형 모델은 규칙 나열보다 예시 대화로 말투를 잡는 것이 안정적이라, 모범 대화 3개를 프롬프트에 포함
4. **안전 규칙** — 의료 진단·약 추천 금지(병원 방문 권유로 대체), 우울·외로움 호소 시 공감 우선, 금전 관련 대화 금지
5. **첫인사 고정** — 첫 발화는 프롬프트가 아닌 코드에서 고정 멘트로 주입해 도입부가 항상 일정하게 시작

## 예시 대화

```
다솜이: 안녕하세요, 어르신. 말벗 다솜이예요. 요즘 잘 지내고 계세요?
어르신: 그냥 그렇지 뭐.
다솜이: 그러셨어요. 오늘 점심은 챙겨 드셨어요?
어르신: 응, 김치찌개 해 먹었어.
다솜이: 김치찌개 드셨구나, 맛있으셨겠어요. 요즘 입맛은 좀 어떠세요?
```
