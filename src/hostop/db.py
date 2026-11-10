"""Engine/session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from hostop.models import Base

_engines: dict[str, Engine] = {}


def get_engine(url: str | None = None) -> Engine:
    if url is None:
        from hostop.settings import get_settings

        url = get_settings().hostop_db_url
    if url not in _engines:
        _engines[url] = create_engine(url, future=True)
    return _engines[url]


def init_db(url: str | None = None) -> Engine:
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    session = sessionmaker(bind=get_engine(url), expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
