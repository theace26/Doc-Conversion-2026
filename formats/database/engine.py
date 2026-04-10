"""Abstract base class and dataclasses for database content extraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TableInfo:
    """Summary info for a single database table."""
    name: str
    row_count: int
    column_count: int


@dataclass
class ColumnInfo:
    """Column definition within a table."""
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool
    default_value: str | None = None


@dataclass
class RelationshipInfo:
    """Foreign key / relationship between tables."""
    name: str
    parent_table: str
    child_table: str
    parent_columns: list[str] = field(default_factory=list)
    child_columns: list[str] = field(default_factory=list)


@dataclass
class IndexInfo:
    """Index definition on a table."""
    name: str
    table: str
    columns: list[str] = field(default_factory=list)
    unique: bool = False


class DatabaseEngine(ABC):
    """Abstract interface for database content extraction."""

    @abstractmethod
    def open(self, path: Path, password: str | None = None) -> bool:
        """Attempt to open the database. Returns True on success."""
        ...

    @abstractmethod
    def list_tables(self) -> list[TableInfo]:
        """Return table names with row counts."""
        ...

    @abstractmethod
    def get_schema(self, table: str) -> list[ColumnInfo]:
        """Return column definitions for a table."""
        ...

    @abstractmethod
    def get_row_count(self, table: str) -> int:
        """Return exact row count for a table."""
        ...

    @abstractmethod
    def sample_rows(self, table: str, limit: int = 25) -> list[list[str]]:
        """Return the first N rows as string values (header row first)."""
        ...

    def get_relationships(self) -> list[RelationshipInfo]:
        """Return foreign key definitions. Override if format supports them."""
        return []

    def get_indexes(self) -> list[IndexInfo]:
        """Return index definitions. Override if format supports them."""
        return []

    @abstractmethod
    def close(self) -> None:
        """Release resources."""
        ...

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
