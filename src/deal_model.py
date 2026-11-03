"""Reusable calculations for analysing an all-cash public M&A deal.

Invalid inputs raise ValueError. Negative profits, dilution and negative yields
are economically possible and are allowed. Multiples whose denominator is zero
or negative are not meaningful and are returned as NaN.
"""

from dataclasses import dataclass
import math
import warnings

import numpy as np
import pandas as pd


def _finite(**values):
    for name, value in values.items():
        if not isinstance(value, (int, float, np.integer, np.floating)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number, got {value!r}")


def _positive(**values):
    _finite(**values)
    for name, value in values.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive, got {value!r}")


def _non_negative(**values):
    _finite(**values)
    for name, value in values.items():
        if value < 0:
            raise ValueError(f"{name} cannot be negative, got {value!r}")


def _valid_tax_rate(tax_rate):
    _finite(tax_rate=tax_rate)
    if not 0 <= tax_rate < 1:
        raise ValueError(f"tax_rate must be in [0, 1), got {tax_rate!r}")


def _multiple(numerator, denominator):
    return numerator / denominator if denominator > 0 else math.nan


def load_inputs(path):
    """Return the inputs file as a {key: value} dictionary, after validating it."""
    frame = pd.read_csv(path)
    missing = {"key", "value"} - set(frame.columns)
    if missing:
        raise ValueError(f"Inputs file is missing columns: {sorted(missing)}")
    if frame.empty or frame["key"].isna().any():
        raise ValueError("Inputs file must have a key on every row")
    duplicates = sorted(frame.loc[frame["key"].duplicated(), "key"].unique())
    if duplicates:
        raise ValueError(f"Duplicate input keys: {duplicates}")
    values = pd.to_numeric(frame["value"], errors="coerce").astype(float)
    invalid = frame.loc[~np.isfinite(values), "key"].tolist()
    if invalid:
        raise ValueError(f"Non-numeric or non-finite values for: {invalid}")
    return dict(zip(frame["key"], values))


# --- Price and valuation -----------------------------------------------------

def premium(offer, reference):
    """Premium of the offer price over a reference share price."""
    _positive(offer=offer, reference=reference)
    return offer / reference - 1


def implied_diluted_shares(deal_value, cash, debt, offer):
    """Estimate diluted shares from a deal value quoted net of cash.

    Deal value = equity value - net cash, and equity value = shares x offer.
    The result is an inference that depends on which cash and debt figures the
    announced value used. It is not a reported share count.
    """
    _finite(deal_value=deal_value)
    _non_negative(cash=cash, debt=debt)
    _positive(offer=offer)
    shares = (deal_value + cash - debt) / offer
    if shares <= 0:
        raise ValueError("Inputs imply a non-positive share count")
    return shares


def treasury_method_shares(basic, rsus, options, strike, offer):
    """Diluted shares at an offer price: basic + RSUs + options, treasury method."""
    _non_negative(basic=basic, rsus=rsus, options=options, strike=strike)
    _positive(offer=offer)
    net_options = options * (1 - strike / offer) if offer > strike else 0.0
    return basic + rsus + net_options


def valuation_multiples(price, shares, cash, debt, revenue, ebit, da, net_income):
    """Equity value, enterprise value and the standard trading multiples.

    `da` is whatever is added back to EBIT, so the caller sets the EBITDA policy.
    EV/EBITDA and P/E are NaN when EBITDA or net income is zero or negative.
    """
    _positive(price=price, shares=shares, revenue=revenue)
    _non_negative(cash=cash, debt=debt)
    _finite(ebit=ebit, da=da, net_income=net_income)
    equity = price * shares
    ev = equity - cash + debt
    return {
        "Equity value ($bn)": equity / 1000,
        "EV ($bn)": ev / 1000,
        "EV/Revenue": ev / revenue,
        "EV/EBITDA": _multiple(ev, ebit + da),
        "P/E": _multiple(equity, net_income),
        "EBIT margin": ebit / revenue,
    }


# --- Market reaction ---------------------------------------------------------

@dataclass
class EventStudy:
    alpha: float
    beta: float
    r_squared: float
    residual_std: float
    observations: int
    market_mean: float
    market_sxx: float
    table: pd.DataFrame


def _check_series(series, name):
    if not isinstance(series, pd.Series) or not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError(f"{name} must be a pandas Series with a DatetimeIndex")
    if not series.index.is_unique or not series.index.is_monotonic_increasing:
        raise ValueError(f"{name} must have unique dates in ascending order")
    if np.isinf(series.astype(float)).any():
        raise ValueError(f"{name} contains infinite values")


def market_model_event_study(returns, market, event_date, estimation=120, gap=10, half_window=5):
    """Abnormal returns from a market model fitted before the event.

    Estimation uses `estimation` trading days and stops `gap` days before the
    event, so that the announcement cannot affect the fitted parameters. Leading
    missing values, such as the first value from pct_change(), are allowed. Any
    later gap raises an error, because dropping it would renumber the event days.

    Standard errors are out-of-sample prediction errors, which include the
    uncertainty in the fitted alpha and beta. They assume independent, normally
    distributed residuals with constant variance.
    """
    _check_series(returns, "returns")
    _check_series(market, "market")
    for name, value, minimum in (("estimation", estimation, 3), ("gap", gap, 0),
                                 ("half_window", half_window, 0)):
        if not isinstance(value, (int, np.integer)) or value < minimum:
            raise ValueError(f"{name} must be an integer of at least {minimum}, got {value!r}")

    if gap < half_window:
        raise ValueError(f"gap ({gap}) must be at least half_window ({half_window}) so that the "
                         "estimation sample does not overlap the event window")

    data = pd.concat({"stock": returns, "market": market}, axis=1)
    for name in data.columns:
        first_valid = data[name].first_valid_index()
        if first_valid is None or data.loc[first_valid:, name].isna().any():
            raise ValueError(f"{name} has missing values after its first observation, or the two "
                             "series do not share the same dates")
    data = data.dropna()
    event_date = pd.Timestamp(event_date)
    if event_date not in data.index:
        raise ValueError(f"Event date {event_date.date()} is not available in both series")

    event = data.index.get_loc(event_date)
    first = event - gap - estimation
    if first < 0:
        raise ValueError(f"Need {estimation + gap} observations before the event, have {event}")
    if event + half_window >= len(data):
        raise ValueError(f"Need {half_window} observations after the event, have {len(data) - event - 1}")

    sample = data.iloc[first:event - gap]
    market_mean = sample["market"].mean()
    sxx = ((sample["market"] - market_mean) ** 2).sum()
    if sxx <= 0:
        raise ValueError("Market returns do not vary in the estimation window")

    beta, alpha = np.polyfit(sample["market"], sample["stock"], 1)
    residuals = sample["stock"] - (alpha + beta * sample["market"])
    residual_std = residuals.std(ddof=2)
    total_variance = sample["stock"].var(ddof=0)
    r_squared = 1 - residuals.var(ddof=0) / total_variance if total_variance > 0 else math.nan

    window = data.iloc[event - half_window:event + half_window + 1].copy()
    window["day"] = range(-half_window, half_window + 1)
    window["abnormal"] = window["stock"] - (alpha + beta * window["market"])
    window["std_error"] = residual_std * np.sqrt(
        1 + 1 / estimation + (window["market"] - market_mean) ** 2 / sxx)
    window["t_stat"] = window["abnormal"] / window["std_error"].where(window["std_error"] > 0)
    return EventStudy(alpha, beta, r_squared, residual_std, len(sample), market_mean, sxx, window)


def cumulative_abnormal(study, first_day, last_day):
    """Cumulative abnormal return over a complete window, with its t-statistic.

    The variance includes estimation uncertainty, which is shared across days:
    s^2 x [L + L^2 / n + (sum of market returns - L x mean)^2 / Sxx].
    """
    for name, value in (("first_day", first_day), ("last_day", last_day)):
        if not isinstance(value, (int, np.integer)):
            raise ValueError(f"{name} must be an integer, got {value!r}")
    if first_day > last_day:
        raise ValueError("first_day cannot be after last_day")
    available = study.table["day"]
    if first_day < available.min() or last_day > available.max():
        raise ValueError(
            f"Window [{first_day}, {last_day}] is outside the available days "
            f"[{available.min()}, {available.max()}]")

    days = study.table[available.between(first_day, last_day)]
    length = len(days)
    car = days["abnormal"].sum()
    variance = study.residual_std ** 2 * (
        length + length ** 2 / study.observations
        + (days["market"].sum() - length * study.market_mean) ** 2 / study.market_sxx)
    return car, (car / math.sqrt(variance) if variance > 0 else math.nan)


def implied_completion_probability(market_price, offer, fallback):
    """Completion probability in a simple binary model.

    It is conditional on the fallback price and has no discounting or risk
    premium, so it is not an objective probability. Values outside [0, 1] are
    returned unchanged with a warning, because they show inconsistent inputs.
    """
    _positive(market_price=market_price, offer=offer, fallback=fallback)
    if offer <= fallback:
        raise ValueError("offer must be above the fallback price")
    probability = (market_price - fallback) / (offer - fallback)
    if not 0 <= probability <= 1:
        warnings.warn(f"Implied probability {probability:.2f} is outside [0, 1]; check the inputs",
                      stacklevel=2)
    return probability


# --- EPS sensitivity ---------------------------------------------------------

def pro_forma_eps(acquirer_income, target_income, acquirer_shares, cash_used,
                  forgone_yield, tax_rate, synergies=0.0, amortization=0.0):
    """Acquirer EPS after an all-cash deal, so the share count does not change.

    A simplified sensitivity, not an accounting pro forma. One tax rate applies
    to the forgone income, synergies and amortization. `amortization` means
    amortization in addition to anything already in the target's net income.
    """
    _finite(acquirer_income=acquirer_income, target_income=target_income,
            forgone_yield=forgone_yield, synergies=synergies, amortization=amortization)
    _positive(acquirer_shares=acquirer_shares)
    _non_negative(cash_used=cash_used)
    _valid_tax_rate(tax_rate)
    after_tax = 1 - tax_rate
    income = (acquirer_income + target_income
              + (synergies - amortization - cash_used * forgone_yield) * after_tax)
    return income / acquirer_shares


def accretion(acquirer_income, target_income, acquirer_shares, cash_used,
              forgone_yield, tax_rate, synergies=0.0, amortization=0.0):
    """Percentage change in the acquirer's EPS. NaN if standalone income is not positive."""
    combined = pro_forma_eps(acquirer_income, target_income, acquirer_shares, cash_used,
                             forgone_yield, tax_rate, synergies, amortization)
    if acquirer_income <= 0:
        return math.nan
    return combined / (acquirer_income / acquirer_shares) - 1


def breakeven_yield(target_income, cash_used, tax_rate, synergies=0.0, amortization=0.0):
    """Yield on the cash spent at which the deal stops adding to EPS."""
    _finite(target_income=target_income, synergies=synergies, amortization=amortization)
    _positive(cash_used=cash_used)
    _valid_tax_rate(tax_rate)
    return (target_income / (1 - tax_rate) + synergies - amortization) / cash_used
