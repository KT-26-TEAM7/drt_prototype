"""배차 서버·drt_service·메인 서버를 올바른 포트로 함께 띄운다.

배차 서버와 drt_service는 기본 포트가 8000으로 같고, 배차 서버의 조회 링크 주소
(`TRACKING_BASE_URL`)는 실제 리슨 포트와 **별개의 설정**이다. 이 둘이 어긋나면
어르신이 문자로 받은 링크가 엉뚱한 서버를 가리키는데, 그 증상은 링크를 눌러 봐야
드러난다.

그래서 이 스크립트는 포트 하나만 받고 나머지를 전부 거기서 파생시킨다.

    배차 포트 8000 ─┬─► 배차 서버 리슨 포트
                    ├─► TRACKING_BASE_URL  = http://localhost:8000/tracking
                    └─► DRT_SERVER_BASE_URL = http://127.0.0.1:8000  (drt_service가 볼 주소)

실행:
    py scripts/run_stack.py                 # 배차 8000, drt_service 8001
    py scripts/run_stack.py --dispatch-port 8100 --service-port 8101
    py scripts/run_stack.py --check-only    # 이미 떠 있는 스택만 점검

Ctrl+C로 띄운 서버를 모두 내린다(기본 세 개, --no-main이면 두 개).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge import preflight  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]

# 네 덩어리가 이 폴더 안에 함께 있다. 다른 곳에 둔 것을 쓰려면 인자나 환경변수로 알려 준다.
DEFAULT_SERVICE_DIR = PROJECT_DIR / "drt_service"
DEFAULT_DISPATCH_DIR = PROJECT_DIR / "mock_drt_server"


def read_env_value(env_path: Path, key: str) -> str:
    """.env에서 값 하나만 읽는다. 릴레이 토큰을 사전 점검에 쓰기 위한 것이며,
    값은 화면에 출력하지 않는다."""
    if not env_path.exists():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def venv_python(project_dir: Path) -> Path | None:
    candidates = (
        project_dir / ".venv" / "Scripts" / "python.exe",  # Windows
        project_dir / ".venv" / "bin" / "python",          # macOS/Linux
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def wait_until_ready(check, timeout_s: float = 40.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check().ok:
            return True
        time.sleep(0.5)
    return False


def start_server(
    label: str, project_dir: Path, port: int, extra_env: dict[str, str]
) -> subprocess.Popen:
    python = venv_python(project_dir)
    if python is None:
        raise SystemExit(
            f"{label}: 가상환경을 찾지 못했습니다 ({project_dir}\\.venv)\n"
            f"  먼저 만들어 주세요:  py -m venv .venv && .venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        )
    if not (project_dir / "app" / "main.py").exists():
        raise SystemExit(f"{label}: app/main.py가 없습니다 ({project_dir})")

    env = os.environ.copy()
    env.update(extra_env)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"  {label:<12} 포트 {port}  ({project_dir.name})")
    # run_server.py는 포트가 8000으로 고정되어 있어 uvicorn을 직접 부른다.
    return subprocess.Popen(
        [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(project_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )


def check_main_server(url: str) -> preflight.CheckResult:
    """메인 서버가 응답하는지. 배차 서버·drt_service와 같은 방식으로 점검한다.

    메인 서버는 carecall_drt(+Gemini)를 로딩하느라 다른 둘보다 기동이 느릴 수 있어서,
    이 점검이 없으면 "모두 정상입니다"가 뜬 뒤에도 몇 초간 8002가 응답하지 않을 수 있다.
    """
    name = "메인 서버 응답"
    try:
        status, body = preflight._get(f"{url}/")
    except urllib.error.URLError as error:
        return preflight.CheckResult(name, False, f"{url}에 붙지 못했습니다 ({error.reason})")
    if status != 200:
        return preflight.CheckResult(name, False, f"{url}/ 가 {status}를 돌려줬습니다")
    try:
        root = json.loads(body)
    except ValueError:
        return preflight.CheckResult(name, False, "응답이 JSON이 아닙니다")
    return preflight.CheckResult(
        name, True, f"{root.get('service')} (응답기={root.get('responder')})"
    )


def report(results: list[preflight.CheckResult]) -> bool:
    print()
    print("사전 점검")
    print("-" * 60)
    for result in results:
        mark = "OK  " if result.ok else "실패"
        print(f"  [{mark}] {result.name}: {result.detail}")
        if not result.ok and result.hint:
            print(f"         -> {result.hint}")
    ok = all(result.ok for result in results)
    print("-" * 60)
    print("  모두 정상입니다." if ok else "  문제가 있습니다. 위 안내를 확인하세요.")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="배차 서버 + drt_service를 함께 띄운다")
    parser.add_argument("--dispatch-port", type=int, default=8000)
    parser.add_argument("--service-port", type=int, default=8001)
    parser.add_argument("--main-port", type=int, default=8002,
                        help="메인 서버(통화 처리) 포트. --no-main 으로 끌 수 있습니다")
    parser.add_argument("--no-main", action="store_true", help="메인 서버는 띄우지 않는다")
    parser.add_argument("--service-dir", default=os.getenv("DRT_SERVICE_DIR", str(DEFAULT_SERVICE_DIR)))
    parser.add_argument("--dispatch-dir", default=os.getenv("DISPATCH_DIR", str(DEFAULT_DISPATCH_DIR)))
    parser.add_argument("--token", default=os.getenv("RELAY_API_TOKEN", ""))
    parser.add_argument("--check-only", action="store_true", help="띄우지 않고 점검만 한다")
    args = parser.parse_args()

    # 런처 출력이 뒤늦게 몰려 나오지 않도록 줄 단위로 흘려보낸다.
    sys.stdout.reconfigure(line_buffering=True)

    if args.dispatch_port == args.service_port:
        raise SystemExit("두 서버는 서로 다른 포트를 써야 합니다.")

    service_dir = Path(args.service_dir)
    # 사전 점검이 인증 경로까지 확인하려면 토큰이 필요하다. 값은 출력하지 않는다.
    token = args.token or read_env_value(service_dir / ".env", "RELAY_API_TOKEN")
    if token and not args.token:
        print("drt_service의 .env에서 릴레이 토큰을 읽었습니다.")

    # 포트 하나에서 나머지를 전부 파생시킨다. 이 아래로는 포트가 어긋날 수 없다.
    dispatch_url = f"http://127.0.0.1:{args.dispatch_port}"
    service_url = f"http://127.0.0.1:{args.service_port}"
    tracking_base_url = f"http://localhost:{args.dispatch_port}/tracking"

    if args.check_only:
        raise SystemExit(0 if report(preflight.run_checks(service_url, dispatch_url, token)) else 1)

    ports = [("배차 서버", args.dispatch_port), ("drt_service", args.service_port)]
    if not args.no_main:
        ports.append(("메인 서버", args.main_port))
    for label, port in ports:
        if port_in_use(port):
            raise SystemExit(
                f"포트 {port}이(가) 이미 사용 중입니다({label}로 쓰려던 포트).\n"
                f"  기존 서버를 내리거나 다른 포트를 지정하세요."
            )

    print("서버 시작")
    processes: list[tuple[str, subprocess.Popen]] = []
    try:
        dispatch = start_server(
            "배차 서버", Path(args.dispatch_dir), args.dispatch_port,
            # PORT만 넘긴다. 배차 서버가 이 값에서 조회 링크 주소를 만들기 때문에
            # 리슨 포트와 링크가 어긋날 수 없다. (.env에 TRACKING_BASE_URL을 직접
            # 지정해 두었다면 그쪽이 우선하고, 어긋나면 서버가 기동 시 경고한다.)
            {"PORT": str(args.dispatch_port)},
        )
        processes.append(("배차 서버", dispatch))
        if not wait_until_ready(lambda: preflight.check_dispatch_server(dispatch_url)):
            raise SystemExit("배차 서버가 뜨지 않았습니다. DB 초기화(scripts/initialize_db.py)를 했는지 확인하세요.")

        service = start_server(
            "drt_service", service_dir, args.service_port,
            {"DRT_SERVER_BASE_URL": dispatch_url},
        )
        processes.append(("drt_service", service))
        if not wait_until_ready(lambda: preflight.check_drt_service(service_url, token)):
            raise SystemExit("drt_service가 뜨지 않았습니다.")

        # 메인 서버는 브릿지 가상환경에서 돈다(브릿지를 직접 import하기 때문).
        main_url = f"http://127.0.0.1:{args.main_port}"
        main_started = False
        if not args.no_main:
            main_python = venv_python(PROJECT_DIR)
            if main_python is None:
                print("  메인 서버 건너뜀 — 브릿지 가상환경이 없습니다 (py scripts/setup.py)")
            else:
                env = os.environ.copy()
                env.update({"DRT_BASE_URL": service_url, "PYTHONUTF8": "1",
                            "PYTHONIOENCODING": "utf-8"})
                if token:
                    env["RELAY_API_TOKEN"] = token
                print(f"  {'메인 서버':<12} 포트 {args.main_port}  (main_server)")
                main = subprocess.Popen(
                    [str(main_python), "-m", "uvicorn", "main_server.app:app",
                     "--host", "127.0.0.1", "--port", str(args.main_port)],
                    cwd=str(PROJECT_DIR), env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                )
                processes.append(("메인 서버", main))
                main_started = True
                # care_call_bot 분석기 로딩 때문에 배차 서버·drt_service보다 늦게 뜬다.
                # 여기서 기다리지 않으면 "모두 정상입니다"가 뜬 뒤에도 몇 초간 8002가
                # 연결을 거부해, 바로 이어서 call_demo.py를 돌리면 실패할 수 있다.
                if not wait_until_ready(lambda: check_main_server(main_url), timeout_s=60.0):
                    print(f"  메인 서버가 제 시간 안에 뜨지 않았습니다({main_url}). "
                          "분석기 로딩이 오래 걸릴 수 있으니 잠시 후 다시 확인하세요.")

        checks = preflight.run_checks(service_url, dispatch_url, token)
        if main_started:
            checks.append(check_main_server(main_url))
        ok = report(checks)
        print()
        if main_started:
            print(f"통화 시연: py scripts\\call_demo.py --server http://127.0.0.1:{args.main_port}")
            print()
        print("이제 다른 터미널에서 실행해 보세요:")
        print("  .venv\\Scripts\\python.exe scripts\\run_handoff.py "
              "samples\\03_exact_library_scheduled.json --reply \"응 불러줘\"")
        print("  .venv\\Scripts\\python.exe scripts\\verify_dispatch.py")
        print()
        print(f"Ctrl+C로 {len(processes)}개 서버를 함께 내립니다.")
        if not ok:
            print("(점검에 실패한 항목이 있습니다.)")

        while all(process.poll() is None for _, process in processes):
            time.sleep(1)
        for label, process in processes:
            if process.poll() is not None:
                print(f"\n{label}가 종료되었습니다(코드 {process.returncode}).")
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        for label, process in reversed(processes):
            if process.poll() is None:
                print(f"  {label} 종료 중...")
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    main()
