"""Run analysis.ipynb from top to bottom and save its outputs.

Run from the repository root:

    python tools/execute_notebook.py            Full run; needs data/market_prices.csv
    python tools/execute_notebook.py --partial  Runs without market data

A full run replaces analysis.ipynb and charts/ only after every cell succeeds, so
a failure keeps the previous version. A partial run never touches them: it saves
to partial_run/, so it cannot be mistaken for the complete analysis.

This tool runs Python code cells and captures printed text and Matplotlib figures.
It does not support IPython magics, widgets or rich display objects, and it is not
a full replacement for Jupyter.
"""

import base64
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import traceback

os.environ["MPLBACKEND"] = "Agg"

import matplotlib.pyplot as plt

NOTEBOOK = "analysis.ipynb"
CHARTS = "charts"
PARTIAL_DIR = "partial_run"
PRICES = "data/market_prices.csv"


def lines(text):
    return text.splitlines(keepends=True)


def run_cells(notebook):
    """Execute the code cells in order, storing outputs in the notebook object."""
    figures = []

    def capture_figures(*args, **kwargs):
        for number in plt.get_fignums():
            buffer = io.BytesIO()
            plt.figure(number).savefig(buffer, format="png", bbox_inches="tight", facecolor="white")
            figures.append(base64.b64encode(buffer.getvalue()).decode())
        plt.close("all")

    plt.show = capture_figures
    namespace = {"__name__": "__main__"}
    count = 0
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        count += 1
        figures.clear()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exec(compile("".join(cell["source"]), cell["id"], "exec"), namespace)
        outputs = []
        if stdout.getvalue():
            outputs.append({"output_type": "stream", "name": "stdout", "text": lines(stdout.getvalue())})
        for image in figures:
            outputs.append({"output_type": "display_data", "metadata": {},
                            "data": {"image/png": image, "text/plain": ["<Figure>"]}})
        cell["outputs"] = outputs
        cell["execution_count"] = count
    return count


def write_notebook(notebook, path):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(notebook, handle, indent=1, ensure_ascii=False)
        handle.write("\n")


def main(arguments):
    partial = arguments == ["--partial"]
    if arguments and not partial:
        sys.exit("Usage: python tools/execute_notebook.py [--partial]")
    if not partial and not os.path.exists(PRICES):
        sys.exit("Market data is missing, so nothing was changed. See data/README.md to import it, "
                 "or use --partial to run the other sections.")
    if partial and os.path.exists(PRICES):
        sys.exit("--partial is only for runs without market data. Run without it.")

    with open(NOTEBOOK, encoding="utf-8") as handle:
        notebook = json.load(handle)

    work = tempfile.mkdtemp(prefix=".notebook-run-", dir=".")
    try:
        work_charts = os.path.join(work, CHARTS)
        os.makedirs(work_charts)
        os.environ["CHARTS_DIR"] = work_charts
        try:
            count = run_cells(notebook)
        except Exception:
            traceback.print_exc()
            sys.exit("A cell failed, so the existing notebook and charts were kept.")

        notebook["metadata"].setdefault("language_info", {})["version"] = sys.version.split()[0]
        chart_count = len(os.listdir(work_charts))
        if partial:
            shutil.rmtree(PARTIAL_DIR, ignore_errors=True)
            os.makedirs(PARTIAL_DIR)
            write_notebook(notebook, os.path.join(PARTIAL_DIR, "analysis_partial.ipynb"))
            os.replace(work_charts, os.path.join(PARTIAL_DIR, CHARTS))
            print(f"PARTIAL RUN: executed {count} code cells and {chart_count} charts, saved to {PARTIAL_DIR}/. "
                  "Market sections were skipped, and the saved analysis was not changed.")
            return

        work_notebook = os.path.join(work, NOTEBOOK)
        write_notebook(notebook, work_notebook)
        if os.path.exists(CHARTS):
            os.replace(CHARTS, os.path.join(work, "previous_charts"))
        os.replace(work_charts, CHARTS)
        os.replace(work_notebook, NOTEBOOK)
        print(f"FULL RUN: executed {count} code cells; regenerated {chart_count} charts")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:])
