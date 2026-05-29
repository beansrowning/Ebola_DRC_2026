"""
Build long and wide datasets which directly merge in to existing CDC data by a foreign key
Sean Browning
"""
import logging
from argparse import ArgumentParser
from functools import reduce
from pathlib import Path
from typing import Optional

import polars as pl
import shapefile

from tools.build_geojson import DATE_COLUMN_CANDIDATES
from tools.lib.schema import REPO_ROOT, load_zones, to_canonical
from tools.qa import main as qa

DATE_COLS_SET = set(DATE_COLUMN_CANDIDATES)

logger = logging.getLogger(__name__)

def load_geo_table_from_feats(path: Path) -> pl.DataFrame:
    """
    Load in shape file to get canonical names
    """

    reader = shapefile.Reader(path)
    zones = load_zones()

    # oh you know...
    onetable = []

    for zone, sh in zip(zones, reader.shapes()):
        
        if sh is None:
            logger.warning(f"Shape geometry missing for {zone.canonical_nom}, skipping!")
            continue
        
        loc = {
            "nom": zone.canonical_nom,
            "province": zone.province,
            "iso3": "COD",
            # NOTE: unique id we use interal to CDC to join to other spatial objects
            "unique_id": f"COD_{zone.province}_{zone.canonical_nom}",
        }
        onetable.append(loc)

    return pl.DataFrame(onetable)


def main(project_root: Path, force_qa: bool, out_path: Optional[Path]):

    # Build paths
    data_dir = project_root / "data"
    qa_path = project_root / "qa"
    qa_log_path = qa_path / "qa_log.csv"
    shapefile_path = data_dir / "shapefiles" / "DRC_Health_zones"
    out_path = out_path if out_path is not None else project_root / "build"

    logger.info(f"Established project root as: {str(project_root)}")
    logger.debug(f"Writing out to: {str(out_path)}")

    if force_qa:
        logger.info("force_qa=True, running QA process first.")
        qa()
    
    # Load shapefile
    onetable = load_geo_table_from_feats(shapefile_path)

    # Load Data manifest from QA
    qa_manifest = (
        pl.read_csv(qa_log_path)
        .filter(
            pl.col("status") != "fail",
            pl.col("type") == "vector"
        )
        .with_columns(
            file_path = pl.concat_str(
                [pl.lit(str(data_dir)), pl.col("dataset"), pl.lit("processed"), pl.col("file")],
                separator="/"
            )
        )
    )

    horz = []
    vert = []

    for row in qa_manifest.select(["file", "file_path"]).iter_rows(named=True):
        # Read in data and match HZ to canonical
        df = (
            pl.read_csv(row["file_path"], null_values=["ND"])
            .with_columns(
                nom = pl.col("nom").map_elements(to_canonical, return_dtype=pl.String)
            )
        )

        # Remove empty col if present
        try:
            df = df.drop("")
        except pl.exceptions.ColumnNotFoundError:
            pass

        # Handle ts data
        # NOTE: In a wide dataset, we'll just keep the latest observation only
        if (date_col := DATE_COLS_SET & set(df.columns)):
            date_col = date_col.pop() # HACK: set -> str
            
            # - Trust no date
            # - rename date col consistently
            df = (
                df
                .with_columns(
                    pl.col(date_col).str.to_date().alias("date")
                )
            )

            vert.append(df)
        else:
            horz.append(df)

    # Generate the two tables

    # Build a cartesian scaffold with nom x date
    # HACK: Could be thrown off if one date is wonky
    nom_dates = onetable.select("nom").join(
        pl.concat([df.select("date") for df in vert]).unique(),
        how="cross",
    )

    long_table = (
        onetable
        .join(
            reduce(lambda l, r: l.join(r, on=["date", "nom"], how="left"), vert, nom_dates),
            on="nom"
        )
        .sort(["unique_id", "date"])
    )

    wide_table = reduce(lambda l, r: l.join(r, on="nom", how="left"), horz, onetable)

    # Write out
    logger.info(f"Writing to {str(out_path)}")

    long_table.write_csv(out_path / "cdc_data_long.csv")
    logger.info(f"Wrote CDC Long Table {str(long_table.shape)}")

    wide_table.write_csv(out_path / "cdc_data_wide.csv")
    logger.info(f"Wrote CDC Wide Table {str(wide_table.shape)}")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--project_root", type=Path, default=REPO_ROOT, help="Path to project root")
    parser.add_argument("--force_qa", action="store_true", default=False, help="Should QA be re-run in this build? (default: False)")
    parser.add_argument("--out_path", type=Path, required=False, help="(optional) Path where output should be written (default is in build/ off of project root)")
    parser.add_argument("--log_level", type=str, default="INFO", help="Python logging default log level (default: INFO)")
    args = vars(parser.parse_args())

    logging.basicConfig(level=args.pop("log_level"))

    main(**args)
