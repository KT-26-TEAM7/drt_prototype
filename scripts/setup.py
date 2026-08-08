"""네 덩어리를 한 번에 준비한다.

각 프로젝트의 가상환경을 만들고, 의존성을 설치하고, 데이터베이스를 초기화하고,
서로를 가리키도록 설정까지 맞춘다. 끝나면 `py scripts/run_stack.py`로 바로 뜬다.

    py scripts/setup.py                    # 기본 (몇 분 걸림)
    py scripts/setup.py --force            # 가상환경을 지우고 다시 만듦
    py scripts/setup.py --full-care-call   # 케어콜 로컬 모델(torch 등)까지 설치 (수 GB)
    py scripts/setup.py --check            # 설치하지 않고 상태만 확인

이미 되어 있는 단계는 건너뛰므로 여러 번 실행해도 안전하다.
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]

BRIDGE_DIR = PROJECT_DIR
SERVICE_DIR = PROJECT_DIR / "drt_service"
DISPATCH_DIR = PROJECT_DIR / "mock_drt_server"
CARE_CALL_DIR = PROJECT_DIR / "care_call_bot"

IS_WINDOWS = platform.system() == "Windows"


def venv_python(project_dir: Path) -> Path:
    if IS_WINDOWS:
        return project_dir / ".venv" / "Scripts" / "python.exe"
    return project_dir / ".venv" / "bin" / "python"


def step(message: str) -> None:
    print(f"\n[{message}]", flush=True)


def info(message: str) -> None:
    print(f"    {message}", flush=True)


def run(command: list[str], cwd: Path, what: str) -> None:
    info(f"{what} ...")
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        raise SystemExit(
            f"\n실패: {what}\n  명령: {' '.join(command)}\n  위치: {cwd}\n"
            + "\n".join(f"  {line}" for line in tail[-12:])
        )


def ensure_venv(project_dir: Path, label: str, force: bool) -> Path:
    python = venv_python(project_dir)
    if force and (project_dir / ".venv").exists():
        info("기존 가상환경 삭제")
        shutil.rmtree(project_dir / ".venv")
        python = venv_python(project_dir)
    if python.exists():
        info("가상환경 있음 (건너뜀)")
        return python
    run([sys.executable, "-m", "venv", ".venv"], project_dir, f"{label} 가상환경 생성")
    return python


def pip_install(python: Path, project_dir: Path, args: list[str], what: str) -> None:
    run([str(python), "-m", "pip", "install", "-q", "--disable-pip-version-check", *args],
        project_dir, what)


def ensure_env_file(project_dir: Path) -> None:
    env_path = project_dir / ".env"
    example = project_dir / ".env.example"
    if env_path.exists() or not example.exists():
        return
    shutil.copyfile(example, env_path)
    info(".env 생성 (.env.example 복사)")


def get_env_value(env_path: Path, key: str) -> str:
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def set_env_default(env_path: Path, key: str, value: str) -> bool:
    """.env에 값이 **비어 있을 때만** 채운다.

    사용자가 한 번 넣은 키나 주소를 setup을 다시 돌렸다고 덮어쓰면 안 되므로,
    이미 값이 있으면 그대로 둔다.
    """
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, current = stripped.partition("=")
        if name.strip() != key:
            continue
        if current.strip():
            return False  # 이미 값이 있다 — 건드리지 않는다
        lines[index] = f"{key}={value}"
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _key_state(env_path: Path, key: str) -> str:
    """키가 들어 있는지만 알려 준다. 값은 절대 출력하지 않는다."""
    if not env_path.exists():
        return "파일 없음"
    value = get_env_value(env_path, key)
    if not value:
        return "비어 있음"
    return f"설정됨 ({len(value)}자)"


def check_only() -> None:
    print("설치 상태")
    print("-" * 58)
    rows = [
        ("브릿지", BRIDGE_DIR, BRIDGE_DIR / "bridge" / "orchestrator.py"),
        ("drt_service", SERVICE_DIR, SERVICE_DIR / "app" / "main.py"),
        ("배차 서버", DISPATCH_DIR, DISPATCH_DIR / "app" / "main.py"),
        ("케어콜 분석기", CARE_CALL_DIR, CARE_CALL_DIR / "drt_analyzer.py"),
    ]
    # 한글은 폭이 두 배라 자릿수 맞추기가 어긋난다. 정렬 대신 구분자로 읽히게 둔다.
    for label, directory, marker in rows:
        exists = "있음" if marker.exists() else "없음"
        venv = "있음" if venv_python(directory).exists() else "없음"
        print(f"  {label} — 코드 {exists} / 가상환경 {venv}")
    print(f"  drt_service DB — {'있음' if (SERVICE_DIR / 'db.sqlite3').exists() else '없음'}")
    print(f"  배차 서버 DB — {'있음' if (DISPATCH_DIR / 'mock_drt.db').exists() else '없음'}")

    print()
    print("설정 (값은 표시하지 않습니다)")
    print("-" * 58)
    print(f"  TMAP 키 · drt_service — {_key_state(SERVICE_DIR / '.env', 'TMAP_APP_KEY')}")
    print(f"  TMAP 키 · 배차 서버   — {_key_state(DISPATCH_DIR / '.env', 'TMAP_APP_KEY')}")
    print(f"  Gemini 키 · 케어콜    — {_key_state(CARE_CALL_DIR / '.env', 'GEMINI_KEY')}")
    print(f"  릴레이 토큰 · drt_service — {_key_state(SERVICE_DIR / '.env', 'RELAY_API_TOKEN')}")
    print(f"  릴레이 토큰 · 브릿지      — {_key_state(BRIDGE_DIR / '.env', 'RELAY_API_TOKEN')}")

    # 서로 맞아야 하는 값들이 어긋나 있으면 알려 준다.
    problems = []
    service_token = get_env_value(SERVICE_DIR / ".env", "RELAY_API_TOKEN")
    bridge_token = get_env_value(BRIDGE_DIR / ".env", "RELAY_API_TOKEN")
    if service_token != bridge_token:
        problems.append("릴레이 토큰이 drt_service와 브릿지에서 서로 다릅니다 (401이 납니다)")
    service_tmap = get_env_value(SERVICE_DIR / ".env", "TMAP_APP_KEY")
    dispatch_tmap = get_env_value(DISPATCH_DIR / ".env", "TMAP_APP_KEY")
    if service_tmap and not dispatch_tmap:
        problems.append("배차 서버에 TMAP 키가 없어 차량 경로가 직선으로 표시됩니다")
    if not get_env_value(SERVICE_DIR / ".env", "DRT_SERVER_BASE_URL"):
        problems.append("drt_service의 DRT_SERVER_BASE_URL이 비어 MOCK 배차로 동작합니다")

    print("-" * 58)
    if problems:
        for item in problems:
            print(f"  ! {item}")
        print("  → py scripts/setup.py 를 다시 실행하면 맞춰집니다.")
    else:
        print("  설정이 서로 맞습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="네 덩어리를 한 번에 준비한다")
    parser.add_argument("--force", action="store_true", help="가상환경을 지우고 다시 만든다")
    parser.add_argument("--full-care-call", action="store_true",
                        help="케어콜 로컬 모델(torch, faster-whisper 등)까지 설치 (수 GB)")
    parser.add_argument("--check", action="store_true", help="설치하지 않고 상태만 확인")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)

    if args.check:
        check_only()
        return

    for directory in (SERVICE_DIR, DISPATCH_DIR, CARE_CALL_DIR):
        if not directory.exists():
            raise SystemExit(f"폴더가 없습니다: {directory}")

    print("=" * 58)
    print("케어콜 → DRT 통합 환경 준비")
    print("=" * 58)
    print("의존성을 내려받으므로 몇 분 걸립니다.")

    # ── 1. 배차 서버 ────────────────────────────────────────────────────
    step("1/4 배차 서버 (mock_drt_server)")
    python = ensure_venv(DISPATCH_DIR, "배차 서버", args.force)
    pip_install(python, DISPATCH_DIR, ["-r", "requirements.txt"], "의존성 설치")
    ensure_env_file(DISPATCH_DIR)
    if not (DISPATCH_DIR / "mock_drt.db").exists():
        run([str(python), "scripts/initialize_db.py"], DISPATCH_DIR, "데이터베이스 초기화")
    else:
        info("데이터베이스 있음 (건너뜀)")

    # ── 2. drt_service ──────────────────────────────────────────────────
    step("2/4 drt_service")
    python = ensure_venv(SERVICE_DIR, "drt_service", args.force)
    requirements = "requirements-dev.txt" if (SERVICE_DIR / "requirements-dev.txt").exists() else "requirements.txt"
    pip_install(python, SERVICE_DIR, ["-r", requirements], "의존성 설치 (모델 라이브러리 포함, 오래 걸림)")
    ensure_env_file(SERVICE_DIR)
    if not (SERVICE_DIR / "db.sqlite3").exists():
        run([str(python), "-m", "app.cli", "init-db"], SERVICE_DIR, "데이터베이스 초기화")
    else:
        info("데이터베이스 있음 (건너뜀)")

    # ── 3. 브릿지 ───────────────────────────────────────────────────────
    # 메인 서버(main_server/)는 브릿지를 직접 import하므로 같은 가상환경을 쓴다.
    step("3/5 브릿지 · 메인 서버")
    python = ensure_venv(BRIDGE_DIR, "브릿지", args.force)
    pip_install(python, BRIDGE_DIR, ["-r", "requirements.txt"], "의존성 설치")
    pip_install(python, BRIDGE_DIR, ["-r", "requirements-analyzer.txt"],
                "분석기 연동용 의존성 설치")
    ensure_env_file(BRIDGE_DIR)

    # ── 4. 케어콜 분석기 ────────────────────────────────────────────────
    step("4/5 케어콜 분석기 (care_call_bot)")
    python = ensure_venv(CARE_CALL_DIR, "케어콜", args.force)
    if args.full_care_call:
        pip_install(python, CARE_CALL_DIR, ["-r", "requirements.txt"],
                    "전체 설치 (torch 등, 수 GB — 매우 오래 걸림)")
    else:
        # 의도 분석(drt_analyzer)과 Gemini 대화 데모에 필요한 것만 넣는다.
        # 로컬 Mi:dm 대화(chat_demo.py)를 쓰려면 --full-care-call로 다시 실행한다.
        pip_install(python, CARE_CALL_DIR, ["google-genai", "python-dotenv"],
                    "의도 분석·Gemini 데모용 의존성 설치")
        info("로컬 Mi:dm 대화가 필요하면 --full-care-call로 다시 실행하세요.")
    # 분석기는 경로 없이 load_dotenv()를 부르기 때문에, 이 파일이 없으면 상위 폴더의
    # .env를 대신 읽어 GEMINI_KEY를 넣을 곳이 없어진다. 빈 템플릿을 만들어 준다.
    if not (CARE_CALL_DIR / ".env").exists():
        (CARE_CALL_DIR / ".env").write_text(
            "# 케어콜 대화·의도 분석 설정\n"
            "# Gemini를 쓰려면 발급받은 키를 넣으세요.\n"
            "# 비워 두면 분석기가 규칙 기반으로만 동작합니다(경고 후 계속 진행).\n"
            "GEMINI_KEY=\n",
            encoding="utf-8",
        )
        info(".env 생성 (GEMINI_KEY를 넣을 자리)")

    # ── 5. 설정 맞추기 ──────────────────────────────────────────────────
    # 설치가 모두 끝난 뒤에 한다. 값이 비어 있을 때만 채우므로, 한 번 넣은 키는
    # setup을 다시 돌려도 그대로 남는다.
    step("5/5 설정 맞추기")
    if set_env_default(SERVICE_DIR / ".env", "DRT_SERVER_BASE_URL", "http://127.0.0.1:8000"):
        info("drt_service: 배차 서버 주소 설정")

    service_token = get_env_value(SERVICE_DIR / ".env", "RELAY_API_TOKEN")
    if service_token and set_env_default(BRIDGE_DIR / ".env", "RELAY_API_TOKEN", service_token):
        info("브릿지: 릴레이 토큰을 drt_service와 맞춤")

    # TMAP 키를 두 군데 넣지 않아도 되게 한다. 배차 서버는 이 키로 차량 주행 경로를
    # 그린다(없으면 직선). 같은 키를 쓰므로 호출량도 그만큼 늘어난다.
    tmap_key = get_env_value(SERVICE_DIR / ".env", "TMAP_APP_KEY")
    if tmap_key and set_env_default(DISPATCH_DIR / ".env", "TMAP_APP_KEY", tmap_key):
        info("배차 서버: TMAP 키를 drt_service와 맞춤 (경로를 실제 도로로 그림)")

    missing = []
    if not tmap_key:
        missing.append("drt_service/.env 의 TMAP_APP_KEY (비우면 모의 장소·직선 경로)")
    if not get_env_value(CARE_CALL_DIR / ".env", "GEMINI_KEY"):
        missing.append("care_call_bot/.env 의 GEMINI_KEY (비우면 규칙 기반 분석만)")

    print()
    print("=" * 58)
    print("준비 완료")
    print("=" * 58)
    if missing:
        print("아직 비어 있는 키 (선택 사항, 넣으면 계속 유지됩니다):")
        for item in missing:
            print(f"  - {item}")
        print()
    print("바로 확인해 보세요:")
    print("  py scripts/setup.py --check                                    (설정 점검)")
    print("  py scripts/run_handoff.py --all --offline --reply \"응 불러줘\"   (서버 없이)")
    print("  py scripts/run_stack.py                                        (두 서버 띄우기)")


if __name__ == "__main__":
    main()
