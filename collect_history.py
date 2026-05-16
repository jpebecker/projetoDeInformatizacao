"""
collect_history.py
==================
Standalone script to backfill historical fiscal data year by year.

Run once (or whenever you want to update the historical archive):

    python collect_history.py              # collects 2019 → current year
    python collect_history.py --start 2022 # collects 2022 → current year
    python collect_history.py --start 2022 --end 2023  # specific range
    python collect_history.py --year 2021  # single year

Each year is collected sequentially (not threaded) to avoid hammering
the APIs. Existing JSON files are skipped by default — use --force to
overwrite them.

NOTE: Historical data availability depends on each portal. The federal
portal (portaldatransparencia.gov.br) reliably provides data from 2014
onward. The Santa Catarina portal availability may vary.
"""

import argparse,logging,os,time
from datetime import datetime

import extract as extractor

# ==============================================================================
# CONFIGURATION
# ==============================================================================

DEFAULT_START_YEAR = 2018
CURRENT_YEAR = datetime.today().year

# Seconds to wait between years to be respectful to the APIs
THROTTLE_SECONDS = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ==============================================================================
# HELPERS
# ==============================================================================

def json_exists(prefix: str, year: int) -> bool:
    """Check if a JSON file already exists for this prefix + year."""
    path = os.path.join(
        extractor.COLLECTED_DATA_FOLDER,
        f"{prefix}_{year}.json"
    )
    return os.path.exists(path)


def all_files_exist(year: int) -> bool:
    """Return True only if ALL six expected JSONs exist for this year."""
    prefixes = [
        "receitas_BR",
        "receitas_SC",
        "despesas_BR",
        "despesas_SC",
        "investimentos_BR",
        "investimentos_SC",
    ]
    return all(json_exists(p, year) for p in prefixes)


# ==============================================================================
# COLLECTION PER YEAR
# ==============================================================================

def collect_year(year: int, force: bool = False) -> None:
    """
    Run the full ETL for a single year.

    Args:
        year (int): Target year.
        force (bool): If True, overwrite existing files.
    """
    if not force and all_files_exist(year):
        logging.info(
            "Year %s already complete — skipping. Use --force to overwrite.",
            year
        )
        return

    logging.info("=" * 60)
    logging.info("Starting collection for year: %s", year)
    logging.info("=" * 60)

    start = time.time()

    # Revenues
    logging.info("[%s] Collecting revenues...", year)
    try:
        extractor.collect_revenues(year=year)
    except Exception as e:
        logging.error("[%s] Revenues failed: %s", year, e)

    # Expenses
    logging.info("[%s] Collecting expenses...", year)
    try:
        extractor.collect_expenses_by_area(year=year)
    except Exception as e:
        logging.error("[%s] Expenses failed: %s", year, e)

    # Investments
    logging.info("[%s] Collecting investments...", year)
    try:
        extractor.collect_investments(year=year)
    except Exception as e:
        logging.error("[%s] Investments failed: %s", year, e)

    elapsed = time.time() - start
    logging.info(
        "Year %s completed in %.1f seconds.", year, elapsed
    )


# ==============================================================================
# ENTRY POINT
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Backfill historical fiscal data by year."
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--year",
        type=int,
        help="Collect a single year (e.g. --year 2021)"
    )
    group.add_argument(
        "--start",
        type=int,
        default=DEFAULT_START_YEAR,
        help=f"Start year of the range (default: {DEFAULT_START_YEAR})"
    )

    parser.add_argument(
        "--end",
        type=int,
        default=CURRENT_YEAR,
        help=f"End year of the range (default: {CURRENT_YEAR})"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing JSON files"
    )

    args = parser.parse_args()

    if args.year:
        years = [args.year]
    else:
        if args.start > args.end:
            parser.error("--start must be <= --end")
        years = list(range(args.start, args.end + 1))

    logging.info(
        "Historical collection: %s → %s (%d year(s))",
        years[0], years[-1], len(years)
    )

    total_start = time.time()

    for i, year in enumerate(years):
        collect_year(year, force=args.force)

        # Throttle between years (skip after the last one)
        if i < len(years) - 1:
            logging.info(
                "Waiting %ds before next year...", THROTTLE_SECONDS
            )
            time.sleep(THROTTLE_SECONDS)

    total_elapsed = time.time() - total_start
    logging.info(
        "All done. Total time: %.1f seconds (%.1f minutes).",
        total_elapsed,
        total_elapsed / 60
    )


if __name__ == "__main__":
    main()