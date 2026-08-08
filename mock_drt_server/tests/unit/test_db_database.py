import unittest
from threading import Thread

from sqlalchemy import text

from app.db.database import create_database_engine


class DatabaseEngineTest(unittest.TestCase):
    def test_sqlite_foreign_keys_are_enabled(self):
        engine = create_database_engine("sqlite://")
        try:
            with engine.connect() as connection:
                enabled = connection.scalar(text("PRAGMA foreign_keys"))
        finally:
            engine.dispose()

        self.assertEqual(enabled, 1)

    def test_sqlite_connection_can_be_used_across_threads(self):
        engine = create_database_engine("sqlite://")
        connection = engine.raw_connection()
        results: list[int] = []
        errors: list[Exception] = []

        def query_connection() -> None:
            try:
                cursor = connection.cursor()
                try:
                    cursor.execute("SELECT 1")
                    results.append(cursor.fetchone()[0])
                finally:
                    cursor.close()
            except Exception as error:
                errors.append(error)

        try:
            thread = Thread(target=query_connection)
            thread.start()
            thread.join()
        finally:
            connection.close()
            engine.dispose()

        self.assertEqual(errors, [])
        self.assertEqual(results, [1])


if __name__ == "__main__":
    unittest.main()
