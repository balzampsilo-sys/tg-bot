"""Пакет для версий миграций"""

from database.migrations.versions.v001_initial_schema import InitialSchema
from database.migrations.versions.v002_add_version_column import AddVersionColumn

__all__ = ["InitialSchema", "AddVersionColumn"]
