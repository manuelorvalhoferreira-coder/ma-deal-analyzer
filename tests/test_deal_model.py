"""Checks for the model. Run from the repository root: python tests/test_deal_model.py"""

import math
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import deal_model as dm


def close(a, b, tol=1e-9):
    assert abs(a - b) < tol, f"{a} != {b}"


def raises(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError(f"{function.__name__} accepted invalid input: {args} {kwargs}")


def sample_returns(periods=200, noise=0.0):
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2021-01-01", periods=periods)
    market = pd.Series(rng.normal(0, 0.01, periods), index=dates)
    stock = 0.001 + 1.5 * market + rng.normal(0, 0.005, periods) * noise
    return stock, market, dates


def inputs_file(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    handle.write(text)
    handle.close()
    return handle.name


# --- Original checks ---------------------------------------------------------

def test_premium():
    close(dm.premium(120, 100), 0.20)


def test_diluted_shares_reconcile_to_the_price_paid():
    shares = dm.implied_diluted_shares(900, 150, 50, 10)
    close(shares, 100)


def test_multiples():
    m = dm.valuation_multiples(10, 100, 150, 50, 450, 80, 10, 50)
    close(m["EV ($bn)"], 0.9)
    close(m["EV/Revenue"], 2)
    close(m["EV/EBITDA"], 10)
    close(m["P/E"], 20)


def test_probability_bounds():
    close(dm.implied_completion_probability(100, 100, 60), 1)
    close(dm.implied_completion_probability(60, 100, 60), 0)


def test_no_income_and_no_cost_means_no_accretion():
    close(dm.accretion(100, 0, 10, 0, 0.05, 0.2), 0)


def test_accretion_is_zero_at_breakeven_yield():
    y = dm.breakeven_yield(40, 1000, 0.2, synergies=10, amortization=5)
    close(dm.accretion(100, 40, 10, 1000, y, 0.2, synergies=10, amortization=5), 0)


def test_event_study_recovers_known_parameters():
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2021-01-01", periods=200)
    market = pd.Series(rng.normal(0, 0.01, 200), index=dates)
    stock = 0.001 + 1.5 * market
    stock.iloc[150] += 0.05
    study = dm.market_model_event_study(stock, market, dates[150])
    close(study.beta, 1.5, 1e-9)
    close(study.alpha, 0.001, 1e-9)
    day_zero = study.table.loc[study.table["day"] == 0, "abnormal"].iloc[0]
    close(day_zero, 0.05, 1e-9)


# --- Inputs ------------------------------------------------------------------

def test_inputs_reject_duplicate_keys():
    raises(dm.load_inputs, inputs_file("key,value\na,1\na,2\n"))


def test_inputs_reject_missing_columns_and_bad_values():
    raises(dm.load_inputs, inputs_file("name,value\na,1\n"))
    raises(dm.load_inputs, inputs_file("key,value\na,text\n"))
    raises(dm.load_inputs, inputs_file("key,value\na,inf\n"))
    raises(dm.load_inputs, inputs_file("key,value\n,1\n"))


def test_inputs_load_valid_file():
    assert dm.load_inputs(inputs_file("key,value,source\na,1.5,x\nb,-2,y\n")) == {"a": 1.5, "b": -2.0}


# --- Event study -------------------------------------------------------------

def test_event_study_rejects_insufficient_history():
    stock, market, dates = sample_returns()
    raises(dm.market_model_event_study, stock, market, dates[150], estimation=200)


def test_event_study_rejects_incomplete_event_window():
    stock, market, dates = sample_returns()
    raises(dm.market_model_event_study, stock, market, dates[-2], half_window=5)


def test_event_study_rejects_bad_parameters():
    stock, market, dates = sample_returns()
    raises(dm.market_model_event_study, stock, market, dates[150], estimation=2)
    raises(dm.market_model_event_study, stock, market, dates[150], gap=-1)
    raises(dm.market_model_event_study, stock, market, dates[150], half_window=-1)
    raises(dm.market_model_event_study, stock, market, dates[150], estimation=120.5)


def test_event_study_rejects_missing_event_date():
    stock, market, _ = sample_returns()
    raises(dm.market_model_event_study, stock, market, "2030-01-01")


def test_event_study_rejects_unsorted_or_duplicate_dates():
    stock, market, dates = sample_returns()
    raises(dm.market_model_event_study, stock.iloc[::-1], market, dates[150])
    doubled = pd.concat([market, market.iloc[:1]]).sort_index()
    raises(dm.market_model_event_study, stock, doubled, dates[150])


def test_event_study_rejects_infinite_data():
    stock, market, dates = sample_returns()
    stock = stock.copy()
    stock.iloc[10] = np.inf
    raises(dm.market_model_event_study, stock, market, dates[150])


def test_event_study_rejects_constant_market():
    stock, market, dates = sample_returns()
    raises(dm.market_model_event_study, stock, market * 0 + 0.01, dates[150])


def test_prediction_error_exceeds_residual_std():
    stock, market, dates = sample_returns(noise=1.0)
    study = dm.market_model_event_study(stock, market, dates[150])
    assert (study.table["std_error"] > study.residual_std).all()


def test_car_of_one_day_matches_the_daily_t_stat():
    stock, market, dates = sample_returns(noise=1.0)
    study = dm.market_model_event_study(stock, market, dates[150])
    row = study.table[study.table["day"] == 0].iloc[0]
    car, t = dm.cumulative_abnormal(study, 0, 0)
    close(car, row["abnormal"])
    close(t, row["t_stat"])


def test_car_rejects_incomplete_or_incoherent_windows():
    stock, market, dates = sample_returns(noise=1.0)
    study = dm.market_model_event_study(stock, market, dates[150])
    raises(dm.cumulative_abnormal, study, -100, 100)
    raises(dm.cumulative_abnormal, study, 2, 1)
    raises(dm.cumulative_abnormal, study, 0.5, 1)


def test_event_study_rejects_overlap_with_the_event_window():
    stock, market, dates = sample_returns(noise=1.0)
    raises(dm.market_model_event_study, stock, market, dates[150], gap=4, half_window=5)
    dm.market_model_event_study(stock, market, dates[150], gap=5, half_window=5)


def test_event_study_allows_a_leading_missing_value():
    stock, market, dates = sample_returns(noise=1.0)
    stock.iloc[0] = np.nan
    market.iloc[0] = np.nan
    assert len(dm.market_model_event_study(stock, market, dates[150]).table) == 11


def test_event_study_rejects_internal_missing_values():
    stock, market, dates = sample_returns(noise=1.0)
    stock.iloc[148] = np.nan
    raises(dm.market_model_event_study, stock, market, dates[150])


def test_event_study_rejects_misaligned_series():
    stock, market, dates = sample_returns(noise=1.0)
    raises(dm.market_model_event_study, stock.drop(dates[100]), market, dates[150])


def test_event_days_stay_tied_to_the_dates():
    stock, market, dates = sample_returns(noise=1.0)
    table = dm.market_model_event_study(stock, market, dates[150]).table
    assert table.index[table["day"] == 0][0] == dates[150]
    assert table.index[table["day"] == -2][0] == dates[148]


def test_exchange_holidays_are_not_treated_as_missing():
    stock, market, dates = sample_returns(noise=1.0)
    holiday = dates[140]
    study = dm.market_model_event_study(stock.drop(holiday), market.drop(holiday), dates[150])
    assert study.observations == 120


# --- Financial functions -----------------------------------------------------

def test_financial_functions_reject_invalid_denominators():
    raises(dm.premium, 100, 0)
    raises(dm.implied_diluted_shares, 100, 10, 5, 0)
    raises(dm.implied_diluted_shares, -100, 0, 0, 10)
    raises(dm.valuation_multiples, 10, 100, 1, 1, 0, 1, 1, 1)
    raises(dm.pro_forma_eps, 100, 10, 0, 100, 0.01, 0.2)
    raises(dm.breakeven_yield, 10, 0, 0.2)
    raises(dm.accretion, 100, 10, 10, 100, 0.01, 1.0)
    raises(dm.accretion, 100, 10, 10, -5, 0.01, 0.2)
    raises(dm.premium, math.nan, 10)


def test_probability_requires_offer_above_fallback():
    raises(dm.implied_completion_probability, 80, 60, 60)
    raises(dm.implied_completion_probability, 80, 50, 60)


def test_probability_outside_range_warns_without_clipping():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        close(dm.implied_completion_probability(110, 100, 60), 1.25)
    assert len(caught) == 1


def test_probability_in_range_does_not_warn():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dm.implied_completion_probability(80, 100, 60)
    assert not caught


def test_multiples_are_nan_when_not_meaningful():
    m = dm.valuation_multiples(10, 100, 0, 0, 100, -20, 5, -3)
    assert math.isnan(m["EV/EBITDA"]) and math.isnan(m["P/E"])
    close(m["EV/Revenue"], 10)


def test_negative_results_are_allowed():
    assert dm.accretion(100, -30, 10, 100, -0.01, 0.2) < 0
    assert dm.pro_forma_eps(-50, 10, 10, 0, 0, 0.2) < 0
    assert math.isnan(dm.accretion(-50, 10, 10, 0, 0, 0.2))


def test_zero_yield_removes_the_effect_of_price():
    low = dm.accretion(100, 10, 10, 500, 0, 0.2)
    high = dm.accretion(100, 10, 10, 900, 0, 0.2)
    close(low, high)


def test_treasury_method():
    close(dm.treasury_method_shares(100, 10, 20, 50, 100), 120)
    close(dm.treasury_method_shares(100, 10, 20, 150, 100), 110)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} tests passed")
