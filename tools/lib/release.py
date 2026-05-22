"""Pure helpers for tools.release.

No I/O side effects beyond writing to paths the caller passes in. All
functions here must be unit-testable without subprocess, network, or
environment dependencies.
"""

from __future__ import annotations

import re
import tarfile
from pathlib import Path


def build_tag(date_or_iso: str, short_sha: str) -> str:
    """Construct the GitHub-release tag for an archived build.

    `date_or_iso` may be a plain `YYYY-MM-DD` or an ISO 8601 timestamp; in the
    latter case only the date portion is used (the tag is per-day, with the
    sha disambiguating within a day).
    """
    if not date_or_iso:
        raise ValueError("date must be non-empty")
    if not short_sha:
        raise ValueError("sha must be non-empty")
    date_part = date_or_iso.split("T", 1)[0]
    return f"build-{date_part}-{short_sha}"


EDITOR_TEMPLATE = """\
# Lines starting with '#' are ignored.
# Describe what's new in this build and why.
# First line = short summary (shown in README's Past releases log).
# Following paragraphs = full release notes (shown on GitHub Releases).

"""


def render_editor_template() -> str:
    """Return the buffer shown to the user when $EDITOR opens."""
    return EDITOR_TEMPLATE


def strip_editor_comments(raw: str) -> str:
    """Drop lines whose first non-whitespace character is '#', then trim."""
    kept = [line for line in raw.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(kept).strip()


def pack_archive(members: list[tuple[Path, str]], out_path: Path) -> None:
    """Write a gzip-compressed tarball.

    Each member is (source_path_on_disk, arcname_inside_tarball). Directories
    are recursed automatically by tarfile.add. Raises FileNotFoundError if any
    source path does not exist.
    """
    for src, _ in members:
        if not src.exists():
            raise FileNotFoundError(src)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_path, "w:gz") as tf:
        for src, arcname in members:
            tf.add(str(src), arcname=arcname)


WHATS_NEW_START = "<!-- whats-new:start -->"
WHATS_NEW_END = "<!-- whats-new:end -->"
PAST_RELEASES_START = "<!-- past-releases:start -->"
PAST_RELEASES_END = "<!-- past-releases:end -->"
PAST_RELEASES_HEADER = (
    "| Tag | Date | Summary | Download |\n"
    "|-----|------|---------|----------|"
)


def rewrite_readme(
    readme: str,
    *,
    last_build_line: str,
    current_build_date: str,
    whats_new: str,
    past_release_row: str,
) -> str:
    """Return a new README body with release-driven content swapped in.

    Replaces:
      - the line starting with `Last successful build:` with `last_build_line`
      - the `# Current build (YYYY-MM-DD)` heading's date
      - the contents between whats-new markers with `whats_new`
      - prepends `past_release_row` after the past-releases table header

    Raises ValueError if any required marker is missing.
    """
    for marker in (WHATS_NEW_START, WHATS_NEW_END, PAST_RELEASES_START, PAST_RELEASES_END):
        if marker not in readme:
            raise ValueError(f"README is missing marker: {marker}")

    readme = re.sub(
        r"^Last successful build:.*$",
        lambda _: last_build_line,
        readme,
        count=1,
        flags=re.MULTILINE,
    )

    readme = re.sub(
        r"^# Current build \([^)]*\)",
        f"# Current build ({current_build_date})",
        readme,
        count=1,
        flags=re.MULTILINE,
    )

    whats_new_block = f"{WHATS_NEW_START}\n{whats_new}\n{WHATS_NEW_END}"
    readme = re.sub(
        re.escape(WHATS_NEW_START) + r".*?" + re.escape(WHATS_NEW_END),
        lambda _: whats_new_block,
        readme,
        count=1,
        flags=re.DOTALL,
    )

    block_pattern = re.compile(
        re.escape(PAST_RELEASES_START) + r".*?" + re.escape(PAST_RELEASES_END),
        re.DOTALL,
    )

    def _prepend_row(match: re.Match) -> str:
        block = match.group(0)
        body = block[len(PAST_RELEASES_START):-len(PAST_RELEASES_END)]
        lines = [ln for ln in body.splitlines() if ln.strip()]
        existing_rows = [
            ln for ln in lines
            if ln.startswith("|") and "---" not in ln and "Tag" not in ln
        ]
        rows: list[str] = []
        if past_release_row:
            rows.append(past_release_row)
        rows.extend(existing_rows)
        return (
            PAST_RELEASES_START
            + "\n"
            + PAST_RELEASES_HEADER
            + ("\n" + "\n".join(rows) if rows else "")
            + "\n"
            + PAST_RELEASES_END
        )

    return block_pattern.sub(_prepend_row, readme, count=1)
