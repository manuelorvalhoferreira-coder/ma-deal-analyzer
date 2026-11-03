"""Checks that the inputs, notebook, README and charts agree.

Run from the repository root: python tests/test_project.py
Each check is reported as PASS, FAIL or SKIP. Checks that recompute market results
are skipped without data/market_prices.csv, which is not in the repository.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import deal_model as dm
from price_data import load_market_prices

PRICES = ROOT / "data" / "market_prices.csv"
I = dm.load_inputs(ROOT / "data" / "inputs.csv")
README = (ROOT / "README.md").read_text(encoding="utf-8")
NOTEBOOK = json.loads((ROOT / "analysis.ipynb").read_text(encoding="utf-8"))
CODE_CELLS = [c for c in NOTEBOOK["cells"] if c["cell_type"] == "code"]
MARKDOWN = "".join("".join(c["source"]) for c in NOTEBOOK["cells"] if c["cell_type"] == "markdown")


class Skipped(Exception):
    pass


def stored_summary():
    """Read the labelled results printed by the notebook's summary cell."""
    for cell in CODE_CELLS:
        if "summary = pd.Series" in "".join(cell["source"]):
            text = "".join("".join(o.get("text", [])) for o in cell["outputs"])
            rows = [re.split(r"\s{2,}", line.strip(), maxsplit=1) for line in text.splitlines() if line.strip()]
            return {row[0]: row[1] for row in rows}
    raise AssertionError("The notebook has no summary cell")


def readme_results():
    """Read the README results table as {measure: result}."""
    section = README.split("## Results")[1].split("##")[0]
    rows = re.findall(r"^\| (.+?) \| (.+?) \|$", section, flags=re.M)
    return {measure: result for measure, result in rows if measure != "Measure"}


def expected_without_market_data():
    offer = I["offer_price"]
    shares = dm.implied_diluted_shares(I["deal_value"], I["atvi_cash"], I["atvi_debt"], offer)
    basic = I["atvi_shares_issued"] - I["atvi_treasury_shares"]
    bottom_up = dm.treasury_method_shares(basic, I["atvi_rsus"], I["atvi_options"], I["atvi_option_strike"], offer)
    cash = shares * offer
    tax = I["msft_tax"] / I["msft_pretax_income"]
    policy = dm.valuation_multiples(offer, shares, I["atvi_cash"], I["atvi_debt"], I["atvi_revenue"],
                                    I["atvi_ebit"], I["atvi_da"], I["atvi_net_income"])
    alternative = dm.valuation_multiples(offer, shares, I["atvi_cash"], I["atvi_debt"], I["atvi_revenue"],
                                         I["atvi_ebit"], I["atvi_da"] + I["atvi_capsw"], I["atvi_net_income"])
    args = (I["msft_diluted_shares"], cash, 0.01, tax)
    return {
        "Premium to prior close": f"{dm.premium(offer, I['atvi_undisturbed']):.1%}",
        "Estimated diluted shares": f"{shares:.1f}m",
        "Bottom-up diluted shares": f"{bottom_up:.1f}m",
        "EV / Revenue at $95": f"{policy['EV/Revenue']:.1f}x",
        "EV / Adjusted EBITDA at $95, policy": f"{policy['EV/EBITDA']:.1f}x",
        "EV / Adjusted EBITDA at $95, alternative": f"{alternative['EV/EBITDA']:.1f}x",
        "P/E at $95": f"{policy['P/E']:.1f}x",
        "Binary-model implied probability, day 1":
            f"{dm.implied_completion_probability(I['atvi_day1_close'], offer, I['atvi_undisturbed']):.0%}",
        "Illustrative non-GAAP EPS change at 1% yield":
            f"{dm.accretion(I['msft_net_income_nongaap'], I['atvi_net_income_nongaap'], *args):+.1%}",
        "Illustrative GAAP EPS change at 1% yield":
            f"{dm.accretion(I['msft_net_income'], I['atvi_net_income'], *args, amortization=2500):+.1%}",
        "Breakeven yield, non-GAAP": f"{dm.breakeven_yield(I['atvi_net_income_nongaap'], cash, tax):.1%}",
    }


README_LABELS = {
    "Premium to prior close": "Premium to the prior close ($65.39)",
    "Estimated diluted shares": "Estimated diluted shares implied by the headline",
    "Bottom-up diluted shares": "Bottom-up diluted shares, RSUs at target and options at average strike",
    "EV / Revenue at $95": "EV / Revenue",
    "EV / Adjusted EBITDA at $95, policy": "EV / Adjusted EBITDA, main definition",
    "EV / Adjusted EBITDA at $95, alternative": "EV / Adjusted EBITDA, adding capitalized software",
    "P/E at $95": "P/E",
    "Binary-model implied probability, day 1": "Implied probability in a simplified binary model",
    "Illustrative non-GAAP EPS change at 1% yield": "Illustrative non-GAAP EPS change, no synergies, 1% yield on cash",
    "Illustrative GAAP EPS change at 1% yield": "Illustrative GAAP EPS change with $2.5bn of incremental amortization",
    "Breakeven yield, non-GAAP": "Yield on cash at which that change falls to zero",
}


def test_each_saved_metric_matches_its_recomputed_value():
    summary = stored_summary()
    for label, value in expected_without_market_data().items():
        assert summary[label] == value, f"{label}: notebook {summary[label]} != recomputed {value}"


def test_each_readme_metric_matches_its_recomputed_value():
    table = readme_results()
    for label, value in expected_without_market_data().items():
        result = table[README_LABELS[label]]
        cleaned = result.replace("About ", "")
        assert cleaned.startswith(value), f"{label}: README {result} != recomputed {value}"


def test_saved_market_result_matches_the_readme():
    saved = stored_summary()["MSFT abnormal return, day 0"]
    match = re.fullmatch(r"([+-][\d.]+%) \((t = -?[\d.]+)\)", saved)
    assert match, f"Unexpected saved result: {saved}"
    result = readme_results()["Microsoft abnormal return on announcement day"]
    assert match.group(1) in result and match.group(2) in result


def test_market_result_recomputes_from_data():
    if not PRICES.exists():
        raise Skipped("data/market_prices.csv is not available")
    prices = load_market_prices(PRICES)
    study = dm.market_model_event_study(prices["msft_adj_close"].pct_change(),
                                        prices["sp500tr_close"].pct_change(), "2022-01-18")
    car, t = dm.cumulative_abnormal(study, 0, 0)
    assert stored_summary()["MSFT abnormal return, day 0"] == f"{car:+.2%} (t = {t:.2f})"


def test_conclusions_match_between_readme_and_notebook():
    section = lambda text: re.sub(r"USD (?=\d)", "$", text.split("## My conclusions")[1].split("## What")[0]).strip()
    assert section(README) == section(MARKDOWN)


def test_notebook_is_a_complete_saved_run():
    assert [c["execution_count"] for c in CODE_CELLS] == list(range(1, len(CODE_CELLS) + 1))
    assert not any(o["output_type"] == "error" for c in CODE_CELLS for o in c["outputs"])
    text = "".join("".join(o.get("text", [])) for c in CODE_CELLS for o in c["outputs"])
    assert "FULL RUN" in text and "PARTIAL RUN" not in text


def test_charts_exist_and_match_the_notebook():
    source = "".join("".join(c["source"]) for c in CODE_CELLS)
    named = set(re.findall(r'"(\d_[a-z0-9_]+)"', source))
    on_disk = {p.stem for p in (ROOT / "charts").glob("*.png")}
    assert named == on_disk, f"{named} != {on_disk}"
    for image in re.findall(r"\(charts/([^)]+)\)", README):
        assert (ROOT / "charts" / image).exists(), image


def test_inputs_have_sources():
    frame = pd.read_csv(ROOT / "data" / "inputs.csv")
    assert frame[["period", "published", "source", "url"]].notna().all().all()
    assert frame["url"].str.startswith("https://").all()


def test_intangibles_by_class_sum_to_the_reported_total():
    total = I["close_marketing_intangibles"] + I["close_technology_intangibles"] + I["close_customer_intangibles"]
    assert total == I["close_intangibles"]


def test_market_data_is_valid_when_present():
    if not PRICES.exists():
        raise Skipped("data/market_prices.csv is not available")
    load_market_prices(PRICES)


def test_third_party_price_files_are_not_tracked():
    assert "data/market_prices.csv" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    if not (ROOT / ".git").exists():
        raise Skipped("not a Git repository")
    tracked = subprocess.run(["git", "ls-files", "data"], cwd=ROOT, capture_output=True, text=True).stdout
    assert "market_prices.csv" not in tracked and "atvi_closes" not in tracked


if __name__ == "__main__":
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for name, test in [(k, v) for k, v in list(globals().items()) if k.startswith("test_")]:
        try:
            test()
            status, note = "PASS", ""
        except Skipped as reason:
            status, note = "SKIP", f" ({reason})"
        except Exception as error:
            status, note = "FAIL", f" ({error})"
        counts[status] += 1
        print(f"{status} {name}{note}")
    print(f"{counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped")
    sys.exit(1 if counts["FAIL"] else 0)
