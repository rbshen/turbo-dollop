from sqlmodel import SQLModel, create_engine

from config import BASE_DIR, settings

import models  # noqa: F401  (registers tables on SQLModel.metadata)

DB_PATH = (BASE_DIR / settings.database_path).resolve()
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
