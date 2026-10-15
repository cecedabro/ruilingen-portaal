"""docs/schema.sql and docs/erd.md are generated from the models: they must not go stale."""

from pathlib import Path

from scripts import dump_schema

DOCS = Path(__file__).parent.parent / "docs"
HINT = "run `.venv/bin/python -m scripts.dump_schema` and commit docs/schema.sql and docs/erd.md"


def test_schema_sql_is_up_to_date():
    assert (DOCS / "schema.sql").read_text() == dump_schema.schema_sql(), HINT


def test_erd_is_up_to_date():
    assert (DOCS / "erd.md").read_text() == dump_schema.erd(), HINT
