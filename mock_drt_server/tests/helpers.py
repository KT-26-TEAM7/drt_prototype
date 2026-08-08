import unittest

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base, create_database_engine


def create_test_database() -> tuple[Engine, sessionmaker]:
    engine = create_database_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


class DatabaseTestCase(unittest.TestCase):
    engine: Engine
    session_factory: sessionmaker
    db: Session

    def setUp(self) -> None:
        self.engine, self.session_factory = create_test_database()
        self.db = self.session_factory()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
