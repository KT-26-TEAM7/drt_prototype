from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.clients.drt_client import HttpDrtClient, MockDrtClient
from app.clients.tmap_client import MockTmapClient, TmapClient
from app.config import Settings, settings as default_settings
from app.db.session import create_engine_and_sessionmaker, init_db, load_active_stations, seed_stations_if_empty
from app.travel_time.estimate_duration import ETAPredictor, ETAService, StationIndex


def create_app(app_settings: Settings | None = None) -> FastAPI:
    config = app_settings or default_settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine, session_factory = create_engine_and_sessionmaker(config.database_path)
        await init_db(engine)
        async with session_factory() as session:
            await seed_stations_if_empty(session, config.stations_csv_path)
        async with session_factory() as session:
            stations = await load_active_stations(session)

        tmap_client = (
            TmapClient(
                app_key=config.tmap_app_key,
                base_url=config.tmap_base_url,
                timeout_s=config.tmap_timeout_s,
                max_retries=config.tmap_max_retries,
            )
            if config.use_real_api
            else MockTmapClient()
        )
        # 모델 로딩(joblib)은 비용이 있으므로 기동 시 1회만 만들어 재사용한다.
        # artifacts_dir이 없거나 로드에 실패해도 ETAPredictor 내부에서 공식/규칙 폴백으로 처리된다.
        eta_predictor = ETAPredictor(StationIndex(stations), artifacts_dir=config.eta_artifacts_dir)

        # DRT_SERVER_BASE_URL이 있으면 실제 배차 서버에 붙고, 없으면 항상 수락하는 MOCK이다.
        drt_client = (
            HttpDrtClient(
                base_url=config.drt_server_base_url,
                timeout_s=config.drt_server_timeout_s,
            )
            if config.drt_server_base_url
            else MockDrtClient()
        )

        app.state.settings = config
        app.state.session_factory = session_factory
        app.state.tmap_client = tmap_client
        app.state.drt_client = drt_client
        app.state.eta_service = ETAService(eta_predictor)
        yield
        await tmap_client.close()
        await app.state.drt_client.close()
        await engine.dispose()

    application = FastAPI(
        title=config.app_name,
        version=config.app_version,
        description="실시간 위치와 TMAP 데이터를 이용해 DRT 승·하차 정류장 및 목적지를 추천합니다.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Relay-Token"],
    )
    application.include_router(router)
    return application


app = create_app()
