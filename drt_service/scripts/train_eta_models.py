from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.travel_time.train_model import train_eta_models


def main() -> None:
    parser = argparse.ArgumentParser(description="CatBoost와 LightGBM의 ETA 회귀·속도 분류 성능을 비교합니다.")
    parser.add_argument("input", type=Path, nargs="?", default=ROOT / "data" / "processed" / "eta_processed.csv")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "app" / "travel_time" / "models")
    parser.add_argument("--dataset-label", default="real_eta_dataset")
    parser.add_argument("--max-rows", type=int, default=300_000, help="0이면 전체 행 사용")
    parser.add_argument("--models", nargs="+", default=["catboost", "lightgbm"])
    args = parser.parse_args()
    result = train_eta_models(
        args.input,
        args.artifacts,
        dataset_label=args.dataset_label,
        max_rows=args.max_rows or None,
        candidate_models=args.models,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
