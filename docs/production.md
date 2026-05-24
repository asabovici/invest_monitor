# Production Scheduling

A scheduled-job runner that keeps prices, attribution metrics, sector betas, and fund profiles fresh. Each job's last status + full run history is persisted to parquet, so failures don't disappear silently.

## Built-in jobs

| Job | Default interval | What it does |
|---|---|---|
| `collect_prices` | daily | `Collector.update_all_assets(period="1mo")` — appends trailing-month prices for every asset in the security master. |
| `refresh_attribution` | daily | `AttributionEngine.refresh_all()` — incremental refresh of `daily_*.parquet` (uses v2 trade replay where available). |
| `refresh_sector_betas` | weekly | 20-year SPDR sector ETF fetch + `save_sector_betas` — keeps the implied-shock matrix current. |
| `refresh_fund_profiles` | weekly | For every held ETF/Fund: `Collector.fetch_fund_profile` → `save_fund_profile`. |

Each job runs inside try/except. Exceptions are captured into `production_runs.error_message` + a 4-frame traceback in `details`, and the job's `last_status` flips to `error` so it lights up in the dashboard's **🚨 Issues** tab.

## Three ways to wire automation

=== "One-click systemd (Linux)"

    In the dashboard's **⚙️ Production → 📅 Schedule with systemd** section, click **Install** next to any job. That writes the `.service` + `.timer` units to `~/.config/systemd/user/` and runs `systemctl --user enable --now`. From the CLI:

    ```bash
    invest-monitor production schedule list
    invest-monitor production schedule install refresh_attribution
    invest-monitor production schedule install collect_prices --interval 720
    invest-monitor production schedule uninstall refresh_attribution
    ```

    Generated unit files use:

    - `Type=oneshot`
    - `ExecStart=<runner> production run-now <job>`
    - `OnBootSec=5min`
    - `OnUnitActiveSec=<interval>min`
    - `Persistent=true` (catches up runs missed while the machine was off)
    - `StandardOutput=journal` / `StandardError=journal`

    Logs land in `journalctl --user -u invest-monitor-<job>.service`.

=== "Cron"

    ```cron
    */15 * * * * cd /path/to/invest_monitor && /usr/bin/uv run invest-monitor production run >> ~/.invest-monitor-cron.log 2>&1
    ```

    `production run` only fires jobs whose interval has elapsed since their last successful run, so it's safe to call every minute or every hour.

=== "Foreground daemon"

    ```bash
    nohup invest-monitor production daemon --check-every 60 > ~/.invest-monitor-daemon.log 2>&1 &
    ```

## Manual control

The **⚙️ Production** view in the dashboard also lets you:

- Toggle individual jobs on/off.
- Click **Run** on a row to force-execute one job (ignores schedule + enabled flag).
- Click **Run all due now** to fire every overdue job in one go.
- Inspect run history in the **📜 Recent Runs** tab and errors in the **🚨 Issues** tab.

State is per-data-dir: live (`data/`) and demo (`data_demo/`) have independent schedules + run logs.

## Adding a new job

In `src/production.py`:

```python
def _my_job(db: Database) -> dict:
    ...
    return {"key": "value pairs that get json.dumps'd into production_runs.details"}

JOB_REGISTRY["my_job"] = {
    "callable": _my_job,
    "interval_minutes": 60 * 24,
    "description": "Brief description shown in the dashboard.",
}
```

The next `JobRunner` instantiation auto-seeds `production_jobs.parquet` with a row for `my_job` (enabled by default, status `never_run`). No DB migration needed.

## Gotchas

!!! danger "systemd timer doesn't respect the dashboard Enabled toggle"
    An installed systemd timer fires regardless of the Enabled toggle inside the dashboard, because the timer runs `run-now` (which bypasses the `enabled` flag by design — that's how the per-row Run button works). If you want the toggle to gate firing, **uninstall the systemd timer** and use the `production run` path under cron instead.

!!! info "production run is idempotent"
    Only fires jobs whose interval has elapsed since their last successful run. Don't introduce side-effects in a job that aren't safe under re-execution; the runner doesn't dedupe within a single interval.

!!! info "WorkingDirectory is captured at install time"
    `WorkingDirectory` in the generated unit is the CWD when you ran the install command (typically project root). If you move the project, `production schedule uninstall <job>` then `install <job>` again to regenerate the unit with the new path.
