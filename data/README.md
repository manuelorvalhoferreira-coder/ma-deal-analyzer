# Data

Third-party data stays subject to its providers' terms and is not covered by the project's MIT License. Web data in this project was retrieved on 3 November 2026 during its preparation. Retrieval logs are not part of the repository.

## `inputs.csv`

Financial inputs and deal terms, with one row per figure.

- **`period`:** the date or financial period the figure refers to.
- **`published`:** the publication date, to the precision known. `not stated` means the source gave no date I could confirm.
- **`source` and `url`:** where the figure comes from. Primary filings are used where I could read them.
- Some values are simple sums described in the `source` column, such as cash plus short-term investments.

The file holds single observations, not price series. The Take-Two close is a single Yahoo Finance observation, because I found no alternative source for that date. The two Activision closes from 2023 are short excerpts, shown unaltered with their source.

## `market_prices.csv` (not in this repository)

The market sections of the notebook need this file. To re-run them, get daily data from a provider whose terms allow your use, save it as a CSV with the columns below, and run:

```bash
python tools/import_prices.py path/to/your_prices.csv
```

| Column | Content |
|---|---|
| `date` | Trading date, as YYYY-MM-DD, in ascending order |
| `msft_close` | Microsoft close |
| `msft_adj_close` | Microsoft close adjusted for dividends and splits |
| `sp500_close` | S&P 500 price index close |
| `sp500tr_close` | S&P 500 total return index close |
| `ndx_close` | Nasdaq-100 price index close |

The importer rejects files with missing columns or values, non-positive prices, duplicate or unsorted dates, gaps of more than 5 calendar days, or too little history around 18 January 2022. It needs at least 131 observations before that date and 5 after it. Rows outside 1 July 2021 to 15 February 2022 are removed and reported. Results may differ slightly between providers and download dates.

## How the saved results were produced

The saved event-study results used 159 daily observations from Yahoo Finance's chart endpoint (symbols MSFT, ^GSPC, ^SP500TR and ^NDX). Those series are not distributed here. Yahoo's terms restrict automated data collection without permission, so the repository has no automatic downloader, and the published tables show model results rather than daily prices or returns.

## Prices not available as a series

Yahoo Finance and Nasdaq returned no data for ATVI, and Yahoo returned none for EA on the dates requested. These prices are single values in `inputs.csv`, from the sources listed there.
