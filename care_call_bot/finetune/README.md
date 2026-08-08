# Mi:dm 2.0 파인튜닝 — 복지 분야 콜센터 상담데이터 (AI Hub #470)

목표: [AI Hub 복지 분야 콜센터 상담데이터](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=470)
(대학병원·광역이동지원센터·정신건강복지센터 콜센터 상담 녹음 + 전사 JSON, 음성 2,945시간/323GB,
전사 226만 문장/약 20GB)의 **전사 텍스트만** 소규모로 뽑아 `Midm-2.0-Mini-Instruct`를 LoRA로
가볍게 파인튜닝합니다. 이 macOS 로컬(Apple Silicon, MPS) 환경 기준입니다.

음성(WAV)은 파인튜닝에 쓰지 않으므로 다운로드하지 않습니다. 라벨링데이터(JSON 전사)만 받으세요.

## 0. 왜 제가 직접 데이터를 못 받아오는가

AI Hub는 로그인 + 이용정책/보안서약서 동의 + 데이터 신청 승인을 거쳐야 다운로드가 가능하고,
"내국인만 신청 가능"이라는 제한도 있습니다. 이 절차는 본인 명의 계정으로만 할 수 있어서
제가 대신 진행할 수 없습니다. 아래 절차를 직접 밟아주세요.

## 1. AI Hub 데이터 신청 및 다운로드

1. https://aihub.or.kr 회원가입/로그인
2. 위 데이터셋 페이지에서 "데이터 신청" → 이용목적 작성 → 승인 대기 (보통 즉시~수 시간)
3. 승인 후 AI Hub 공식 다운로드 도구 `aihubshell` 설치

   ```bash
   curl -o aihubshell "https://api.aihub.or.kr/api/aihubshell.do"
   chmod +x aihubshell
   ```

4. 로그인 후 데이터셋 트리(파일키 목록) 확인 — 정확한 옵션명은 버전에 따라 다를 수 있으니
   `./aihubshell -help`로 최신 사용법을 꼭 확인하세요.

   ```bash
   ./aihubshell -mode l -datasetkey 470
   ```

5. **라벨링데이터(JSON) 폴더 중 일부 파일키만** 선택해서 다운로드하세요 (원천데이터=WAV는 제외).
   보통 기관별(대학병원/광역이동지원센터/정신건강복지센터) · Training/Validation으로 나뉘어
   있으니, 우선 Validation 쪽 라벨링데이터 1~2개 zip 정도만 받아도 소규모 샘플 학습에 충분합니다.

   ```bash
   ./aihubshell -mode d -datasetkey 470 -filekey <라벨링데이터_파일키>
   ```

6. 받은 zip을 풀어서 이 폴더에 둡니다.

   ```bash
   mkdir -p finetune/data/raw
   unzip <다운로드파일>.zip -d finetune/data/raw
   ```

## 2. 실제 JSON 구조 확인

AI Hub 데이터셋마다 JSON 스키마가 조금씩 다르므로, 먼저 구조를 직접 확인합니다.

```bash
source .venv/bin/activate
python finetune/inspect_sample.py finetune/data/raw
```

출력된 키 구조를 보고 `finetune/prepare_dataset.py` 상단의 `SPEAKER_KEYS` / `TEXT_KEYS`
후보 목록에 실제 키 이름이 없다면 추가해주세요 (자동 탐지가 안 맞을 경우에만).

## 3. 학습 데이터 변환

```bash
python finetune/prepare_dataset.py finetune/data/raw --out finetune/data/train.jsonl --max-samples 3000
```

콜센터 상담사↔내담자 발화를 이 프로젝트의 "다솜이" 케어콜 페르소나에 맞춰
system/user/assistant 멀티턴 대화 포맷(JSONL)으로 변환합니다.
(내담자=user, 상담사=assistant로 매핑)

## 4. LoRA 파인튜닝 (MPS)

```bash
pip install -r requirements.txt   # peft, datasets 추가됨
python finetune/train_lora.py --data finetune/data/train.jsonl --epochs 3
```

결과 어댑터는 `finetune/output/midm-lora/`에 저장됩니다. 로컬 Apple Silicon(MPS)이라
샘플 수천 건 기준으로도 시간이 꽤 걸릴 수 있습니다 (수십 분~수 시간, 샘플 수에 비례).

## 5. 파인튜닝된 모델과 대화

```bash
python finetune/chat_finetuned.py
```

기본 베이스 모델(`Midm-2.0-Mini-Instruct`) + 방금 학습한 LoRA 어댑터를 얹어 터미널에서 대화합니다.
