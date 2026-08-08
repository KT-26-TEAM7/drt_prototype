"""개발용 서버 실행.

포트는 `PORT` 환경변수(또는 --port)로 정한다. 조회 링크 주소(TRACKING_BASE_URL)의
기본값이 이 포트에서 만들어지므로, 포트를 바꿔도 문자로 나가는 링크가 따라온다.

    python scripts/run_server.py                 # 8000
    python scripts/run_server.py --port 8100     # 링크도 8100으로 따라감
"""
import argparse
import os
import sys
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock DRT Server 실행")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=None,
                        help="기본값은 PORT 환경변수, 없으면 8000")
    parser.add_argument("--reload", action="store_true")
    arguments = parser.parse_args()

    if arguments.port is not None:
        # app.core.config가 이 값을 읽어 TRACKING_BASE_URL 기본값을 만든다.
        # config는 uvicorn이 앱을 불러올 때 import되므로 그 전에 넣어야 한다.
        os.environ["PORT"] = str(arguments.port)

    from app.core.config import PORT, tracking_base_url_warning

    warning = tracking_base_url_warning()
    if warning:
        # uvicorn 로그보다 먼저 눈에 띄도록 즉시 내보낸다.
        print(f"[설정 확인 필요] {warning}", flush=True)

    # --host 0.0.0.0(기본값)은 "모든 네트워크 인터페이스에서 받는다"는 바인딩 주소일 뿐,
    # 브라우저 주소창에 그대로 치면 연결되지 않는다. uvicorn 로그에는 이 주소가 그대로
    # 찍혀서 혼동하기 쉬우므로, 실제로 열어야 할 주소를 따로 알려 준다.
    print(f"[접속 안내] 브라우저에서는 http://127.0.0.1:{PORT} 로 여세요.", flush=True)

    uvicorn.run("app.main:app", host=arguments.host, port=PORT, reload=arguments.reload)


if __name__ == "__main__":
    main()
