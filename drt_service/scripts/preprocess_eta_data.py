from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.travel_time.preprocess_dataset import preprocess_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="100만 행 ETA CSV를 청크 단위로 전처리합니다.")
    parser.add_argument("input", type=Path, nargs="?", default=ROOT / "data" / "raw" / "eta_raw.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "processed" / "eta_processed.csv")
    parser.add_argument("--stations", type=Path, default=ROOT / "data" / "stations_geo.csv")
    parser.add_argument("--chunksize", type=int, default=100_000)
    args = parser.parse_args()
    summary = preprocess_csv(
        args.input,
        args.output,
        stations_path=args.stations,
        chunksize=args.chunksize,
    )
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
