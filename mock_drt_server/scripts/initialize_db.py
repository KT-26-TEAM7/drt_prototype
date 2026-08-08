import sys
from pathlib import Path

from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    command.upgrade(Config(PROJECT_ROOT / "alembic.ini"), "head")


if __name__ == "__main__":
    main()
