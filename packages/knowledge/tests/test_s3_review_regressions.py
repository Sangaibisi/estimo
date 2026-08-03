"""Regressions for the confirmed findings of the S3 adversarial review."""

from pathlib import Path

import pytest
from estimo_knowledge import import_seed, lexical_chunk_ids, lexical_ledger_ids
from estimo_knowledge.importer import _canonicalize, _parse_float, read_rows
from estimo_knowledge.search import _prefix_or_expr
from sqlalchemy.ext.asyncio import AsyncSession


class TestQuerySafety:
    """Finding 1 (critical): raw text must never reach to_tsquery."""

    def test_no_usable_tokens_yields_empty_expr(self) -> None:
        assert _prefix_or_expr("?!") == ""
        assert _prefix_or_expr("a &") == ""

    @pytest.mark.db
    @pytest.mark.parametrize("query", ["ek iş", "?!", "a & b !", "'; drop table x; --"])
    async def test_garbage_queries_never_crash(
        self, session: AsyncSession, clean_tables: None, query: str
    ) -> None:
        assert await lexical_ledger_ids(session, query) == []
        assert await lexical_chunk_ids(session, query, acl_keys=["public"]) == []


class TestCanonicalize:
    def test_stray_delimiter_row_is_reportable(self) -> None:
        """Finding 2 (critical): overflow rows raise a reportable error."""
        with pytest.raises(ValueError, match="stray delimiter"):
            _canonicalize({"a": "1", None: "extra"})

    def test_turkish_caps_headers(self) -> None:
        """Finding 4 (major): İ/I headers must canonicalize."""
        canonical = _canonicalize(
            {"BRD_REF": "B-1", "İŞ KALEMİ": "Kalem", "MÜŞTERİ": "Aurora", "İYİMSER": "1"}
        )
        assert canonical["item_title"] == "Kalem"
        assert canonical["customer"] == "Aurora"
        assert canonical["est_opt"] == "1"

    def test_english_all_caps_headers_still_work(self) -> None:
        canonical = _canonicalize({"ITEM_TITLE": "x", "BRD_REF": "B-2"})
        assert canonical["item_title"] == "x"


class TestParsing:
    def test_turkish_thousands_separator(self) -> None:
        """Finding 5 (major): '1.234,56' is 1234.56, and '7.5' stays 7.5."""
        assert _parse_float("1.234,56") == pytest.approx(1234.56)
        assert _parse_float("7,5") == pytest.approx(7.5)
        assert _parse_float("7.5") == pytest.approx(7.5)

    def test_empty_csv_returns_no_rows(self, tmp_path: Path) -> None:
        """Finding 6 (minor): empty file must not crash."""
        empty = tmp_path / "empty.csv"
        empty.write_text("", encoding="utf-8")
        assert read_rows(empty) == []

    def test_quoted_newlines_preserved(self, tmp_path: Path) -> None:
        f = tmp_path / "quoted.csv"
        f.write_text('brd_ref,item_title\nB-1,"satır bir\nsatır iki"\n', encoding="utf-8")
        rows = read_rows(f)
        assert rows[0]["item_title"] == "satır bir\nsatır iki"


@pytest.mark.db
class TestImportResilience:
    async def test_stray_delimiter_rejects_row_not_import(
        self, session: AsyncSession, clean_tables: None, tmp_path: Path
    ) -> None:
        """Finding 2 (critical): one malformed row, others import."""
        f = tmp_path / "stray.csv"
        f.write_text(
            "brd_ref,item_title,est_likely\n"
            "B-1,İyi kalem,3\n"
            "B-2,Bozuk,kalem,fazla,virgül,5\n"
            "B-3,Diğer iyi kalem,4\n",
            encoding="utf-8",
        )
        report = await import_seed(session, f)
        assert report.imported == 2
        assert len(report.rejected) == 1
        assert "stray delimiter" in report.rejected[0]["error"]

    async def test_varchar_overflow_rejects_row_not_batch(
        self, session: AsyncSession, clean_tables: None, tmp_path: Path
    ) -> None:
        """Finding 3 (major): DB-side rejection lands in the report via savepoint."""
        f = tmp_path / "overflow.csv"
        f.write_text(
            "brd_ref,item_title,est_likely\n"
            f"{'X' * 200},Uzun referanslı kalem,3\n"
            "B-2,Normal kalem,4\n",
            encoding="utf-8",
        )
        report = await import_seed(session, f)
        assert report.imported == 1
        assert len(report.rejected) == 1
        assert "db rejected row" in report.rejected[0]["error"]

    async def test_unparseable_values_warn_not_silent(
        self, session: AsyncSession, clean_tables: None, tmp_path: Path
    ) -> None:
        """Finding 5 (major): non-empty unparseable values are surfaced."""
        f = tmp_path / "warn.csv"
        f.write_text(
            "brd_ref,item_title,est_likely,est_date\nB-1,Kalem,3,otuz Şubat\n",
            encoding="utf-8",
        )
        report = await import_seed(session, f)
        assert report.imported == 1
        assert any("unparseable date" in w["warning"] for w in report.warnings)
