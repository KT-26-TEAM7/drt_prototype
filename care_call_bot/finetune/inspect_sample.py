'''AI Hub 라벨링데이터(JSON)의 실제 구조를 확인하기 위한 스크립트.

prepare_dataset.py가 어떤 키를 찾아야 하는지 파악하기 전에,
받아온 JSON 파일 몇 개를 열어 키 구조와 예시 값을 눈으로 확인합니다.

실행:
    python finetune/inspect_sample.py finetune/data/raw
    python finetune/inspect_sample.py finetune/data/raw --n 5
'''

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def find_json_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.json"))


def describe(value: Any, depth: int = 0, max_depth: int = 4) -> str:
    indent = "  " * depth
    if depth >= max_depth:
        return f"{indent}...(더 깊음)"
    if isinstance(value, dict):
        lines = []
        for key, sub in value.items():
            lines.append(f"{indent}- {key}: {type(sub).__name__}")
            lines.append(describe(sub, depth + 1, max_depth))
        return "\n".join(line for line in lines if line)
    if isinstance(value, list):
        if not value:
            return f"{indent}(빈 리스트)"
        return f"{indent}[리스트 {len(value)}개, 첫 원소]\n" + describe(value[0], depth + 1, max_depth)
    text = str(value)
    if len(text) > 120:
        text = text[:120] + "..."
    return f"{indent}= {text}"


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Hub JSON 라벨 구조 확인")
    parser.add_argument("root", help="JSON이 들어있는 폴더 (압축 해제한 raw 폴더)")
    parser.add_argument("--n", type=int, default=3, help="확인할 파일 개수 (기본 3)")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"경로가 없습니다: {root}")
        sys.exit(1)

    files = find_json_files(root)
    if not files:
        print(f"{root} 아래에서 .json 파일을 찾지 못했습니다. zip을 제대로 풀었는지 확인하세요.")
        sys.exit(1)

    print(f"총 {len(files)}개 JSON 파일 발견. 상위 {min(args.n, len(files))}개를 확인합니다.\n")

    for path in files[: args.n]:
        print("=" * 80)
        print(path)
        print("=" * 80)
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:  # noqa: BLE001
            print(f"(파싱 실패: {exc})")
            continue
        print(describe(data))
        print()


if __name__ == "__main__":
    main()
