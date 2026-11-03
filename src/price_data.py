"""Schema and validation for the daily market data used by the event study.

The project does not download or distribute this data. Users supply a CSV that
they are entitled to use, from any provider.
"""

import numpy as np
import pandas as pd

EVENT_DATE = "2022-01-18"
START_DATE = "2021-07-01"
END_DATE = "2022-02-15"
PRICE_COLUMNS = ["msft_close", "msft_adj_close", "sp500_close", "sp500tr_close", "ndx_close"]

# The longest ordinary gap between trading days is a long weekend. This is not a
# business-day calendar, so exchange holidays are not treated as missing data.
MAX_GAP_DAYS = 5


def validate_market_prices(frame, event_date=EVENT_DATE, start=START_DATE, end=END_DATE,
                           estimation=120, gap=10, half_window=5, max_gap_days=MAX_GAP_DAYS):
    """Return the data indexed by date, or raise ValueError describing the problem."""
    if frame.empty:
        raise ValueError("The price table has no rows")
    missing = [c for c in ["date", *PRICE_COLUMNS] if c not in frame.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    extra = [c for c in frame.columns if c not in ["date", *PRICE_COLUMNS]]
    if extra:
        raise ValueError(f"Unexpected columns: {extra}")

    dates = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ValueError("Dates must be valid and use the format YYYY-MM-DD")
    if not dates.is_unique:
        raise ValueError("Dates must be unique")
    if not dates.is_monotonic_increasing:
        raise ValueError("Dates must be in ascending order")
    if dates.iloc[0] < pd.Timestamp(start) or dates.iloc[-1] > pd.Timestamp(end):
        raise ValueError(f"Dates must be between {start} and {end}")

    values = frame[PRICE_COLUMNS].apply(pd.to_numeric, errors="coerce").astype(float)
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError("Prices must be numeric, finite and present on every row")
    if (values <= 0).any().any():
        raise ValueError("Prices must be positive")

    largest_gap = dates.diff().dt.days.max()
    if largest_gap > max_gap_days:
        raise ValueError(f"Unexpected gap of {largest_gap:.0f} days between observations")

    table = values.set_index(pd.DatetimeIndex(dates, name="date"))
    event = pd.Timestamp(event_date)
    if event not in table.index:
        raise ValueError(f"The event date {event_date} is missing")
    position = table.index.get_loc(event)
    needed_before = estimation + gap + 1  # The first price has no return.
    if position < needed_before:
        raise ValueError(f"Need {needed_before} observations before the event, have {position}")
    after = len(table) - position - 1
    if after < half_window:
        raise ValueError(f"Need {half_window} observations after the event, have {after}")
    return table


def load_market_prices(path):
    """Read and validate a market data CSV."""
    return validate_market_prices(pd.read_csv(path, dtype={"date": str}))
