"""The language table matches app/platform/languages.py, which the runner images are checked
against (`make runners-check`, TCK-0801). A change to one without the other fails here."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory, system_session
from app.platform.languages import RUNNERS
from app.platform.models import Language


async def test_table_matches_the_runners(app_engine: AsyncEngine) -> None:
    async with system_session(create_session_factory(app_engine)) as s:
        rows = {row.key: row for row in await s.scalars(select(Language))}
    assert set(rows) == {r.key for r in RUNNERS}
    for runner in RUNNERS:
        row = rows[runner.key]
        assert row.image == runner.image
        assert row.display_name == runner.display_name
        assert row.source_filename == runner.source_filename
        assert row.compile_cmd == (list(runner.compile_cmd) if runner.compile_cmd else None)
        assert row.run_cmd == list(runner.run_cmd)
        assert Decimal(row.time_multiplier) == runner.time_multiplier
        assert row.enabled
