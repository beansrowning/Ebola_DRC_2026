from __future__ import annotations

import csv
from pathlib import Path

from tools.fix_non_iso_dates import fix_dates_from_qa_log


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)


def _read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_fix_dates_from_qa_log_converts_reported_vector_dates(tmp_path: Path):
    data_dir = tmp_path / "data"
    qa_log = tmp_path / "qa_log.csv"

    ddmmyyyy = data_dir / "insp_sitrep" / "processed" / "insp_sitrep__cases__daily.csv"
    mdyy = data_dir / "insp_sitrep" / "processed" / "insp_sitrep__deaths__daily.csv"
    _write_csv(
        ddmmyyyy,
        [
            ["nom", "date", "cases"],
            ["Bunia", "14/05/2026", "1"],
            ["Goma", "15/05/2026", "2"],
        ],
    )
    _write_csv(
        mdyy,
        [
            ["nom", "date", "deaths"],
            ["Bunia", "5/27/26", "3"],
        ],
    )
    _write_csv(
        qa_log,
        [
            ["dataset", "file", "type", "status", "n_rows", "n_zones_covered", "reasons", "checked_at"],
            [
                "insp_sitrep",
                ddmmyyyy.name,
                "vector",
                "fail",
                "2",
                "2",
                "2 non-ISO date values",
                "2026-05-29T00:00:00+00:00",
            ],
            [
                "insp_sitrep",
                mdyy.name,
                "vector",
                "fail",
                "1",
                "1",
                "1 non-ISO date values",
                "2026-05-29T00:00:00+00:00",
            ],
        ],
    )

    results = fix_dates_from_qa_log(qa_log=qa_log, data_dir=data_dir)

    assert sorted(r.changed for r in results) == [1, 2]
    assert _read_csv(ddmmyyyy) == [
        ["nom", "date", "cases"],
        ["Bunia", "2026-05-14", "1"],
        ["Goma", "2026-05-15", "2"],
    ]
    assert _read_csv(mdyy) == [
        ["nom", "date", "deaths"],
        ["Bunia", "2026-05-27", "3"],
    ]
