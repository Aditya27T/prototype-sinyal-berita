"""Koneksi DB — milik Person 3. Postgres utama, SQLite fallback demo."""
from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from database.models import Base

load_dotenv()

def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./signyal.db")


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./signyal.db")

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine(url: str | None = None) -> Engine:
    global _engine
    if _engine is not None and url is None:
        return _engine
    db_url = url or get_database_url()
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    eng = create_engine(db_url, future=True, pool_pre_ping=True, connect_args=connect_args)
    if url is None:
        _engine = eng
    return eng


def get_session_factory(url: str | None = None) -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is not None and url is None:
        return _SessionLocal
    eng = get_engine(url)
    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    if url is None:
        _SessionLocal = factory
    return factory


def init_db(url: str | None = None) -> None:
    eng = get_engine(url)
    Base.metadata.create_all(eng)
