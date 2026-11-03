"""Validate a CSV of daily prices and save it as data/market_prices.csv.

Run from the repository root: python tools/import_prices.py path/to/your_prices.csv

The file can come from any provider whose terms allow you to use it this way.
data/README.md describes the columns. Nothing is downloaded, and the result stays
out of the repository. Rows outside the required period are removed and reported.
Prices are otherwise unchanged.
"""

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from price_data import END_DATE, START_DATE, validate_market_prices

OUTPUT = Path("data/market_prices.csv")


def main(arguments):
    if len(arguments) != 1:
        sys.exit("Usage: python tools/import_prices.py path/to/your_prices.csv")
    frame = pd.read_csv(arguments[0], dtype={"date": str})
    if "date" not in frame.columns:
        sys.exit("Could not import the file: Missing columns: ['date']")

    inside = frame["date"].between(START_DATE, END_DATE)
    removed = int((~inside).sum())
    selected = frame[inside]
    try:
        table = validate_market_prices(selected)
    except ValueError as error:
        sys.exit(f"Could not import the file: {error}")

    temporary = OUTPUT.with_suffix(".tmp")
    table.to_csv(temporary)
    os.replace(temporary, OUTPUT)
    print(f"Saved {len(table)} rows to {OUTPUT}; removed {removed} rows outside {START_DATE} to {END_DATE}")


if __name__ == "__main__":
    main(sys.argv[1:])
