# Local Stock Lab

A local stock and options research app for separating **technical strength**,
**entry readiness**, and **options contract quality**. It explains the evidence
behind its classifications and keeps research observations in a local SQLite
database. It does not place orders or import broker positions.

## What you can explore

| Page | Purpose |
| --- | --- |
| Dashboard | Review technical setups, structural entry plans, and readiness blockers. |
| Options | Filter and rank call contracts by DTE, delta, liquidity, IV, and data quality. |
| Classification | Review research profiles and explicitly accept or reject proposed role changes. |
| Features | Browse the available workflows and terminology. |

A strong stock is not automatically a good entry. A qualified equity setup is
not automatically a suitable option. Scores describe configured rules and data;
they are not probabilities of profit.

## Quick start (macOS, Python 3.12+)

Clone into a new directory, then run the following commands from the project
root. The copy commands are for first-time setup; do not overwrite an existing
`.env` or personal configuration when updating the app.

```bash
git clone https://github.com/luonan54/trading_lab.git
cd trading_lab
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
cp config/watchlist.example.yaml config/watchlist.yaml
cp config/strategy.example.yaml config/strategy.yaml
cp config/classification.example.yaml config/classification.yaml
cp config/starter.example.yaml config/starter.yaml
python -m uvicorn app.main:app --host 127.0.0.1 --port 9068
```

Open <http://127.0.0.1:9068/>. Keep the terminal running; stop with Ctrl+C.
For subsequent launches, activate `.venv` and run the same uvicorn command from
the project root. The default database path is relative to the working directory.

An empty dashboard is expected initially. Follow the configuration sections
below, restart the app, then request a scan from the dashboard. Pages can load
without provider credentials; live market-data requests cannot.

## Connect Alpaca

Put your own credentials in the local `.env` file. The tracked
[.env.example](.env.example) intentionally has blank credential values.

| Variable | Purpose / default |
| --- | --- |
| `ALPACA_API_KEY` | Your Alpaca API key. |
| `ALPACA_API_SECRET` | Your Alpaca API secret. |
| `ALPACA_DATA_FEED` | Equity feed; defaults to `iex`. |
| `ALPACA_OPTIONS_FEED` | Options feed; defaults to `indicative`. |
| `ALPACA_TRADING_BASE_URL` | Defaults to `https://paper-api.alpaca.markets`; used for option contract metadata. |
| `DATABASE_URL` | Defaults to `sqlite:///data/ceg_trader.db`. |

Use paper credentials with the paper endpoint. Data requests use
`https://data.alpaca.markets`. See [Alpaca documentation](https://docs.alpaca.markets/)
for credential setup and current data entitlements. The default equity feed is
not consolidated SIP, and the options feed is indicative; displayed prices can
differ from another broker. Changing a feed setting does not grant access to it.

Restart after configuration changes. Existing process environment variables take
precedence over values loaded from `.env`; check both if a change seems ignored.

## Authentication and local access

This app has **no user login, session authentication, or per-user authorization**.
Anyone who can reach its HTTP service can access its exposed routes, including
scan and profile mutation endpoints. Keep it bound to `127.0.0.1`; this version
is not designed for public hosting or shared multi-user access.

Provider authentication happens in the Python backend:

1. [`load_config()`](app/config.py) reads `.env` and environment variables.
2. [`create_app()`](app/main.py) initializes the scan services with that configuration.
3. [`AlpacaMarketDataClient`](app/alpaca.py) and
   [`AlpacaOptionsDataProvider`](app/options/provider.py) send credentials over HTTPS
   using `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY` headers.
4. The services process responses and return research results to the browser.

Credentials are ordinary strings held in backend memory, and `.env` is a local
plaintext file, not an encrypted credential vault. There is no OAuth, JWT,
access-token refresh, or in-app key rotation flow. Rotate credentials with the
provider, update the local configuration, and restart. `next_page_token` in the
provider code is a pagination cursor, not an authentication token.

`/health` reports whether both credential values are present; it does not verify
that Alpaca accepts them. Options errors distinguish missing credentials,
authentication rejection (401), and forbidden access or feed entitlement (403).

## Add your own symbols and preferences

`config/watchlist.example.yaml` intentionally contains only `symbols: {}`.
Edit the ignored `config/watchlist.yaml`, not the tracked example. The following
names are placeholders, not real ticker recommendations: replace both with your
own valid uppercase symbols before enabling them.

```yaml
symbols:
  YOUR_BENCHMARK:
    enabled: true
    benchmark: true
    company_quality: 0
  YOUR_STOCK:
    enabled: true
    company_quality: 1.0
    groups: [leader_long_call]
    benchmark_tags: [YOUR_BENCHMARK]
    asset_class: equity
    confirmed_profile:
      primary_role: GROWTH
      risk_tier: HIGH
```

`company_quality` is on a 0-2 scale, not 0-10. Each referenced benchmark must
also be an enabled benchmark entry. Groups are `leader_long_call`,
`short_term_watch`, `long_term_core`, `long_term_growth`, `high_risk_growth`.
Group selection is your decision, not a signal to buy. The example role and risk
tier are illustrative; choose values appropriate to your own research.

At startup, eligible symbols with explicit `confirmed_profile` metadata can
initialize new database profiles. Existing confirmed profiles are not overwritten
by YAML edits: the database is the runtime authority when available. A stock
without a confirmed profile may be absent from the normal scan universe.

For Classification/confirmed-profile workflows, see
`ConfirmedProfileBootstrap` in `app/classification/models.py`; only supply your
own role, risk tier and optional weights. Do not import another owner's database.
This package does not import broker positions or claim to track real holdings.

The generated strategy file uses generic code defaults rather than copying the
owner's settings. Override fields in your local `config/strategy.yaml`:

```yaml
alpaca: {feed: iex}
thresholds: {momentum_rsi: 50}
structure: {}
entry: {min_reward_risk: 2.0}
options:
  long_call: {min_dte: 60, max_dte: 120}
```

Full validated settings and allowed ranges live in `app/config.py`,
`app/entry_models.py`, `app/classification/config.py` and
`app/starter/config.py`. Defaults are unbacktested research settings, not
personalized risk advice. Consistent preferred DTE/delta ranges are required
when changing their outer limits.

## Architecture and decision logic

1. `app/alpaca.py` fetches bars; indicators and structural features use completed
   bars. `app/service.py` orchestrates scans and persistence.
2. `app/strategy.py` classifies technical trend. A strong stock is not necessarily
   a good entry. `app/entry.py` evaluates a separate structural entry plan.
3. E is the latest completed regular-session 15-minute close; S is structural
   invalidation with a volatility buffer; T is confirmed prior resistance.
   Stock reward/risk is `(T - E) / (E - S)`, only meaningful for `S < E < T`.
   Missing structure does not manufacture a target, stop or R.
4. Anchored levels, extension/noise limits, completed-bar confirmation, benchmark
   checks, RSI and quote freshness determine readiness. Repeated refreshes of the
   same bars do not create new confirmation. Poor new-entry suitability does not
   instruct an existing holder to sell.
5. `app/options/` separately evaluates contract fit, liquidity, spread, DTE,
   delta, IV and data quality. Equity readiness is not options suitability.
   Historical/manual research results are not current execution qualification.
6. `app/main.py` and `app/options/ui.py` show prices and conclusions, with detailed
   evidence inside Explanation. Shared emoji checks preserve each gate's evidence.
   `app/classification/` manages local human-confirmed profile decisions.

Stock R is not option R, a probability, or a guarantee. Gaps and slippage can
exceed a planned loss. The app has no backtest validating these defaults.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Missing YAML file at startup | Run all four first-time configuration copy commands. |
| Empty dashboard or unknown/unconfirmed ticker | The sample watchlist is empty. Add valid symbols and explicit confirmed profiles, restart, and scan. Existing database profiles take precedence over YAML edits. |
| Missing Alpaca credentials | Set both key fields in local `.env`, then restart. |
| Provider HTTP 401 | Check the key/secret pair and the paper/live endpoint match. `/health` alone cannot validate credentials. |
| Provider HTTP 403 | Check account permissions and the selected feed; OPRA requires the appropriate entitlement. |
| HTTP 429 or timeout | Check provider limits and network availability; retry later. A timeout alone does not prove a key expired. |
| No suitable option contracts | Inspect eligibility, filters, and data-quality reasons; an empty result can be valid. |
| Address already in use | Run with `--port 9069` and open `http://127.0.0.1:9069/`. |

## Scope and validation status

- Research only: no order execution, automated position sizing, or broker holdings import.
- Default thresholds are unbacktested research settings, not personalized advice.
  Gaps, stale data, and slippage can invalidate an apparent setup.
- The Starter module is dormant, disabled by default, and has an empty approved
  universe. Review its policy before enabling experimental workflows.
- This sharing version excludes original tests and fixtures. Python syntax was
  checked during the initial import; application startup, live Alpaca access, and
  end-to-end behavior were not verified in that import. Installing the `test`
  extra does not restore the omitted test suite.
- Legacy internal names such as the `ceg-trader` package and `ceg_trader.db` remain
  for compatibility; the displayed project name is Local Stock Lab.

## Privacy and sharing

The sharing copy excludes personal credentials, actual watchlists, confirmed
profiles, databases, scan history, logs, and the source project's Git history.
Keep `.env`, personal configuration, runtime data, and account screenshots local.
The [.gitignore](.gitignore) covers common local files, but cannot protect secrets
added to tracked files or files deliberately force-added to Git.

Source code includes the scoring logic and default thresholds. Keeping your
personal configuration private does not hide those rules in a public repository.

See [Sharing a clean project copy](docs/sharing.md) for export and upload guidance.
[EXPORT-MANIFEST.json](EXPORT-MANIFEST.json) records the initial sharing snapshot;
it is not a current-file checksum list or a security certification. Later edits,
including this README revision, can differ from those initial hashes.
