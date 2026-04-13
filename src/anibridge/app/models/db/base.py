"""Base Model Module."""

from sqlalchemy.orm import DeclarativeBase

__all__ = ["Base"]


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass
