# Local Stock Lab

A local, analysis-only stock and options research app. FastAPI serves the
dashboard, Options, Classification and Features pages; SQLite stores local
observations. It does not submit trades. This is a fresh sharing copy, not a
backup of the original owner's portfolio.

## What is deliberately absent

No API keys, account credentials, positions, watchlist, confirmed profiles,
database, scan history, logs, Git history, private document links or original
tests/fixtures are included. Only explicitly selected application files and the
package manifest are copied. All configuration examples are generated anew.
The original product name is replaced with a neutral name.

The dormant Starter research module is disabled, with an empty stock universe
instead of the original fixed list. Its export-only validation allows a future
owner to supply their own `approved_tickers`; the original app is not changed.
Do not enable experimental research without reviewing its policy.

`EXPORT-MANIFEST.json` records hashes of the initial exported files, not an
ongoing security certification. Heuristic credential checks cannot guarantee
that all sensitive information was found. Review every file before sharing.

## Run locally (macOS, Python 3.12+)

Use a separate folder from any existing installation. Work from this folder
each time: the default SQLite path is relative to the working directory.

```bash
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

Open <http://127.0.0.1:9068/>. If port 9068 is already in use, use 9069 instead.
The terminal must remain open. Stop with Ctrl+C; restart with the same uvicorn
command from this folder and the activated environment. No machine-specific
LaunchAgent or background task is installed.

An empty dashboard is expected before adding symbols and scanning. Local pages
can load without credentials; live data cannot. This is a localhost app, not a
hardened multi-user internet service: do not expose its port publicly.

## Connect your own Alpaca account

Create your own account at <https://alpaca.markets/> and generate keys in the
Paper Trading dashboard. Enter them only in your local `.env`, never in source
code, example files, screenshots, Git commits or GitHub repository settings.

The app reads `ALPACA_API_KEY` and `ALPACA_API_SECRET`. Keep
`ALPACA_TRADING_BASE_URL=https://paper-api.alpaca.markets` for paper credentials;
paper and live credentials/endpoints are not interchangeable.
Market data uses <https://data.alpaca.markets>. See the provider's current
documentation at <https://docs.alpaca.markets/> for account and data entitlements.

The default equity feed is `iex` (not consolidated SIP); the default options
feed is `indicative`. Prices can differ from another broker. Enable paid feeds
only if your account is authorized. Restart after editing `.env`.
Timeouts can have network, provider or local-process causes; they do not by
themselves establish that a key expired or that a particular network is blocked.

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
```

`company_quality` is on a 0-2 scale, not 0-10. Each referenced benchmark must
also be an enabled benchmark entry. Groups are `leader_long_call`,
`short_term_watch`, `long_term_core`, `long_term_growth`, `high_risk_growth`.
Group selection is your decision, not a signal to buy.

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

## Manual upload to YOUR personal GitHub

**First verify that you own the code and may share it.** Removing identifiers
or keys does not grant publishing rights to employer or third-party code. Use
only an approved GitHub Desktop installation on a managed computer, or follow
your organization's approved process on an authorized personal computer.
This exporter installs nothing and does not bypass device or network policy.

### GitHub Desktop (recommended)

1. **Copy this export folder outside every existing Git checkout first**, for
   example into a new folder under your personal Documents directory. The
   exporter's default `exports/` location is still inside the original worktree;
   Desktop may otherwise discover its parent repository. Never add or publish
   the original project, worktree, or its `.git` file.
2. In Desktop Settings/Preferences -> Accounts, verify the signed-in GitHub.com
   account is your **personal account**. Under Git, verify the commit author
   name/email; a personal GitHub noreply email avoids exposing a work email.
   Account sign-in and commit identity are separate settings.
3. File -> Add Local Repository -> select this exported folder. It has no `.git`;
   use the offered **Create a Repository here** action. Check the displayed
   final local path is exactly this folder, not an empty nested folder.
   Do not initialize from, copy, or attach the original Git history.
   If Desktop shows old commits, an existing remote, or the original project's
   path, stop: that is not the fresh sharing repository.
4. Review the initial Changes list file by file. `.env`, actual `config/*.yaml`,
   databases, logs and holdings must not appear. `.env.example` must have blank
   credential values. Do not force-add ignored files. Do not commit screenshots
   or real scan/portfolio outputs.
5. Commit the reviewed sharing files, then choose Publish Repository. Confirm
   the owner is your personal username (not an employer organization) and keep
   **Keep this code private** selected for the first publication.
6. Verify the repository URL and Files/Commits in your browser. Check again before
   later changing visibility to public. A private repository is still an upload.

If Desktop does not offer in-place creation, create a new empty personal
repository in Desktop and copy the **contents of this export only**, including
`.gitignore` and `.env.example`, into it. Do not copy the original app folder.

### Browser alternative

On GitHub.com verify your personal login, create a new private repository under
your personal owner, then Add file -> Upload files. Upload this export's contents,
preserving subdirectories, in batches if required. Uploading a ZIP stores a ZIP;
GitHub does not unpack it into a runnable repository.

Finder Cmd+Shift+. shows hidden files. Ensure `.gitignore` and `.env.example`
are included (create them manually in the GitHub editor if the picker omits
them). Do not upload the local `.env` or actual configs. GitHub Desktop handles
these hidden files and folder structure more reliably.

## Safety after publishing

The ignore rules prevent ordinary addition of private files; they do not protect
files already tracked, force-adds, edited examples, comments or commit messages.
Never paste real keys into a tracked file. If a key is ever committed or uploaded,
revoke/rotate it with the provider immediately; deleting the latest file does
not erase history or copies. Resolve repository history exposure separately.

For a later release, export to a new empty folder, review the changes, then copy
only reviewed code/example files into the personal repository. Do not copy
runtime data back into it. No license is automatically selected; choose one
only after confirming ownership and dependency obligations.
