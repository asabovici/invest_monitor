# Front-End Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap between the React SPA in `frontend/` and the Streamlit dashboard, screen by screen, until the SPA covers every read-only analytical view.

**Architecture:** Each screen is backed by exactly one aggregate endpoint that returns everything the view renders, so a page load is one round trip. Business logic stays in `src/services/`; routers stay thin; the SPA holds no analytics. Every screen respects the portfolio scope already carried in the URL hash.

**Tech Stack:** Python 3.14 · FastAPI · pandas · pydantic · React 19 · TypeScript (`erasableSyntaxOnly`) · Vite 8 · hand-built SVG charts (no chart library)

**Spec:** No separate spec document. This plan is self-contained. The conventions it builds on are documented in `frontend/CLAUDE.md`, `src/api/CLAUDE.md`, and `src/services/CLAUDE.md`; the portfolio-scoping work it extends is described in `frontend/CLAUDE.md` § Scope.

---

## Global Constraints

- **Python ≥ 3.14.** Use `X | None`, not `Optional[X]`. Every module starts `from __future__ import annotations`.
- **The API layer never imports `src.database`, `src.reporting`, `src.attribution` directly.** Routers call `src/services/` only. Enforced by `tests/test_lint_domain_layering.py`.
- **Routers never catch `ValueError`.** `src/api/errors.py` maps service-layer messages to status codes by phrasing: `"not found"`/`"does not exist"` → 404, `"already exists"` → 409, anything else → 400. To change a status, change the service's message.
- **Every new router prefix must be added to the proxy list in `frontend/vite.config.ts`.** A missing prefix falls through to Vite and the view reports "the API isn't responding" against a healthy server. `tests/test_frontend_proxy.py` fails if you forget.
- **Scope is `portfolio: string | null`.** `null` means every portfolio and omits the query param entirely, so the unscoped request stays byte-identical to the pre-scoping URL.
- **TypeScript:** no constructor parameter properties; React 19 has no global `JSX` namespace — import `ReactNode`.
- **Colour follows the entity, never its rank.** Use `colorForType()` from `lib.ts` for asset types. Never index a palette array by position in a sorted list. Read colours via `cssVar()` at render time and call `useThemeTick()` so charts repaint on theme change.
- **Money goes through `usd()` or `compact()`; numbers carry `className="num"`.** The sign sits outside the currency symbol (`-$315`, never `$-315`).
- **Every view handles three states explicitly:** error, loading skeleton, loaded. The "start it with `invest-monitor serve`" hint renders **only** when `error.status === 0`.
- **Wide content scrolls in its own `.tablescroll`.** The page body never scrolls sideways; the layout must work at ~400px.
- **Verification per task:** `uv run python -m pytest tests/ -q` and, for frontend tasks, `cd frontend && npm run build && npm run lint`.

### Known-failing baseline

Three tests in `tests/test_database.py` fail before any of this work and are unrelated to it (stale assertions about the `assets` schema after `income_rate`/`payment_frequency` were added, and changed missing-ticker price behaviour):

```
test_init_assets_has_correct_columns
test_get_historical_prices_missing_ticker_skipped
test_get_historical_prices_all_missing_returns_empty
```

A task is green at **3 failed, N passed**. If a fourth failure appears, you caused it.

---

## The "needs a portfolio" rule

Three of the remaining screens are backed by endpoints that are **per-portfolio by path** and have no all-portfolios form:

| Endpoint | Screen |
|---|---|
| `GET /reports/attribution/{portfolio_name}` | Attribution |
| `POST /scenarios/stress/{portfolio_name}` | Stress Test |
| `GET /reports/correlation/{portfolio_name}` | Correlation |

Under scope **All portfolios** these screens cannot render. The rule for all three, implemented once in Task 3 and reused by Tasks 4 and 5:

> A screen that requires a portfolio shows a **picker prompt** under All — never an invented aggregate.

Aggregating them client-side was considered and rejected. Attribution windows differ per portfolio (measured on live data: SCHAB starts 2026-04-14 with 111 points, PRU401K starts 2021-05-10 with 1346), so summing returns across them would be arithmetic on incomparable windows. Correlation across a merged ticker set is a different computation, not a merge of matrices. Stress results *are* additive, but that would cost N requests to produce a number the backend never defined.

---

## File Structure

**Task 1 — `/performance` endpoint (backend)**
- Create `src/services/schemas/performance.py` — `PerformanceReport`, `TickerSeries`
- Create `src/services/performance.py` — `get_performance(data_dir, portfolio=None, start=None)`
- Create `src/api/routers/performance.py` — thin `GET /performance`
- Modify `src/api/main.py` — import + `include_router`
- Modify `frontend/vite.config.ts` — add `/performance` to the proxy list
- Create `tests/services/test_performance.py`
- Create `tests/api/test_performance_route.py`

**Task 2 — Performance screen (frontend)**
- Create `frontend/src/components/LineChart.tsx` — multi-series SVG line chart with a hover readout
- Create `frontend/src/views/Performance.tsx`
- Modify `frontend/src/api.ts` — types + `fetchPerformance`
- Modify `frontend/src/App.tsx` — `'performance'` view, nav entry, title
- Modify `frontend/src/index.css` — chart legend / tooltip styles

**Task 3 — Attribution screen + the picker gate**
- Create `frontend/src/components/NeedsPortfolio.tsx` — the shared prompt
- Create `frontend/src/views/Attribution.tsx`
- Modify `frontend/src/api.ts`, `App.tsx`
- Create `tests/api/test_attribution_route.py`

**Task 4 — Stress Test screen**
- Create `frontend/src/views/Stress.tsx`
- Modify `frontend/src/api.ts`, `App.tsx`

**Task 5 — Correlation screen**
- Create `frontend/src/components/Heatmap.tsx`
- Create `frontend/src/views/Correlation.tsx`
- Modify `frontend/src/api.ts`, `App.tsx`

---

### Task 1: `/performance` aggregate endpoint

**Status: done — `e7ef9cf`.**

Mirrors the Streamlit **Price History** tab: normalised price series, cumulative returns, and trailing return stats — computed server-side so the SPA holds no analytics.

**Why a new endpoint rather than reusing `/prices/history`:** that endpoint takes a ticker list, so the screen would have to fetch `/dashboard` first to learn its tickers, then rebase and compute returns in TypeScript. Both the extra round trip and the client-side maths break the conventions in `src/services/CLAUDE.md`.

**Files:**
- Create: `src/services/schemas/performance.py`
- Create: `src/services/performance.py`
- Create: `src/api/routers/performance.py`
- Modify: `src/api/main.py`
- Modify: `frontend/vite.config.ts`
- Test: `tests/services/test_performance.py`, `tests/api/test_performance_route.py`

**Interfaces:**
- Consumes: `src.services.dashboard.get_snapshot(data_dir, start, portfolio)` → `DashboardSnapshot` with `.holdings: list[Holding]` (each has `.ticker`, `.market_value`, `.asset_type`); `src.services._db._get_db(data_dir)`.
- Produces: `get_performance(data_dir: str, portfolio: str | None = None, start: str | None = None) -> PerformanceReport`, served at `GET /performance?portfolio=&start=`.

- [ ] **Step 1: Write the schema**

Create `src/services/schemas/performance.py`:

```python
"""Schemas for the Performance screen."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TickerSeries(BaseModel):
    """One ticker's normalised history, aligned to the report's ``dates``."""

    ticker: str
    asset_type: str
    market_value: float
    # Index-for-index with PerformanceReport.dates. None where the ticker
    # has no sample on that date — the series starts later than the window.
    cumulative_return: list[float | None] = Field(
        ..., description="Decimal return since the ticker's first sample. 0.0 at its start."
    )
    total_return: float = Field(..., description="Decimal return over the whole window.")


class PerformanceReport(BaseModel):
    """Rebased price history for every priced holding in scope."""

    dates: list[str] = Field(..., description="Ascending ISO dates, shared x-axis.")
    series: list[TickerSeries] = Field(..., description="Sorted by market value, largest first.")
    portfolio_cumulative_return: list[float | None] = Field(
        ..., description="Value-weighted blend of the series, aligned to ``dates``."
    )
    portfolio_total_return: float
    excluded: list[str] = Field(
        ..., description="Tickers with no usable price history; absent from every series."
    )
```

- [ ] **Step 2: Write the failing service test**

Create `tests/services/test_performance.py`:

```python
"""Tests for the performance (rebased price history) service."""

import shutil

import pytest

from src.services import performance
from src.services._db import reset_db_cache


@pytest.fixture(autouse=True)
def _clean():
    reset_db_cache()
    yield
    reset_db_cache()


@pytest.fixture
def data_dir(tmp_path):
    dest = tmp_path / "data"
    shutil.copytree("data_demo", dest)
    return str(dest)


def test_series_are_aligned_to_the_shared_dates(data_dir):
    """A chart draws every series against one x-axis; ragged lengths corrupt it."""
    rep = performance.get_performance(data_dir)
    assert len(rep.dates) > 2
    for s in rep.series:
        assert len(s.cumulative_return) == len(rep.dates), f"{s.ticker} is not aligned"
    assert len(rep.portfolio_cumulative_return) == len(rep.dates)


def test_each_series_starts_at_zero(data_dir):
    """Rebasing means the first real sample is 0% by construction."""
    rep = performance.get_performance(data_dir)
    for s in rep.series:
        first = next((v for v in s.cumulative_return if v is not None), None)
        assert first == pytest.approx(0.0, abs=1e-9), f"{s.ticker} is not rebased"


def test_total_return_matches_the_last_point(data_dir):
    rep = performance.get_performance(data_dir)
    for s in rep.series:
        last = next((v for v in reversed(s.cumulative_return) if v is not None), None)
        assert s.total_return == pytest.approx(last, abs=1e-9)


def test_series_sorted_by_market_value(data_dir):
    rep = performance.get_performance(data_dir)
    values = [s.market_value for s in rep.series]
    assert values == sorted(values, reverse=True)


def test_scoping_narrows_the_series(data_dir):
    whole = performance.get_performance(data_dir)
    scoped = performance.get_performance(data_dir, portfolio="Demo Brokerage")
    assert len(scoped.series) < len(whole.series)


def test_unknown_portfolio_is_not_found(data_dir):
    with pytest.raises(ValueError, match="not found"):
        performance.get_performance(data_dir, portfolio="No Such Account")


def test_start_trims_the_window(data_dir):
    full = performance.get_performance(data_dir)
    trimmed = performance.get_performance(data_dir, start="2025-01-01")
    assert len(trimmed.dates) < len(full.dates)
    assert trimmed.dates[0] >= "2025-01-01"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/services/test_performance.py -q`
Expected: every test FAILS with `ModuleNotFoundError: No module named 'src.services.performance'`.

- [ ] **Step 4: Write the service**

Create `src/services/performance.py`:

```python
"""Rebased price history for the Performance screen.

Returns cumulative return rather than raw price so series of wildly
different unit prices are comparable on one axis — a $600 share and a $30
share are the same line shape when both start at 0.

Holdings are valued from the snapshot, so the portfolio blend is weighted
by what is actually held rather than equally per ticker.
"""

from __future__ import annotations

import os

import pandas as pd

from src.services.schemas.performance import PerformanceReport, TickerSeries

_PAR_TYPES = {"Cash", "CD"}


def _history(data_dir: str, ticker: str) -> pd.Series | None:
    path = os.path.join(data_dir, "prices", f"{ticker}.parquet")
    if not os.path.exists(path):
        return None
    try:
        s = pd.read_parquet(path)["price"].dropna()
    except (KeyError, OSError, ValueError):
        return None
    if s.empty:
        return None
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def get_performance(
    data_dir: str, portfolio: str | None = None, start: str | None = None
) -> PerformanceReport:
    """Cumulative return per holding, plus the value-weighted blend.

    ``portfolio`` scopes to one account; ``None`` spans every portfolio.
    ``start`` trims the window; ``None`` uses all available history.

    Raises:
        ValueError: unknown ``portfolio``, or no holding has price history.
    """
    from src.services.dashboard import get_snapshot

    snap = get_snapshot(data_dir, portfolio=portfolio)

    frames: dict[str, pd.Series] = {}
    excluded: list[str] = []
    weights: dict[str, float] = {}
    meta: dict[str, tuple[str, float]] = {}

    for h in snap.holdings:
        # Cash and CDs are held at par — a flat line at 0% is noise.
        if h.asset_type in _PAR_TYPES:
            excluded.append(h.ticker)
            continue
        s = _history(data_dir, h.ticker)
        if s is None or len(s) < 2:
            excluded.append(h.ticker)
            continue
        frames[h.ticker] = s
        weights[h.ticker] = weights.get(h.ticker, 0.0) + h.market_value
        meta[h.ticker] = (h.asset_type, weights[h.ticker])

    if not frames:
        raise ValueError("No holdings with usable price history — nothing to plot.")

    prices = pd.DataFrame(frames).sort_index()
    if start:
        prices = prices[prices.index >= pd.Timestamp(start)]
    if len(prices) < 2:
        raise ValueError(f"Start date {start!r} leaves too little history to plot.")

    # Rebase each column to its own first observation, not the window's first
    # row — a ticker that starts mid-window must still begin at 0%.
    first = prices.apply(lambda c: c.dropna().iloc[0] if not c.dropna().empty else pd.NA)
    rebased = prices.div(first) - 1.0

    total_weight = sum(weights.values()) or 1.0
    w = pd.Series({t: v / total_weight for t, v in weights.items()})
    # dropna(how="any") because a dot product propagates NaN: one missing
    # sample would blank the whole blended series for that date.
    aligned = rebased.dropna(how="any")
    blend = aligned.dot(w.reindex(aligned.columns).fillna(0.0)) if not aligned.empty else pd.Series(dtype=float)
    blend = blend.reindex(rebased.index)

    dates = [d.strftime("%Y-%m-%d") for d in rebased.index]

    def _col(name: str) -> list[float | None]:
        return [None if pd.isna(v) else round(float(v), 6) for v in rebased[name]]

    series = [
        TickerSeries(
            ticker=t,
            asset_type=meta[t][0],
            market_value=round(meta[t][1], 2),
            cumulative_return=_col(t),
            total_return=round(float(rebased[t].dropna().iloc[-1]), 6),
        )
        for t in rebased.columns
    ]
    series.sort(key=lambda s: s.market_value, reverse=True)

    blend_list = [None if pd.isna(v) else round(float(v), 6) for v in blend]
    last_blend = next((v for v in reversed(blend_list) if v is not None), 0.0)

    return PerformanceReport(
        dates=dates,
        series=series,
        portfolio_cumulative_return=blend_list,
        portfolio_total_return=round(float(last_blend), 6),
        excluded=sorted(set(excluded)),
    )


__all__ = ["get_performance"]
```

- [ ] **Step 5: Run the service tests to verify they pass**

Run: `uv run python -m pytest tests/services/test_performance.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 6: Write the failing route test**

Create `tests/api/test_performance_route.py`:

```python
"""Tests for GET /performance."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

DEMO_HEADERS = {"X-Data-Dir": "data_demo"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_performance_route_demo(client: TestClient) -> None:
    r = client.get("/performance", headers=DEMO_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["series"]
    assert len(body["portfolio_cumulative_return"]) == len(body["dates"])


def test_performance_scopes(client: TestClient) -> None:
    whole = client.get("/performance", headers=DEMO_HEADERS).json()
    scoped = client.get(
        "/performance", params={"portfolio": "Demo Brokerage"}, headers=DEMO_HEADERS
    )
    assert scoped.status_code == 200
    assert len(scoped.json()["series"]) < len(whole["series"])


def test_unknown_portfolio_is_404(client: TestClient) -> None:
    r = client.get(
        "/performance", params={"portfolio": "No Such Account"}, headers=DEMO_HEADERS
    )
    assert r.status_code == 404
```

- [ ] **Step 7: Run it to verify it fails**

Run: `uv run python -m pytest tests/api/test_performance_route.py -q`
Expected: FAIL with 404 on every test — the route does not exist yet.

- [ ] **Step 8: Write the router and mount it**

Create `src/api/routers/performance.py`:

```python
"""HTTP route for rebased price history."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.api.deps import data_dir_dep
from src.services import performance as performance_service
from src.services.schemas.performance import PerformanceReport

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("", response_model=PerformanceReport)
def get_performance(
    data_dir: Annotated[str, Depends(data_dir_dep)],
    portfolio: Annotated[
        str | None, Query(description="Scope to one portfolio; omit for all.")
    ] = None,
    start: Annotated[
        str | None, Query(description="ISO date; trims the window. Omit for all history.")
    ] = None,
) -> PerformanceReport:
    """Cumulative return per holding plus the value-weighted portfolio blend.

    Series are rebased to each ticker's own first sample, so a holding that
    starts mid-window still begins at 0% rather than jumping.
    """
    return performance_service.get_performance(data_dir, portfolio, start)
```

In `src/api/main.py`, add `performance` to the `from src.api.routers import (...)` block (alphabetical, after `income`) and add `app.include_router(performance.router)` after the `income` line.

- [ ] **Step 9: Add the proxy prefix**

In `frontend/vite.config.ts`, add `'/performance'` to the proxy array.

- [ ] **Step 10: Run the full suite**

Run: `uv run python -m pytest tests/ -q`
Expected: 3 failed (the known baseline), everything else passing — including `tests/test_frontend_proxy.py`, which fails if Step 9 was skipped.

- [ ] **Step 11: Commit**

```bash
git add src/services/performance.py src/services/schemas/performance.py \
        src/api/routers/performance.py src/api/main.py \
        frontend/vite.config.ts tests/services/test_performance.py \
        tests/api/test_performance_route.py
git commit -m "feat: /performance endpoint for rebased price history

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Performance screen

**Status: done — `beda4d4`.**

**Files:**
- Create: `frontend/src/components/LineChart.tsx`
- Create: `frontend/src/views/Performance.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: `GET /performance` → `PerformanceReport` (Task 1).
- Produces: `fetchPerformance(dataDir?: string, portfolio?: string | null, start?: string | null): Promise<PerformanceReport>`; `<Performance dataDir={string} portfolio={string | null} />`; `<LineChart series={LineSeries[]} dates={string[]} />` where `LineSeries = { label: string; values: (number | null)[]; color: string; width?: number }`.

- [ ] **Step 1: Add the client types and fetcher**

In `frontend/src/api.ts`, append:

```ts
export interface TickerSeries {
  ticker: string
  asset_type: string
  market_value: number
  /** Index-for-index with `dates`; null before the ticker's first sample. */
  cumulative_return: (number | null)[]
  total_return: number
}
export interface PerformanceReport {
  dates: string[]
  series: TickerSeries[]
  portfolio_cumulative_return: (number | null)[]
  portfolio_total_return: number
  excluded: string[]
}

export const fetchPerformance = (
  dataDir?: string, portfolio?: string | null, start?: string | null,
) => get<PerformanceReport>(`/performance${qs({ portfolio, start })}`, dataDir)
```

- [ ] **Step 2: Build the line chart**

Create `frontend/src/components/LineChart.tsx`. Hand-built SVG, matching the existing chart components:

```tsx
import { useState } from 'react'
import { cssVar, useThemeTick, useWidth } from '../lib'

export interface LineSeries {
  label: string
  values: (number | null)[]
  color: string
  /** Thicker stroke marks the portfolio blend against its constituents. */
  width?: number
}

const H = 300, PAD_L = 52, PAD_R = 12, PAD_T = 12, PAD_B = 26

export function LineChart({ series, dates }: { series: LineSeries[]; dates: string[] }) {
  useThemeTick()
  const [hover, setHover] = useState<number | null>(null)
  // useWidth wraps a ResizeObserver — the chart is hand-built SVG in a
  // viewBox, so it needs a real pixel width to lay out its x-axis.
  const [box, measured] = useWidth<HTMLDivElement>()
  const w = Math.max(measured || 760, 320)

  const flat = series.flatMap((s) => s.values).filter((v): v is number => v !== null)
  const lo = Math.min(0, ...flat), hi = Math.max(0, ...flat)
  const span = hi - lo || 1

  const x = (i: number) => PAD_L + (i / Math.max(dates.length - 1, 1)) * (w - PAD_L - PAD_R)
  const y = (v: number) => PAD_T + (1 - (v - lo) / span) * (H - PAD_T - PAD_B)

  const path = (values: (number | null)[]) => {
    let d = '', pen = false
    values.forEach((v, i) => {
      if (v === null) { pen = false; return }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`
      pen = true
    })
    return d
  }

  // Five gridlines is enough to read a percentage off without clutter.
  const ticks = Array.from({ length: 5 }, (_, i) => lo + (span * i) / 4)

  return (
    <div className="linechart" ref={box}>
      <svg viewBox={`0 0 ${w} ${H}`} width="100%" height={H} role="img"
           aria-label="Cumulative return over time"
           onMouseLeave={() => setHover(null)}
           onMouseMove={(e) => {
             const box = e.currentTarget.getBoundingClientRect()
             const px = ((e.clientX - box.left) / box.width) * w
             const i = Math.round(((px - PAD_L) / (w - PAD_L - PAD_R)) * (dates.length - 1))
             setHover(i >= 0 && i < dates.length ? i : null)
           }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={w - PAD_R} y1={y(t)} y2={y(t)} stroke={cssVar('--grid')} />
            <text x={PAD_L - 8} y={y(t) + 4} textAnchor="end" fontSize="10"
                  fill={cssVar('--ink-3')} style={{ fontVariantNumeric: 'tabular-nums' }}>
              {(t * 100).toFixed(0)}%
            </text>
          </g>
        ))}
        <line x1={PAD_L} x2={w - PAD_R} y1={y(0)} y2={y(0)} stroke={cssVar('--marker')} strokeWidth="1" />
        {series.map((s) => (
          <path key={s.label} d={path(s.values)} fill="none" stroke={s.color}
                strokeWidth={s.width ?? 1.5} strokeLinejoin="round" />
        ))}
        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={PAD_T} y2={H - PAD_B}
                stroke={cssVar('--marker')} strokeDasharray="3 3" />
        )}
      </svg>
      {hover !== null && (
        <div className="readout">
          <b>{dates[hover]}</b>
          {series.map((s) => {
            const v = s.values[hover]
            return v === null ? null : (
              <span key={s.label}>
                <i className="dot" style={{ background: s.color }} />
                {s.label} <b className="num">{(v * 100).toFixed(1)}%</b>
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Add the styles**

In `frontend/src/index.css`, append:

```css
.linechart { position: relative; }
.readout {
  display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: center;
  margin-top: 10px; font-size: 11.5px; color: var(--ink-2);
}
.readout span { display: inline-flex; align-items: center; gap: 6px; }
```

- [ ] **Step 4: Build the view**

Create `frontend/src/views/Performance.tsx`. It renders the blend plus the top 8 holdings by value — thirty-three overlapping lines is a hairball, and the rest stay reachable through the table:

```tsx
import { useEffect, useState } from 'react'
import { ApiError, fetchPerformance, type PerformanceReport } from '../api'
import { colorForType, cssVar, pct, usd } from '../lib'
import { LineChart, type LineSeries } from '../components/LineChart'

const WINDOWS: { label: string; months: number | null }[] = [
  { label: '1Y', months: 12 }, { label: '3Y', months: 36 },
  { label: '5Y', months: 60 }, { label: 'All', months: null },
]

const startFor = (months: number | null): string | null => {
  if (months === null) return null
  const d = new Date()
  d.setMonth(d.getMonth() - months)
  return d.toISOString().slice(0, 10)
}

export function Performance(
  { dataDir, portfolio }: { dataDir: string; portfolio: string | null },
) {
  const [rep, setRep] = useState<PerformanceReport | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [months, setMonths] = useState<number | null>(12)

  useEffect(() => {
    let live = true
    setRep(null); setError(null)
    fetchPerformance(dataDir, portfolio, startFor(months))
      .then((d) => live && setRep(d))
      .catch((e) => live && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => { live = false }
  }, [dataDir, portfolio, months])

  if (error) {
    return (
      <div className="card state">
        <h2>Can’t load performance</h2>
        <p>{error.status === 0 ? 'The API isn’t responding.' : error.message}</p>
        {error.status === 0 && (
          <p className="sub">Start it with <code>uv run invest-monitor serve</code>, then reload.</p>
        )}
      </div>
    )
  }

  if (!rep) {
    return (
      <div className="stack" aria-busy="true" aria-label="Loading performance">
        <div className="card skeleton" style={{ height: 420 }} />
      </div>
    )
  }

  const top = rep.series.slice(0, 8)
  const lines: LineSeries[] = [
    { label: 'Portfolio', values: rep.portfolio_cumulative_return, color: cssVar('--marker'), width: 2.5 },
    ...top.map((s) => ({
      label: s.ticker, values: s.cumulative_return, color: colorForType(s.asset_type),
    })),
  ]

  return (
    <div className="stack">
      <section className="card hero">
        <div className="statrow">
          <div className="stat">
            <div className="k">Total return</div>
            <div className={`v num ${rep.portfolio_total_return >= 0 ? 'up' : 'down'}`}>
              {pct(rep.portfolio_total_return * 100)}
            </div>
          </div>
        </div>
        <div className="toolbar">
          <div className="spacer" />
          <span className="sub">Window</span>
          {WINDOWS.map((wd) => (
            <button key={wd.label} className="seg" aria-pressed={months === wd.months}
                    onClick={() => setMonths(wd.months)}>{wd.label}</button>
          ))}
        </div>
        <div className="note">
          Each line is rebased to its own first sample in the window, so a holding
          bought later still starts at 0%. The portfolio line is value-weighted.
        </div>
        {rep.excluded.length > 0 && (
          <div className="note">No price history, excluded: {rep.excluded.join(', ')}.</div>
        )}
      </section>

      <section className="card pad">
        <h2 className="h2">Cumulative return{top.length < rep.series.length ? ` — top ${top.length} of ${rep.series.length}` : ''}</h2>
        <LineChart series={lines} dates={rep.dates} />
      </section>

      <section className="card pad">
        <h2 className="h2">Return by holding</h2>
        <div className="tablescroll">
          <table>
            <thead><tr><th>Ticker</th><th>Type</th><th className="r">Value</th><th className="r">Return</th></tr></thead>
            <tbody>
              {rep.series.map((s) => (
                <tr key={s.ticker}>
                  <td><b>{s.ticker}</b></td>
                  <td><span className="dot" style={{ background: colorForType(s.asset_type) }} /> {s.asset_type}</td>
                  <td className="r num">{usd(s.market_value)}</td>
                  <td className={`r num ${s.total_return >= 0 ? 'up' : 'down'}`}>{pct(s.total_return * 100)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
```

- [ ] **Step 5: Wire it into the shell**

In `frontend/src/App.tsx`: add `'performance'` to the `View` union and `VIEWS`; add a `NAV` entry after `holdings` with a line-chart icon; add `performance: 'Performance'` to `TITLES`; add the branch `route.view === 'performance' ? <Performance {...props} /> :`.

`.r`, `.tablescroll`, `.seg`, `.up`, `.down`, `.num` and `.sub` all already
exist in `index.css`. There is **no** `.tbl` class — tables are styled as bare
`<table>` inside a `.tablescroll` wrapper; see `components/HoldingsTable.tsx`
for the established markup. Don't invent a table class.

- [ ] **Step 6: Build, lint, and look at it**

```bash
cd frontend && npm run build && npm run lint
```
Expected: build succeeds, oxlint silent.

Then run it and confirm the chart draws, the window buttons refetch, and the scope selector changes the lines:
```bash
uv run invest-monitor serve          # terminal 1
cd frontend && npm run dev           # terminal 2 → http://localhost:5173/#performance
```
Check at ~400px wide that the table scrolls inside `.tablescroll` and the page body does not scroll sideways.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat: Performance screen with rebased return chart

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Attribution screen + the picker gate

**Status: done — `b237bac`.**

Implements the "needs a portfolio" rule for the first time. Tasks 4 and 5 reuse `NeedsPortfolio` verbatim.

**Files:**
- Create: `frontend/src/components/NeedsPortfolio.tsx`, `frontend/src/views/Attribution.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`
- Test: `tests/api/test_attribution_route.py`

**Interfaces:**
- Consumes: `GET /reports/attribution/{portfolio_name}?start=&end=&top_n=` → `AttributionReport`.
- Produces: `fetchAttribution(portfolio: string, dataDir?: string, topN?: number)`; `<NeedsPortfolio what={string} />`.

- [ ] **Step 1: Pin the endpoint's contract with a test**

The route already exists, so this test characterises what the screen depends on. Create `tests/api/test_attribution_route.py`:

```python
"""Contract tests for GET /reports/attribution/{portfolio}.

The Attribution screen reads these fields directly; a shape change here
breaks the view silently, so the shape is pinned.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

DEMO_HEADERS = {"X-Data-Dir": "data_demo"}
PORTFOLIO = "Demo Brokerage"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_attribution_shape(client: TestClient) -> None:
    r = client.get(f"/reports/attribution/{PORTFOLIO}", params={"top_n": 5},
                   headers=DEMO_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert len(body["daily_returns"]) == len(body["dates"])
    assert len(body["top_contributors"]) <= 5
    for row in body["top_contributors"]:
        assert {"ticker", "contribution_to_return"} <= row.keys()


def test_unknown_portfolio_is_404(client: TestClient) -> None:
    r = client.get("/reports/attribution/No Such Account", headers=DEMO_HEADERS)
    assert r.status_code == 404
```

- [ ] **Step 2: Run it**

Run: `uv run python -m pytest tests/api/test_attribution_route.py -q`
Expected: PASS. This test characterises existing behaviour — if it fails, the schema drifted and the view code below needs adjusting before you write it.

- [ ] **Step 3: Build the picker gate**

Create `frontend/src/components/NeedsPortfolio.tsx`:

```tsx
/** Shown when a per-portfolio screen is viewed under "All portfolios".
 *
 *  These screens are backed by endpoints that take a portfolio in the path
 *  and define no all-portfolios form. Aggregating client-side would mean
 *  inventing a number the backend never computed — attribution windows
 *  differ per portfolio, so summing them is arithmetic on incomparable
 *  ranges. Asking is honest; guessing is not.
 */
export function NeedsPortfolio({ what }: { what: string }) {
  return (
    <div className="card state">
      <h2>Pick a portfolio</h2>
      <p>{what} is calculated per portfolio, so there’s no all-accounts view.</p>
      <p className="sub">Choose one under <b>Scope</b> in the sidebar.</p>
    </div>
  )
}
```

- [ ] **Step 4: Add the client types and fetcher**

In `frontend/src/api.ts`, append:

```ts
export interface AttributionContributor {
  ticker: string
  /** Decimal, summed over the window. */
  contribution_to_return: number
}
export interface AttributionReport {
  portfolio_name: string
  start_date: string
  end_date: string
  cumulative_return: number
  max_drawdown: number
  dates: string[]
  daily_returns: (number | null)[]
  top_contributors: AttributionContributor[]
  top_detractors: AttributionContributor[]
}

export const fetchAttribution = (portfolio: string, dataDir?: string, topN = 5) =>
  get<AttributionReport>(
    `/reports/attribution/${encodeURIComponent(portfolio)}${qs({ top_n: topN })}`,
    dataDir,
  )
```

- [ ] **Step 5: Build the view**

Create `frontend/src/views/Attribution.tsx`. It returns `<NeedsPortfolio>` before any fetch when unscoped, cumulates `daily_returns` into a line, and renders contributor / detractor tables.

Two caveats the view must state, both measured on live data: the window is whatever `daily_attribution.parquet` covers for that portfolio (SCHAB starts 2026-04-14, PRU401K 2021-05-10), and an all-cash portfolio returns zero contributors. Render `start_date → end_date` prominently and show an explicit empty state when `top_contributors` is empty rather than an empty table.

```tsx
import { useEffect, useState } from 'react'
import { ApiError, fetchAttribution, type AttributionReport } from '../api'
import { cssVar, longDate, pct } from '../lib'
import { LineChart, type LineSeries } from '../components/LineChart'
import { NeedsPortfolio } from '../components/NeedsPortfolio'

/** Daily returns compound into the cumulative line the screen actually shows. */
function cumulate(daily: (number | null)[]): (number | null)[] {
  let acc = 1
  return daily.map((r) => { acc *= 1 + (r ?? 0); return acc - 1 })
}

export function Attribution(
  { dataDir, portfolio }: { dataDir: string; portfolio: string | null },
) {
  const [rep, setRep] = useState<AttributionReport | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  useEffect(() => {
    if (!portfolio) return
    let live = true
    setRep(null); setError(null)
    fetchAttribution(portfolio, dataDir, 10)
      .then((d) => live && setRep(d))
      .catch((e) => live && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => { live = false }
  }, [dataDir, portfolio])

  if (!portfolio) return <NeedsPortfolio what="Performance attribution" />

  if (error) {
    return (
      <div className="card state">
        <h2>Can’t load attribution</h2>
        <p>{error.status === 0 ? 'The API isn’t responding.' : error.message}</p>
        {error.status === 0 && (
          <p className="sub">Start it with <code>uv run invest-monitor serve</code>, then reload.</p>
        )}
        <p className="sub">
          Attribution reads pre-computed metrics. If this portfolio has never been
          refreshed, run <code>uv run invest-monitor metrics refresh</code>.
        </p>
      </div>
    )
  }

  if (!rep) {
    return <div className="card skeleton" style={{ height: 420 }}
                aria-busy="true" aria-label="Loading attribution" />
  }

  const lines: LineSeries[] = [{
    label: rep.portfolio_name, values: cumulate(rep.daily_returns),
    color: cssVar('--marker'), width: 2.5,
  }]

  return (
    <div className="stack">
      <section className="card hero">
        <div className="statrow">
          <div className="stat">
            <div className="k">Cumulative return</div>
            <div className={`v num ${rep.cumulative_return >= 0 ? 'up' : 'down'}`}>
              {pct(rep.cumulative_return * 100)}
            </div>
          </div>
          <div className="stat sm">
            <div className="k">Max drawdown</div>
            <div className="v num down">{pct(rep.max_drawdown * 100)}</div>
          </div>
        </div>
        {/* The window is whatever the metrics job has recorded for this
            portfolio, and it differs a lot between them. Saying so stops
            the number being read as "since inception". */}
        <div className="note">
          {longDate(rep.start_date)} → {longDate(rep.end_date)} · {rep.dates.length} trading days
          recorded for {rep.portfolio_name}. Other portfolios cover different windows,
          so these returns are not comparable across accounts.
        </div>
      </section>

      <section className="card pad">
        <h2 className="h2">Cumulative return</h2>
        <LineChart series={lines} dates={rep.dates} />
      </section>

      <div className="cols">
        <section className="card pad">
          <h2 className="h2">Top contributors</h2>
          {rep.top_contributors.length === 0 ? (
            <p className="sub">
              Nothing contributed — this portfolio holds only cash or par instruments
              over the window.
            </p>
          ) : (
            <table>
              <tbody>
                {rep.top_contributors.map((c) => (
                  <tr key={c.ticker}>
                    <td><b>{c.ticker}</b></td>
                    <td className="r num up">{pct(c.contribution_to_return * 100)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <section className="card pad">
          <h2 className="h2">Top detractors</h2>
          {rep.top_detractors.length === 0 ? (
            <p className="sub">Nothing detracted over this window.</p>
          ) : (
            <table>
              <tbody>
                {rep.top_detractors.map((c) => (
                  <tr key={c.ticker}>
                    <td><b>{c.ticker}</b></td>
                    <td className="r num down">{pct(c.contribution_to_return * 100)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  )
}
```

Confirm `longDate` is exported from `lib.ts` (it is used by `Exposure.tsx`). If it takes a `Date` rather than a string, wrap accordingly.

- [ ] **Step 6: Wire it in**

In `App.tsx`: add `'attribution'` to `View`/`VIEWS`/`TITLES` (`attribution: 'Attribution'`), a `NAV` entry, and the render branch.

- [ ] **Step 7: Build, lint, verify both states**

```bash
cd frontend && npm run build && npm run lint
uv run python -m pytest tests/ -q
```
Then in the browser check **both** paths: under **All portfolios** the picker prompt shows and no request is made (Network tab empty); scoped to one, the chart and tables render.

- [ ] **Step 8: Commit**

```bash
git add frontend/src tests/api/test_attribution_route.py
git commit -m "feat: Attribution screen and the needs-a-portfolio gate

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Stress Test screen

**Status: done.**

**Files:**
- Create: `frontend/src/views/Stress.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `GET /scenarios/stress` → `StressScenarioInfo[]`; `POST /scenarios/stress/{portfolio_name}` with `{scenario_id}` → `StressTestResult`; `NeedsPortfolio` from Task 3.
- Produces: `fetchStressScenarios(dataDir?)`, `runStress(portfolio, scenarioId, dataDir?)`.

- [ ] **Step 1: Add a POST helper to the client**

`api.ts` currently only has `get<T>`. Add alongside it:

```ts
async function post<T>(path: string, body: unknown, dataDir?: string): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(dataDir ? { 'X-Data-Dir': dataDir } : {}),
      },
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'Could not reach the API.')
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const b = await res.json()
      if (b?.detail) detail = String(b.detail)
    } catch { /* non-JSON error body — keep the status line */ }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}
```

- [ ] **Step 2: Add the types and fetchers**

```ts
export interface StressScenarioInfo {
  scenario_id: string
  /** sector key → shock as a fraction (-0.30 = -30%). */
  sector_shocks: Record<string, number>
  non_equity_shocks: Record<string, number>
}
export interface StressShockRow {
  ticker: string; asset_type: string; base_value: number
  /** Percent, not a fraction — the API sends 30 for +30%. */
  shock_pct: number
  new_value: number; change_usd: number; source: string
}
export interface StressTestResult {
  portfolio_name: string
  scenario_id: string | null
  base_value: number; new_value: number
  total_change_usd: number; total_change_pct: number
  rows: StressShockRow[]
}

export const fetchStressScenarios = (dataDir?: string) =>
  get<StressScenarioInfo[]>('/scenarios/stress', dataDir)

export const runStress = (portfolio: string, scenarioId: string, dataDir?: string) =>
  post<StressTestResult>(
    `/scenarios/stress/${encodeURIComponent(portfolio)}`,
    { scenario_id: scenarioId },
    dataDir,
  )
```

**Note the units** (verified against a live response — an earlier draft of this plan had this backwards): `StressShockRow.shock_pct` **and** `StressTestResult.total_change_pct` are *percents* (`-10.0`, `-6.083`), while the scenario `sector_shocks` / `non_equity_shocks` are *fractions* (`-0.55`). `pct()` in `lib.ts` takes a percent, so the first two pass straight through and only the shock catalogue needs `× 100`. Re-verify before rendering — `curl -s -XPOST localhost:8000/scenarios/stress/SCHAB -H 'Content-Type: application/json' -d '{"scenario_id":"Mild Correction (-10%)"}' | head -c 400`.

- [ ] **Step 3: Build the view**

Create `frontend/src/views/Stress.tsx`:
- Return `<NeedsPortfolio what="Stress testing" />` when `portfolio` is null.
- Fetch the catalogue on mount; render the seven scenarios as `.seg` buttons (live ids: `2008 Financial Crisis`, `Dot-Com Crash (Tech)`, `Rate Hike (2022-style)`, `Energy Shock (Oil +50%)`, `Mild Correction (-10%)`, `Severe Drawdown (-30%)`, `Bull Run (+15%)`).
- On click, POST and render: base → new value, total change in dollars and percent, and a per-position table sorted by `change_usd` ascending (worst first), with the `source` column shown so a fallback-derived shock is never mistaken for a real sector hit.
- Before any scenario is chosen, show a one-line prompt, not a spinner.
- Follow the three-state error/loading/loaded structure and the `status === 0` hint guard exactly as in Task 2 Step 4.

- [ ] **Step 4: Wire it in, build, verify**

`App.tsx` gets `'stress'` in `View`/`VIEWS`/`TITLES`/`NAV` plus the branch.

```bash
cd frontend && npm run build && npm run lint
```
In the browser, run at least two scenarios against a real portfolio and confirm the dollar totals reconcile: `rows.reduce((s, r) => s + r.change_usd, 0)` should equal `total_change_usd` within a cent.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: Stress Test screen

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Correlation screen

**Files:**
- Create: `frontend/src/components/Heatmap.tsx`, `frontend/src/views/Correlation.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `GET /reports/correlation/{portfolio_name}` → `{portfolio_name, tickers: string[], matrix: Record<string, Record<string, number>>}`; `NeedsPortfolio` from Task 3.
- Produces: `fetchCorrelation(portfolio, dataDir?)`; `<Heatmap tickers={string[]} matrix={...} />`.

- [ ] **Step 1: Add the type and fetcher**

```ts
export interface CorrelationReport {
  portfolio_name: string
  tickers: string[]
  matrix: Record<string, Record<string, number>>
}

export const fetchCorrelation = (portfolio: string, dataDir?: string) =>
  get<CorrelationReport>(`/reports/correlation/${encodeURIComponent(portfolio)}`, dataDir)
```

- [ ] **Step 2: Build the heatmap**

Create `frontend/src/components/Heatmap.tsx`. **Size is the real constraint here** — SCHAB's live matrix is 33×33, which is 1,089 cells. Requirements:

- Render as a CSS grid of `<div>`s, not 1,089 SVG `<rect>`s with individual listeners.
- Fixed cell size (~22px) inside a `.tablescroll`; the matrix scrolls, the page does not.
- Diverging scale, since correlation is signed and zero is meaningful: `--neg` at −1, the card background at 0, `--c2` at +1. Interpolate in `oklch()` so the midpoint doesn't go muddy. **This is a diverging palette — load the `dataviz` skill before choosing the endpoints and validate the result.**
- Row and column labels are tickers; at 33 columns they must rotate or truncate. Truncate to 4 characters with a `title` attribute carrying the full ticker.
- Each cell gets `title="AAPL / MSFT: 0.62"` so the value is reachable without a tooltip component.
- Below 600px the grid is unreadable regardless. Render a ranked list instead — the 15 most-correlated pairs — and say why.

- [ ] **Step 3: Build the view**

Create `frontend/src/views/Correlation.tsx`: `<NeedsPortfolio what="Correlation" />` when unscoped; otherwise the heatmap plus a "most correlated pairs" table (upper triangle only, sorted by absolute value, top 15). State inline that correlation is computed over whatever price history both tickers share.

- [ ] **Step 4: Wire it in, build, verify**

```bash
cd frontend && npm run build && npm run lint
```
Check SCHAB (33 tickers) specifically for horizontal overflow at 400px, and confirm the diagonal reads 1.00 throughout — a diagonal that isn't 1.0 means the matrix is being indexed transposed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: Correlation heatmap screen

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## RESOLVED: `daily_portfolio_metrics.parquet` was incoherent

**Fixed in `3c57874`; both datasets repaired; Task 3 shipped on the
corrected data.** Kept here because the invariant is easy to break again
and the failure is silent. The durable version lives in
`src/database/CLAUDE.md` § Invariants, and
`tests/test_attribution_coherence.py` fails if it regresses.

This was a backend data bug, not a frontend one, and it predated this plan.

`Database.save_daily_portfolio_metrics` (`src/database/database.py:605`)
**upserts keyed on `(date, portfolio_name)`**. But `cum_return`,
`drawdown` and `max_drawdown` are *path-dependent* — each is a running
figure compounded from the start of the window it was computed over. A
refresh that covers a different window, or runs against a different
position set (v1 static-current vs v2 trade-replay), overwrites only the
dates it touched. The stored series then mixes values compounded from
several different baselines, and is not a coherent series at all.

`daily_return` is path-independent per row, so it survives the merge — but
the *set of rows* does not, because different runs cover different date
ranges and position sets.

Evidence, live dataset:

| Portfolio | stored rows | fresh rows | compounded from stored | fresh compute |
|---|---|---|---|---|
| SCHAB | 111 | 1399 | +2.10% | **+46.77%** |
| PRU401K | 1346 | 1347 | +146.14% | **+60.93%** |
| ESPP | 893 | 1347 | −10.04% | **+36.77%** |

A freshly computed frame is internally consistent — compounding its
`daily_return` equals its own `cum_return` to 1e-6 — which localises the
fault to the stored file and its write path, not to
`AttributionEngine.compute_portfolio_history`, whose formula
(`cumulative = (1 + port_return).cumprod()`) is correct by construction.

**Blast radius — everything reading this file is affected:**
- `src/services/reports.py:272` — `attribution()`, the Attribution screen
- `src/services/benchmarks.py:131,167` — portfolio side of every comparison
- `src/app.py:1163` — the Streamlit Performance Attribution tab
- `src/services/dashboard.py` already refuses to use it for a net-worth
  series, for a related reason documented there

**The fix, at root:** a per-portfolio series is only coherent as a whole,
so the write path must replace a portfolio's whole series rather than
upsert per date. That means a `replace_daily_portfolio_metrics` (delete
rows for the portfolio, then insert) and a refresh that always recomputes
the full window. Worth checking whether `save_daily_attribution` has the
same problem — it upserts on `(date, portfolio_name, ticker)`, and
`contribution_to_return` is summed over the window by the reader, so a
mixture of runs corrupts it the same way.

**What was done.** Writers now use `_replace_parquet`, scoped by
`portfolio_name` / `ticker`, so a series is only ever stored whole;
`refresh_all` always recomputes from inception, and its `start_date` /
`full` arguments no longer truncate the window. `daily_security_metrics`
had the identical defect through its own per-ticker `cum_return` and was
fixed the same way. Corrected live figures: SCHAB +31.65%, PRU401K
+60.93%, ESPP +41.27% — all coherent to 0.00e+00 drift.

## Screen inventory changed: Risk split from Projection

Not in the original plan. The Risk screen had become a wealth-projection
screen — success ring, goal inputs and fan chart up top, four trailing
metrics in a card near the bottom — while the Streamlit Risk tab kept
measurement and projection apart.

`views/Risk.tsx` now leads with measured tail risk and `views/Projection.tsx`
owns the simulation. Both call `GET /risk`; Risk passes the endpoint's
minimum `num_simulations` since it draws no paths.

`expected_shortfall_95` / `_99`, `historical_var_99` and `current_drawdown`
were added to `RiskMetrics` for it — expected shortfall was not computed
anywhere before. Anything else consuming `RiskMetrics` gets them for free.

## Follow-ups on shipped screens

Small enhancements to screens that are already merged. Each is
self-contained; pick one up between tasks.

### Performance — top/bottom X in "Return by holding"

**Status:** open. **File:** `frontend/src/views/Performance.tsx`.

The table currently renders `rep.series` in full — 36 rows unscoped, 32 for
SCHAB. The series arrive sorted by market value, so the best and worst
performers are scattered through it and the question "what actually won and
lost?" needs a manual scan.

Add a selector above the table offering **Top 10 / Bottom 10 / All**, sorted
by `total_return` rather than by value. Follow the existing segmented-control
pattern — `<button className="seg" aria-pressed={...}>` — as used by
`components/HoldingsTable.tsx` (Top 12 / All) and `views/Income.tsx`
(Top 10 / All), so it reads as the same control.

Two things to get right:

- **Sort by return, not value, when the mode is Top/Bottom.** Under All,
  keep the existing value order — re-sorting the default view would change
  what the screen has always shown.
- **Say which order is active.** A table headed "Return by holding" showing
  10 of 36 rows is ambiguous about *which* 10. Put the count and the basis
  in the heading, the way the chart already does
  (`Cumulative return — largest 8 of 32`).

Worth doing at the same time: the chart charts the largest 8 *by value*. If
the table gains a by-return view, consider whether the chart should offer
the same, since "my biggest holdings" and "my best holdings" are different
questions and the screen currently only answers the first.

## Beyond this plan

Not scoped here; each needs its own brainstorm before planning.

**Read-only, backend already exists:**
- **Trades** (`GET /trades?portfolio_name=`) — history table. Recording a trade is a write; see below.
- **Benchmarks** (`/benchmarks`, `/benchmarks/compare/{portfolio}`) — portfolio vs index. Note the `{name:path}` converter: benchmark names contain slashes (`60/40 Classic`).
- **Groups** (`/groups`) — would extend the rail's Scope group to offer groups as a third kind of scope, which is a change to the scoping model, not just a new screen.
- **Production jobs** (`/production`) — job status, run buttons. The run endpoints are long-running and synchronous; the UI needs real timeout handling, not a spinner that lies.
- **Agent chat** (`/agents/sessions/*`) — sessions live in process-local dicts and do not survive a uvicorn restart. The UI must handle a session id going stale.

**Needs backend work first:**
- Position editing and the security master — `PUT /portfolios/{name}/positions` exists, but there is no per-asset metadata write endpoint.
- Look-through CSV upload — parsing lives in `src/data/ingestion.py` and is currently reachable only from Streamlit.

**Cross-cutting, worth doing before the SPA is the primary interface:**
- **Serve the built SPA from FastAPI.** `frontend/dist` is built but nothing mounts it — the SPA only runs under the Vite dev server. A `StaticFiles` mount in `src/api/main.py` with an SPA fallback would make `invest-monitor serve` sufficient on its own.
- **Frontend tests.** There is no test runner in `frontend/`. The pure logic worth covering is small and real: `routeFromHash`/`hashFor` round-tripping, the `qs()` builder, and `cumulate()` from Task 3. Adding vitest is a dependency decision, not a detail.
