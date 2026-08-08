from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import calls, stops, tracking, vehicles
from app.core.config import PORT, PROJECT_ROOT
from app.core.lifespan import lifespan


app = FastAPI(
    title="Mock DRT Server",
    lifespan=lifespan,
)

# GitHub Pages(drt-tracking) 등 다른 오리진에서 조회 API를 부를 수 있도록 허용.
# 로컬 조회 화면은 /static/tracking에서 같은 오리진으로 서빙되므로 이 설정이
# 없어도 동작하지만, 배포된 프론트에서 이 서버를 직접 가리킬 때 필요하다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://kt-26-team7.github.io"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/", tags=["system"])
def root() -> dict:
    # 이 경로가 없으면 브라우저로 루트 주소만 열어 본 사람에게 404가 떠서
    # 서버가 죽은 것처럼 보인다. drt_service의 루트 응답과 같은 형식으로 맞춘다.
    return {
        "status": "ok",
        "service": "Mock DRT Server",
        "endpoints": ["/stops", "/vehicles", "/calls", "/tracking?token=..."],
        "docs": "/docs",
    }


@app.get("/health", tags=["system"])
def health_check() -> dict:
    return {"status": "ok"}


app.include_router(stops.router)
app.include_router(vehicles.router)
app.include_router(calls.router)
app.include_router(tracking.router)
app.mount(
    "/static/tracking",
    StaticFiles(directory=PROJECT_ROOT / "web" / "tracking"),
    name="tracking-static",
)
