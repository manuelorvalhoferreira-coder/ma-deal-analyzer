"""Synthetic checks for data validation, importing and notebook execution.

These use made-up data and never contact a data provider, so they do not show
that any provider's files work. Run from the repository root:
python tests/test_tools.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import price_data as pdata


def synthetic_prices():
    dates = pd.bdate_range(pdata.START_DATE, pdata.END_DATE)
    frame = pd.DataFrame({"date": dates.strftime("%Y-%m-%d")})
    for i, column in enumerate(pdata.PRICE_COLUMNS):
        frame[column] = 100.0 + i + np.arange(len(dates)) * 0.1
    return frame


def rejects(frame, **kwargs):
    try:
        pdata.validate_market_prices(frame, **kwargs)
    except ValueError:
        return
    raise AssertionError("Invalid price data was accepted")


def test_valid_data_is_accepted():
    table = pdata.validate_market_prices(synthetic_prices())
    assert list(table.columns) == pdata.PRICE_COLUMNS and isinstance(table.index, pd.DatetimeIndex)


def test_empty_table_is_rejected():
    rejects(synthetic_prices().iloc[0:0])


def test_missing_and_extra_columns_are_rejected():
    rejects(synthetic_prices().drop(columns="ndx_close"))
    rejects(synthetic_prices().assign(other=1.0))


def test_bad_values_are_rejected():
    for value in (np.nan, np.inf, -1.0, 0.0, "text"):
        frame = synthetic_prices().astype({"sp500_close": object})
        frame.loc[20, "sp500_close"] = value
        rejects(frame)


def test_bad_dates_are_rejected():
    duplicate = synthetic_prices()
    duplicate.loc[21, "date"] = duplicate.loc[20, "date"]
    rejects(duplicate)
    rejects(synthetic_prices().iloc[::-1])
    invalid = synthetic_prices()
    invalid.loc[5, "date"] = "not-a-date"
    rejects(invalid)
    outside = synthetic_prices()
    outside.loc[outside.index[-1], "date"] = "2030-01-01"
    rejects(outside)


def test_insufficient_coverage_is_rejected():
    frame = synthetic_prices()
    rejects(frame[frame["date"] >= "2021-09-01"])
    rejects(frame[frame["date"] <= "2022-01-20"])
    rejects(frame[frame["date"] != pdata.EVENT_DATE])


def test_unexpected_gap_is_rejected_but_holidays_are_allowed():
    frame = synthetic_prices()
    rejects(frame[~frame["date"].between("2021-10-04", "2021-10-15")])
    pdata.validate_market_prices(frame[~frame["date"].isin(["2021-11-25", "2021-12-24", "2022-01-17"])])


def run_tool(folder, *arguments):
    return subprocess.run([sys.executable, str(ROOT / "tools" / arguments[0]), *arguments[1:]],
                          cwd=folder, capture_output=True, text=True)


def small_notebook(path, source):
    cell = {"cell_type": "code", "id": "c0", "metadata": {}, "execution_count": None, "outputs": [],
            "source": [source]}
    path.write_text(json.dumps({"cells": [cell], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))


def project_folder():
    folder = Path(tempfile.mkdtemp())
    (folder / "data").mkdir()
    (folder / "charts").mkdir()
    (folder / "charts" / "old.png").write_text("old chart")
    return folder


def test_import_saves_valid_data_and_reports_removed_rows():
    folder = project_folder()
    frame = synthetic_prices()
    extra = frame.iloc[[-1]].assign(date="2022-02-16")
    pd.concat([frame, extra]).to_csv(folder / "source.csv", index=False)
    result = run_tool(folder, "import_prices.py", "source.csv")
    assert result.returncode == 0, result.stderr
    assert "removed 1 rows" in result.stdout
    assert len(pd.read_csv(folder / "data" / "market_prices.csv")) == len(frame)
    shutil.rmtree(folder)


def test_import_keeps_existing_file_when_input_is_invalid():
    folder = project_folder()
    (folder / "data" / "market_prices.csv").write_text("existing")
    synthetic_prices().drop(columns="ndx_close").to_csv(folder / "source.csv", index=False)
    result = run_tool(folder, "import_prices.py", "source.csv")
    assert result.returncode != 0
    assert (folder / "data" / "market_prices.csv").read_text() == "existing"
    shutil.rmtree(folder)


def test_failed_run_preserves_notebook_and_charts():
    folder = project_folder()
    (folder / "data" / "market_prices.csv").write_text("present")
    source = ("import os, pathlib\n"
              "pathlib.Path(os.environ['CHARTS_DIR'], 'new.png').write_text('new')\n"
              "raise RuntimeError('deliberate failure')\n")
    small_notebook(folder / "analysis.ipynb", source)
    before = (folder / "analysis.ipynb").read_text()
    result = run_tool(folder, "execute_notebook.py")
    assert result.returncode != 0
    assert (folder / "analysis.ipynb").read_text() == before
    assert [p.name for p in (folder / "charts").iterdir()] == ["old.png"]
    assert not [p for p in folder.iterdir() if p.name.startswith(".notebook-run-")]
    shutil.rmtree(folder)


def test_successful_run_replaces_outputs():
    folder = project_folder()
    (folder / "data" / "market_prices.csv").write_text("present")
    source = ("import os, pathlib\n"
              "pathlib.Path(os.environ['CHARTS_DIR'], 'new.png').write_text('new')\n"
              "print('done')\n")
    small_notebook(folder / "analysis.ipynb", source)
    result = run_tool(folder, "execute_notebook.py")
    assert result.returncode == 0, result.stderr
    assert [p.name for p in (folder / "charts").iterdir()] == ["new.png"]
    assert "done" in "".join(json.loads((folder / "analysis.ipynb").read_text())["cells"][0]["outputs"][0]["text"])
    shutil.rmtree(folder)


def test_missing_data_blocks_a_full_run_and_partial_run_is_separate():
    folder = project_folder()
    source = "import os, pathlib\npathlib.Path(os.environ['CHARTS_DIR'], 'new.png').write_text('new')\n"
    small_notebook(folder / "analysis.ipynb", source)
    before = (folder / "analysis.ipynb").read_text()
    assert run_tool(folder, "execute_notebook.py").returncode != 0
    result = run_tool(folder, "execute_notebook.py", "--partial")
    assert result.returncode == 0, result.stderr
    assert "PARTIAL RUN" in result.stdout
    assert (folder / "analysis.ipynb").read_text() == before
    assert [p.name for p in (folder / "charts").iterdir()] == ["old.png"]
    assert (folder / "partial_run" / "charts" / "new.png").exists()
    assert os.path.exists(folder / "partial_run" / "analysis_partial.ipynb")
    shutil.rmtree(folder)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} tool checks passed (synthetic data only)")
