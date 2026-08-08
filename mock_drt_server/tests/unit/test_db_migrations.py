import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from sqlalchemy import create_engine, inspect, text

from app.core.config import PROJECT_ROOT
from app.db.database import Base
import app.db.models  # noqa: F401


class DatabaseMigrationTest(unittest.TestCase):
    def test_upgrade_matches_model_metadata_and_downgrade_succeeds(self):
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "migration.sqlite"
            database_url = f"sqlite:///{database_path.as_posix()}"
            environment = {**os.environ, "DATABASE_URL": database_url}

            subprocess.run(
                [sys.executable, "scripts/initialize_db.py"],
                cwd=PROJECT_ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

            engine = create_engine(database_url)
            try:
                inspector = inspect(engine)
                migrated_tables = {
                    table_name
                    for table_name in inspector.get_table_names()
                    if table_name != "alembic_version"
                }
                self.assertEqual(migrated_tables, set(Base.metadata.tables))
                for table_name, table in Base.metadata.tables.items():
                    migrated_columns = {
                        column["name"] for column in inspector.get_columns(table_name)
                    }
                    self.assertEqual(migrated_columns, set(table.columns.keys()))
                with engine.connect() as connection:
                    self.assertEqual(
                        connection.scalar(text("SELECT version_num FROM alembic_version")),
                        "0003",
                    )
            finally:
                engine.dispose()

            subprocess.run(
                [sys.executable, "-m", "alembic", "downgrade", "base"],
                cwd=PROJECT_ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

            engine = create_engine(database_url)
            try:
                self.assertEqual(inspect(engine).get_table_names(), ["alembic_version"])
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
