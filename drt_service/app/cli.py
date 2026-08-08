from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.config import settings
from app.db.session import create_engine_and_sessionmaker, import_stations, init_db


async def _run(command: str, csv_path: Path | None) -> None:
    engine, session_factory = create_engine_and_sessionmaker(settings.database_path)
    await init_db(engine)
    if command == "init-db":
        print(f"SQLite 초기화 완료: {settings.database_path}")
        await engine.dispose()
        return
    async with session_factory() as session:
        count = await import_stations(session, csv_path or settings.stations_csv_path)
    print(f"정류장 적재 완료: {count}건")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="DRT FastAPI 관리 명령")
    parser.add_argument("command", choices=("init-db", "import-stations"))
    parser.add_argument("--path", type=Path, help="정류장 CSV 경로")
    args = parser.parse_args()
    asyncio.run(_run(args.command, args.path))


if __name__ == "__main__":
    main()

