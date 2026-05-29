"""Fix vector date columns reported as non-ISO by qa/qa_log.csv."""

from __future__ import annotations

import argparse
import codecs
import csv
import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.lib.schema import REPO_ROOT
from tools.qa import DATE_COLUMN_CANDIDATES, QA_LOG

DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y")
NON_ISO_REASON = "non-ISO"


@dataclass(frozen=True)
class FixResult:
    path: Path
    date_col: str
    input_format: str
    changed: int


def _is_iso_date(value: str) -> bool:
    try:
        return dt.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _infer_format(values: set[str]) -> str:
    matches = []
    for fmt in DATE_FORMATS:
        try:
            for value in values:
                dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        matches.append(fmt)

    if len(matches) != 1:
        sample = sorted(values)[:5]
        raise ValueError(f"could not infer one date format for sample {sample}: {matches}")
    return matches[0]


def _csv_encoding(raw: bytes) -> str:
    return "utf-8-sig" if raw.startswith(codecs.BOM_UTF8) else "utf-8"


def _line_terminator(raw: bytes) -> str:
    first_lf = raw.find(b"\n")
    if first_lf > 0 and raw[first_lf - 1:first_lf] == b"\r":
        return "\r\n"
    return "\n"


def _qa_targets(qa_log: Path) -> list[tuple[str, str]]:
    targets = set()
    with qa_log.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("type") == "vector" and NON_ISO_REASON in row.get("reasons", ""):
                targets.add((row["dataset"], row["file"]))
    return sorted(targets)


def fix_file(path: Path, *, dry_run: bool = False) -> FixResult:
    raw = path.read_bytes()
    encoding = _csv_encoding(raw)
    with path.open(newline="", encoding=encoding) as f:
        reader = csv.reader(f)
        header = next(reader, [])
        rows = list(reader)

    date_col = next((c for c in DATE_COLUMN_CANDIDATES if c in header), None)
    if date_col is None:
        raise ValueError("no date column found")
    date_i = header.index(date_col)

    bad_values = {
        row[date_i]
        for row in rows
        if len(row) > date_i and not _is_iso_date(row[date_i])
    }
    if not bad_values:
        return FixResult(path, date_col, "", 0)

    input_format = _infer_format(bad_values)
    changed = 0
    for row in rows:
        if len(row) <= date_i or _is_iso_date(row[date_i]):
            continue
        row[date_i] = dt.datetime.strptime(row[date_i], input_format).date().isoformat()
        changed += 1

    if not dry_run:
        with path.open("w", newline="", encoding=encoding) as f:
            writer = csv.writer(f, lineterminator=_line_terminator(raw))
            writer.writerow(header)
            writer.writerows(rows)

    return FixResult(path, date_col, input_format, changed)


def fix_dates_from_qa_log(
    *,
    qa_log: Path = QA_LOG,
    data_dir: Path = REPO_ROOT / "data",
    dry_run: bool = False,
) -> list[FixResult]:
    results = []
    failures = []
    for dataset, file_name in _qa_targets(qa_log):
        path = data_dir / dataset / "processed" / file_name
        try:
            results.append(fix_file(path, dry_run=dry_run))
        except (OSError, csv.Error, ValueError) as e:
            failures.append(f"{path}: {e}")

    if failures:
        raise RuntimeError("\n".join(failures))
    return results


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-log", type=Path, default=QA_LOG)
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        results = fix_dates_from_qa_log(
            qa_log=args.qa_log,
            data_dir=args.data_dir,
            dry_run=args.dry_run,
        )
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1

    if not results:
        print("No non-ISO vector date errors found in QA log.")
        return 0

    verb = "Would fix" if args.dry_run else "Fixed"
    printed = False
    for result in results:
        if result.changed:
            printed = True
            print(
                f"{verb} {result.changed} {result.date_col} values in "
                f"{_display_path(result.path)} using {result.input_format}"
            )
    if not printed:
        print("No matching files needed date fixes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
