# Watchlist export

The Watchlists page exports lists as files for TradingView (.txt) and thinkorswim (.csv). Two flows: the **active list** (the Export menu's first two items) and **several lists in one file** (its third item, "Export multiple lists…"). Decision record: docs/decisions.md, 2026-10-09. Visual rules: docs/design-system.md, "`ExportMenu`".

## Single list (unchanged except the CSV header)

- **TradingView:** built in the browser from the table's rows (`app/watchlist/page.tsx::handleExportTradingView` → `lib/watchlistExport.ts::buildTradingViewText`). One comma-separated line; a `###Sector` item starts a section; each ticker is `EXCHANGE:SYMBOL`. Rows with no sector go under a literal `###Other` (every ETF does). A row with no cached exchange is skipped, and a section left empty is dropped. Filename `<slug>.txt`.
- **thinkorswim:** `GET /api/watchlists/{id}/export/thinkorswim`. Bare tickers, one per line, **no header row** (the `Symbol` header was removed 2026-10-09 so both thinkorswim exports match). Filename `<slug>_thinkorswim.csv`. An empty list gives an empty file.
- The exchange is FMP's `exchangeShortName` string written as is: no prefix mapping, no share-class conversion (BRK-B stays `BRK-B`). Whether TradingView accepts every value (AMEX, CBOE, OTC) is not verified here.

## Several lists, one file

The user ticks lists in an inline panel (`components/watchlist/MultiExportPanel.tsx`) and picks ONE format.

- **Data:** `GET /api/watchlists/export-data?ids=1&ids=2` (`main.py::watchlists_export_data`, `data/watchlist_data.py::get_export_tickers`). Per requested list, in the order asked: `{id, name, tickers: [{ticker, exchange, sector}]}`, tickers in added order. **Stored data only:** one cache-only read of the cached profile per ticker (exchange = `exchangeShortName` or `exchange`; sector = profile `sector`), no score, Step 1 or consensus computation, no FMP call, no write. A fund (`isEtf`/`isFund`) has sector `null`, the same rule `TickerScore.sector` applies, so it lands in "Other"; a ticker with no cached profile has both `null`. An unknown id is a 404 naming it (nothing partial); no ids is a 422; a repeated id is returned once.
- **Builder:** `lib/watchlistExport.ts::buildMultiExport(lists, format)`, pure. The panel orders the chosen lists by natural name order (E2 before E10), so the file does not depend on tick order.
  - **De-duplication:** across lists, by symbol, the first occurrence wins (its exchange and sector too) and later ones count as duplicates.
  - **TradingView:** `buildTradingViewText` on the merged rows, i.e. grouped by sector across all lists, sections in first-encounter order, first-seen order inside a sector. List names do not appear in the file. Tickers with no cached exchange are skipped and counted.
  - **thinkorswim:** bare tickers, one per line, no header, de-duplicated, first-seen order. Nothing is skipped (no exchange is needed).
  - **Empty lists** contribute nothing and are counted.
- **Filename:** `fathom-watchlists_<n>-lists_<YYYY-MM-DD>_tradingview.txt` or `..._thinkorswim.csv` (`n` = lists ticked, local date). No list name is used, so there is no slug logic and no special-character problem.
- **Result line** under the panel: "Exported 42 symbols from 3 lists · 5 duplicates removed · 1 empty list skipped · 2 skipped (no cached exchange)". Zero counts are left out; the skipped-for-exchange part is drawn in the `caution` tone. If no symbol is written the line reads "Nothing to export" and no file is downloaded.

## Known limits

- US-listed tickers only (docs/specs/fmp-data-and-bar-cache.md, "US-listed tickers only"): no HK or France symbols exist on a list, so there is no mapping for them.
- A ticker added to a list but never opened has no cached profile, so it has no exchange: it is skipped in the TradingView file (still written to the thinkorswim one).
- TradingView's handling of one symbol in several sections is avoided rather than relied on: the file is de-duplicated.
