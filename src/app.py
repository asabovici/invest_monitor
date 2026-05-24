import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import env as _env  # noqa: F401  — loads .env into os.environ
from src.collector import Collector
from src.data.ingestion import Ingester
from src.database.database import Database
from src.models import Asset, AssetType, Portfolio, Position
from src.reporting import ReportingEngine
from src.agent import (
    CIOAgent,
    PortfolioManagerAgent,
    ResearchAgent,
    RiskAgent,
    WealthAgent,
)
from src import demo as demo_data

st.set_page_config(
    page_title="Invest Monitor",
    page_icon="📈",
    layout="wide",
)

# ── Helpers ──────────────────────────────────────────────────────────────────

LIVE_DATA_DIR = "data"


def _active_data_dir() -> str:
    return demo_data.DEMO_DATA_DIR if st.session_state.get("demo_mode") else LIVE_DATA_DIR


@st.cache_resource
def _make_db(data_dir: str) -> Database:
    return Database(data_dir)


@st.cache_resource
def _make_reporting(data_dir: str) -> ReportingEngine:
    return ReportingEngine(_make_db(data_dir))


def get_db() -> Database:
    return _make_db(_active_data_dir())


def get_reporting() -> ReportingEngine:
    return _make_reporting(_active_data_dir())


def load_portfolio_from_upload(uploaded_file, portfolio_name: str) -> Portfolio:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name
    try:
        portfolio = Ingester(get_db()).load_portfolio_from_csv(tmp_path, portfolio_name)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return portfolio


@st.cache_data(ttl=300)
def _fetch_prices_cached(data_dir: str, tickers: tuple[str, ...]) -> pd.DataFrame:
    return _make_db(data_dir).get_historical_prices(list(tickers))


def fetch_prices(tickers: tuple[str, ...]) -> pd.DataFrame:
    return _fetch_prices_cached(_active_data_dir(), tickers)


def latest_prices(tickers: list[str]) -> dict[str, float]:
    df = fetch_prices(tuple(tickers))
    if df.empty:
        return {}
    return df.iloc[-1].to_dict()


def fmt_usd(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"${v:,.2f}"


def fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.2f}%"


def expand_lookthrough_rows(
    portfolio: "Portfolio",
    db: "Database",
    latest_prices_map: dict[str, float],
    enabled: bool = True,
    yfinance_fallback: bool = True,
) -> list[dict]:
    """Expand a portfolio's positions into display rows, optionally replacing
    ETF/Fund positions with their constituents.

    Resolution order per fund (highest fidelity first):
      1. `fund_holdings.parquet` — vendor-uploaded ticker-level rows.
      2. `fund_profiles.parquet` — yfinance asset_classes + sector_weightings
         (no constituent tickers, only sector and asset-class aggregates).
      3. Keep the fund as a single native row.

    Dollar totals (Current Value / Total Cost / P&L) are invariant under
    lookthrough — they're redistributed across constituent rows. Share-level
    fields (Quantity, Cost Basis, Current Price) are None for synthetic rows.
    """
    from src.scenarios import SECTOR_DISPLAY  # local import to avoid circulars

    rows: list[dict] = []
    for pos in portfolio.positions:
        ticker = pos.asset.ticker
        cp = latest_prices_map.get(ticker)
        if cp is None or (isinstance(cp, float) and np.isnan(cp)):
            cur_val = pos.quantity * pos.cost_basis
            cp_for_display = None
        else:
            cur_val = pos.quantity * float(cp)
            cp_for_display = float(cp)
        total_cost = pos.quantity * pos.cost_basis
        pnl = cur_val - total_cost

        is_fund = pos.asset.asset_type.value in ("ETF", "Fund")
        holdings = db.get_fund_holdings(ticker) if (enabled and is_fund) else pd.DataFrame()

        # ── 1) Vendor holdings (highest fidelity) ─────────────────────────────
        if not holdings.empty:
            for _, h in holdings.iterrows():
                w = float(h["weight"]) if pd.notna(h.get("weight")) else 0.0
                holding_ticker = str(h.get("holding_ticker") or "").strip() or "—"
                rows.append({
                    "Ticker":        holding_ticker,
                    "Name":          (str(h.get("holding_name") or "").strip()) or holding_ticker,
                    "Type":          (str(h.get("asset_type") or "").strip()) or "Stock",
                    "Sector":        (str(h.get("sector")     or "").strip()) or "Unknown",
                    "Quantity":      None,
                    "Cost Basis":    None,
                    "Current Price": None,
                    "Total Cost":    total_cost * w,
                    "Current Value": cur_val   * w,
                    "P&L":           pnl       * w,
                    "P&L %":         (pnl / total_cost * 100) if total_cost else None,
                    "Via":           ticker,
                    "Source":        "vendor",
                    "_synthetic":    True,
                })
            continue

        # ── 2) yfinance fund_profile (sector-level fallback) ──────────────────
        if enabled and is_fund and yfinance_fallback:
            profile = db.get_fund_profile(ticker)
            asset_classes = profile.get("asset_classes") or {}
            sector_weights = profile.get("sector_weightings") or {}
            if asset_classes or sector_weights:
                # Raw asset-class weights as reported by yfinance.
                raw_stock = float(asset_classes.get("stockPosition", 0.0) or 0.0)
                raw_bond  = float(asset_classes.get("bondPosition",  0.0) or 0.0)
                raw_cash  = float(asset_classes.get("cashPosition",  0.0) or 0.0)
                raw_pref  = float(asset_classes.get("preferredPosition",   0.0) or 0.0)
                raw_conv  = float(asset_classes.get("convertiblePosition", 0.0) or 0.0)
                raw_other = float(asset_classes.get("otherPosition",       0.0) or 0.0)
                # Inverse / leveraged funds report negative positions (e.g. SH
                # has stockPosition=-1.0, cashPosition=1.82). Clip negatives to
                # 0 and renormalise so the components sum to 1.0 — this loses
                # the "short equity" signal but keeps the total dollar value
                # invariant under lookthrough.
                clipped = {
                    "stock":  max(0.0, raw_stock),
                    "bond":   max(0.0, raw_bond),
                    "cash":   max(0.0, raw_cash),
                    "pref":   max(0.0, raw_pref),
                    "conv":   max(0.0, raw_conv),
                    "other":  max(0.0, raw_other),
                }
                total = sum(clipped.values())
                if total > 0:
                    stock_w = clipped["stock"] / total
                    bond_w  = clipped["bond"]  / total
                    cash_w  = clipped["cash"]  / total
                    pref_w  = clipped["pref"]  / total
                    conv_w  = clipped["conv"]  / total
                    other_w = clipped["other"] / total

                    def _emit(weight: float, name: str, atype: str, sector: str,
                              via_label: str | None = None):
                        if weight <= 0:
                            return
                        rows.append({
                            "Ticker":        f"{ticker} → {via_label or sector}",
                            "Name":          name,
                            "Type":          atype,
                            "Sector":        sector,
                            "Quantity":      None,
                            "Cost Basis":    None,
                            "Current Price": None,
                            "Total Cost":    total_cost * weight,
                            "Current Value": cur_val   * weight,
                            "P&L":           pnl       * weight,
                            "P&L %":         (pnl / total_cost * 100) if total_cost else None,
                            "Via":           ticker,
                            "Source":        "yfinance",
                            "_synthetic":    True,
                        })

                    # Equity portion → spread across sector_weightings if present.
                    equity_w = stock_w + pref_w + conv_w + other_w
                    if equity_w > 0:
                        if sector_weights:
                            sw_total = sum(sector_weights.values()) or 1.0
                            for sec_key, sw in sector_weights.items():
                                if sw <= 0:
                                    continue
                                sec_label = SECTOR_DISPLAY.get(sec_key, sec_key.replace("_", " ").title())
                                _emit(
                                    equity_w * (sw / sw_total),
                                    name=f"{sec_label} (via {ticker})",
                                    atype="Stock",
                                    sector=sec_label,
                                )
                        else:
                            _emit(equity_w, name=f"Equity (via {ticker})",
                                  atype="Stock", sector="Unknown", via_label="Equity")
                    if bond_w > 0:
                        _emit(bond_w, name=f"Bond portion (via {ticker})",
                              atype="Bond", sector="Fixed Income", via_label="Bond")
                    if cash_w > 0:
                        _emit(cash_w, name=f"Cash portion (via {ticker})",
                              atype="Cash", sector="Cash", via_label="Cash")
                    continue  # done with this position via yfinance fallback

        # ── 3) Native row (no lookthrough or no data) ─────────────────────────
        rows.append({
            "Ticker":        ticker,
            "Name":          pos.asset.name or "",
            "Type":          pos.asset.asset_type.value,
            "Sector":        pos.asset.sector or "—",
            "Quantity":      pos.quantity,
            "Cost Basis":    pos.cost_basis,
            "Current Price": cp_for_display,
            "Total Cost":    total_cost,
            "Current Value": cur_val,
            "P&L":           pnl,
            "P&L %":         (pnl / total_cost * 100) if total_cost else None,
            "Via":           "",
            "Source":        "native",
            "_synthetic":    False,
        })
    return rows


def _fmt_income_rate(row) -> str:
    """Format an income-rate row with the unit suffix from its 'Income Rate Unit'.
    Stock/ETF/Fund → "$X.XXXX/share"; Bond/CD/Cash → "X.XX%".
    Tolerates older DataFrames that lacked 'Income Rate Unit' / 'Income Rate'."""
    unit = row.get("Income Rate Unit")
    raw = row.get("Income Rate")
    if raw is None:
        raw = row.get("Income Rate (%)", 0)  # legacy column name
    val = float(raw or 0)
    if unit is None:
        unit = "$/share/payment" if row.get("Type") in ("Stock", "ETF", "Fund") else "%"
    if unit in ("$/share/payment", "$/share"):
        return f"${val:,.4f}/share/pmt"
    return f"{val:.2f}%"


def compute_portfolio_metrics(portfolio: Portfolio) -> dict | None:
    """Compute cross-portfolio comparable metrics. Returns None if no price data.

    Each ticker contributes only on dates where it has a valid daily return; on
    those dates, weights are renormalized across the available tickers. This
    keeps the 1Y / 6M return computable even when some positions have a shorter
    price history than others — the older positions' returns drive earlier dates
    at their relative weights, and the newer positions blend in once their data
    starts.
    """
    tickers = [pos.asset.ticker for pos in portfolio.positions]
    prices = get_db().get_historical_prices(tickers)
    if prices.empty:
        return None

    weights_map = {pos.asset.ticker: pos.quantity * pos.cost_basis for pos in portfolio.positions}
    total_cost = sum(weights_map.values())

    available = [t for t in tickers if t in prices.columns]
    if not available:
        return None

    w_arr = np.array([weights_map.get(t, 0.0) for t in available], dtype=float)
    if w_arr.sum() <= 0:
        return None

    # Per-ticker daily returns (NaN on first date and where prices are missing).
    rets_per_ticker = prices[available].sort_index().pct_change()

    # Add the income-rate contribution as a daily-accrual return. Units of
    # income_rate depend on asset_type:
    #   Stock/ETF/Fund : $/share/payment → annual yield = (rate × freq) / latest_price
    #   Bond/CD/Cash   : annual %        → annual yield = rate / 100
    # Daily contribution = annual_yield / 252. NaN + x = NaN so the validity
    # mask below is unaffected.
    # Compare by .value to be robust against Streamlit hot-reload re-importing
    # AssetType under a different class identity.
    rate_in_dollars_vals = {"Stock", "ETF", "Fund"}
    pos_by_ticker = {pos.asset.ticker: pos for pos in portfolio.positions}
    annual_yield = {}
    for t in available:
        pos = pos_by_ticker.get(t)
        if pos is None:
            annual_yield[t] = 0.0
            continue
        rate = float(getattr(pos.asset, "income_rate", 0.0) or 0.0)
        if pos.asset.asset_type.value in rate_in_dollars_vals:
            freq = int(getattr(pos.asset, "payment_frequency", 1) or 1)
            last_px = prices[t].dropna()
            last_px = float(last_px.iloc[-1]) if not last_px.empty else 0.0
            annual_yield[t] = ((rate * freq) / last_px) if last_px else 0.0
        else:
            annual_yield[t] = rate / 100.0
    income_per_day = np.array([annual_yield.get(t, 0.0) / 252.0 for t in available])
    if (income_per_day != 0).any():
        rets_per_ticker = rets_per_ticker.add(income_per_day, axis=1)

    # On each date: weighted sum of available tickers' returns, divided by the
    # sum of their weights → renormalized portfolio daily return.
    valid = rets_per_ticker.notna()
    row_weight_sum = valid.astype(float).mul(w_arr, axis=1).sum(axis=1)
    contrib = rets_per_ticker.fillna(0.0).mul(w_arr, axis=1).sum(axis=1)
    daily_ret = (contrib / row_weight_sum).where(row_weight_sum > 0).dropna()

    if daily_ret.empty or len(daily_ret) < 2:
        return None

    # Relative-value level series ($1 anchored at the first valid return date).
    port_series = (1.0 + daily_ret).cumprod()

    latest = port_series.index.max()
    horizons = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365}
    cum_returns = {}
    for label, days in horizons.items():
        cutoff = latest - pd.Timedelta(days=days)
        past = port_series[port_series.index <= cutoff]
        if not past.empty:
            cum_returns[label] = (float(port_series.iloc[-1]) - float(past.iloc[-1])) / float(past.iloc[-1])
        else:
            cum_returns[label] = None

    vol = float(daily_ret.std() * np.sqrt(252))
    var_95 = float(np.percentile(daily_ret, 5))
    var_99 = float(np.percentile(daily_ret, 1))

    cummax = port_series.cummax()
    dd = (port_series - cummax) / cummax
    max_dd = float(dd.min())
    current_dd = float(dd.iloc[-1])

    return {
        "total_cost": total_cost,
        "cum_returns": cum_returns,
        "volatility": vol,
        "var_95": var_95,
        "var_99": var_99,
        "max_drawdown": max_dd,
        "current_drawdown": current_dd,
    }


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    is_demo = bool(st.session_state.get("demo_mode"))
    st.title("Invest Monitor" + (" 🎭" if is_demo else ""))

    # Live / Demo toggle. Switching clears the active portfolio + cached
    # prices so nothing leaks across modes.
    new_mode = st.toggle(
        "🎭 Demo mode (hides live accounts)",
        value=is_demo,
        key="demo_mode_toggle",
        help=(
            "Switches to a separate `data_demo/` directory with sample portfolios. "
            "Your live data in `data/` is untouched."
        ),
    )
    if new_mode != is_demo:
        st.session_state["demo_mode"] = new_mode
        st.session_state.pop("portfolio", None)
        _fetch_prices_cached.clear()
        if new_mode:
            with st.spinner("Seeding demo data…"):
                demo_data.seed()
        st.rerun()

    if is_demo:
        st.info("**Demo mode** — viewing `data_demo/`. Your live accounts are hidden.", icon="🎭")
        if st.button("Reset demo data", key="reset_demo_btn"):
            demo_data.reset()
            st.session_state.pop("portfolio", None)
            _make_db.clear()
            _make_reporting.clear()
            _fetch_prices_cached.clear()
            with st.spinner("Re-seeding…"):
                demo_data.seed()
            st.success("Demo data reset.")
            st.rerun()

    st.markdown("---")
    view = st.radio(
        "View",
        ["Multi-Portfolio Dashboard", "Single Portfolio", "⚙️ Production"],
        label_visibility="collapsed",
    )
    st.markdown("---")

    # Portfolio selector (saved portfolios)
    saved = get_db().list_portfolios()
    if saved:
        selected_name = st.selectbox("Select portfolio", options=saved)
        if st.button("Open", type="primary"):
            with st.spinner("Loading…"):
                st.session_state["portfolio"] = get_db().get_portfolio(selected_name)
        st.markdown("---")

    # Load new portfolio from CSV
    with st.expander("Import from CSV"):
        uploaded = st.file_uploader("Portfolio CSV", type=["csv"])
        portfolio_name_input = st.text_input("Portfolio name", placeholder="e.g. Tech Portfolio")
        if uploaded and st.button("Import"):
            name = portfolio_name_input.strip() or Path(uploaded.name).stem
            with st.spinner("Importing…"):
                st.session_state["portfolio"] = load_portfolio_from_upload(uploaded, name)
            st.success(f"Imported '{name}' — {len(st.session_state['portfolio'].positions)} positions")
            st.rerun()

    # Create an empty portfolio (positions added later via Trade Blotter)
    with st.expander("New Empty Portfolio"):
        new_pf_name = st.text_input(
            "Portfolio name", placeholder="e.g. Crypto", key="new_empty_pf_name"
        )
        if st.button("Create", key="create_empty_pf_btn"):
            nm = new_pf_name.strip()
            if not nm:
                st.error("Name is required.")
            elif nm in get_db().list_portfolios():
                st.error(f"Portfolio '{nm}' already exists.")
            else:
                empty = Portfolio(name=nm, positions=[])
                get_db().save_portfolio(empty)
                st.session_state["portfolio"] = empty
                st.success(f"Created '{nm}'. Add positions in the Trade Blotter tab.")
                st.rerun()

    # Portfolio groups — tag portfolios so they can be filtered together on
    # the Multi-Portfolio Dashboard (e.g. Taxable, Tax-Free, Retirement).
    with st.expander("🏷 Portfolio Groups"):
        _gdb = get_db()
        _all_pfs = _gdb.list_portfolios()
        existing_groups = _gdb.list_groups()

        # Create a new group
        st.markdown("**Create / update**")
        new_g_name = st.text_input(
            "Group name", placeholder="e.g. Tax-Free",
            key="group_new_name",
        )
        new_g_desc = st.text_input(
            "Description (optional)", placeholder="e.g. Roth + HSA + 401k",
            key="group_new_desc",
        )
        if st.button("Create group", key="group_create_btn"):
            nm = new_g_name.strip()
            if not nm:
                st.error("Group name is required.")
            else:
                _gdb.create_group(nm, description=new_g_desc.strip())
                st.success(f"Group '{nm}' saved. Add members below.")
                st.rerun()

        if existing_groups:
            st.markdown("---")
            st.markdown("**Manage memberships**")
            sel_group = st.selectbox(
                "Select group", existing_groups, key="group_manage_select",
            )
            current_members = _gdb.get_group_members(sel_group)
            new_members = st.multiselect(
                "Members", _all_pfs, default=current_members,
                key=f"group_members_{sel_group}",
            )
            col_save, col_del = st.columns(2)
            with col_save:
                if st.button("Save members", key=f"group_save_{sel_group}"):
                    _gdb.set_group_members(sel_group, new_members)
                    st.success(
                        f"Group '{sel_group}' has {len(new_members)} portfolio(s)."
                    )
                    st.rerun()
            with col_del:
                if st.button("Delete group", key=f"group_del_{sel_group}",
                             type="secondary"):
                    _gdb.delete_group(sel_group)
                    st.success(f"Deleted group '{sel_group}'.")
                    st.rerun()
        else:
            st.caption("No groups yet. Create one above to start filtering the dashboard.")

    # Always-visible data action: works regardless of whether a portfolio is loaded.
    if st.button(
        "Refresh metrics",
        key="sidebar_refresh_metrics_btn",
        help="Recompute the daily returns/risk/attribution time series for every portfolio.",
    ):
        from src.attribution import AttributionEngine
        with st.spinner("Computing daily metrics…"):
            summary = AttributionEngine(get_db()).refresh_all()
        modes = summary.get("modes", {})
        v2 = [n for n, m in modes.items() if m == "trade_replay"]
        v1 = [n for n, m in modes.items() if m == "static_current"]
        msg = (
            f"Refreshed metrics — sec: {summary['security_rows']}, "
            f"port: {summary['portfolio_rows']}, attr: {summary['attribution_rows']}"
        )
        if v2 or v1:
            msg += f"\n\nMode used: trade replay → {', '.join(v2) or '—'}; static current → {', '.join(v1) or '—'}"
        st.success(msg)

    if "portfolio" in st.session_state:
        p: Portfolio = st.session_state["portfolio"]
        _active_groups = get_db().get_groups_for_portfolio(p.name)
        st.markdown(
            f"**Active:** {p.name} ({len(p.positions)} positions)"
            + (f"  \n🏷 {', '.join(_active_groups)}" if _active_groups else "")
        )
        st.markdown("---")

        period = st.selectbox("Price history period", ["1mo", "3mo", "6mo", "1y", "2y", "5y"], index=3)
        if st.button("Collect Prices"):
            with st.spinner("Fetching from yfinance…"):
                Collector(get_db()).update_all_assets(period=period)
                _fetch_prices_cached.clear()
            st.success("Prices updated!")

        st.markdown("---")
        if st.button("Delete portfolio", type="secondary"):
            get_db().delete_portfolio(p.name)
            del st.session_state["portfolio"]
            st.rerun()

    st.markdown("---")
    st.caption("CSV columns: Ticker, Name, Type, Quantity, CostBasis, [Currency, Sector]")

# ── Multi-Portfolio Dashboard ─────────────────────────────────────────────────

if view == "Multi-Portfolio Dashboard":
    st.title("Multi-Portfolio Dashboard")

    all_portfolio_names = get_db().list_portfolios()
    if not all_portfolio_names:
        st.info("No portfolios found. Import a portfolio CSV in the sidebar.")
        st.stop()

    # ── Group filter ──────────────────────────────────────────────────────────
    # If groups exist, let the user scope every section of the dashboard to a
    # single group (e.g. "Taxable" or "Tax-Free"). "All portfolios" is the
    # default and matches pre-groups behaviour. Filtering portfolio_names here
    # cascades to every downstream section since they all derive from it.
    _all_groups = get_db().list_groups()
    # Default: not in combined mode. Flipped on below when the user picks a
    # group AND toggles "View as combined portfolio".
    combined_view = False
    combined_name: Optional[str] = None
    combined_members: list[str] = []
    if _all_groups:
        ALL_OPTION = "All portfolios"
        col_grp, col_combined = st.columns([3, 2])
        with col_grp:
            group_choice = st.selectbox(
                "Group filter",
                [ALL_OPTION] + _all_groups,
                key="dashboard_group_filter",
                help=(
                    "Scope every section below — KPIs, exposure, summary, "
                    "attribution, wealth projection — to the portfolios in this "
                    "group. Manage groups via the **🏷 Portfolio Groups** "
                    "expander in the sidebar."
                ),
            )
        if group_choice != ALL_OPTION:
            members = set(get_db().get_group_members(group_choice))
            portfolio_names = [p for p in all_portfolio_names if p in members]
            if not portfolio_names:
                st.warning(
                    f"Group **{group_choice}** has no portfolios assigned. "
                    "Add some in the sidebar's **🏷 Portfolio Groups** expander."
                )
                st.stop()
            with col_combined:
                combined_view = st.toggle(
                    "View as combined portfolio",
                    value=False, key="dashboard_combined_view",
                    help=(
                        "Merge this group's member portfolios into one "
                        "synthetic portfolio. Positions in the same ticker are "
                        "quantity-summed with a weighted-average cost basis. "
                        "Useful for comparing the whole group against benchmarks."
                    ),
                )
            desc = get_db().get_group_description(group_choice)
            st.caption(
                f"Showing **{group_choice}** ({len(portfolio_names)} of "
                f"{len(all_portfolio_names)} portfolios)"
                + (f" — {desc}" if desc else "")
                + (" — *combined view*" if combined_view else "")
            )
            if combined_view:
                combined_members = list(portfolio_names)
                combined_name = f"{group_choice} (combined)"
        else:
            portfolio_names = all_portfolio_names
    else:
        portfolio_names = all_portfolio_names

    HORIZONS = ["1M", "3M", "6M", "1Y"]
    CONFIDENCE_LEVELS = [("95%", "var_95"), ("99%", "var_99")]
    METRIC_COLS = HORIZONS + ["Volatility (Ann.)", "VaR 95% (1d)", "VaR 99% (1d)", "Max Drawdown", "Current Drawdown"]

    # Pre-load all portfolios + latest prices once. Reused by KPIs, summary,
    # and the Wealth Projection.
    portfolios_by_name: dict[str, Portfolio] = {}
    all_tickers: set[str] = set()
    for n in portfolio_names:
        try:
            portfolios_by_name[n] = get_db().get_portfolio(n)
            all_tickers.update(pos.asset.ticker for pos in portfolios_by_name[n].positions)
        except Exception:
            continue

    # ── Combined-portfolio synthesis ──────────────────────────────────────────
    # When the user toggled "View as combined portfolio" on a group, replace
    # the per-portfolio dict with a single synthetic entity that merges every
    # member's positions. Quantities for the same ticker are summed; cost basis
    # is the weighted average. Every downstream section reads from
    # portfolios_by_name, so they all transparently switch to the merged view.
    if combined_view and combined_members and combined_name:
        merged_positions: dict[str, Position] = {}
        for member_name in combined_members:
            p = portfolios_by_name.get(member_name)
            if p is None:
                continue
            for pos in p.positions:
                t = pos.asset.ticker
                if t in merged_positions:
                    e = merged_positions[t]
                    new_qty = e.quantity + pos.quantity
                    new_cb = (
                        (e.quantity * e.cost_basis + pos.quantity * pos.cost_basis) / new_qty
                        if new_qty > 0 else e.cost_basis
                    )
                    merged_positions[t] = Position(
                        asset=e.asset, quantity=new_qty, cost_basis=new_cb,
                    )
                else:
                    merged_positions[t] = pos
        combined_portfolio = Portfolio(
            name=combined_name, positions=list(merged_positions.values()),
        )
        portfolios_by_name = {combined_name: combined_portfolio}
        portfolio_names = [combined_name]
        all_tickers = {pos.asset.ticker for pos in combined_portfolio.positions}

    latest = latest_prices(list(all_tickers)) if all_tickers else {}

    def _market_value(pf: Portfolio) -> float:
        total = 0.0
        for pos in pf.positions:
            price = latest.get(pos.asset.ticker)
            if price is None or (isinstance(price, float) and np.isnan(price)):
                total += pos.quantity * pos.cost_basis
            else:
                total += pos.quantity * float(price)
        return total

    def _fill_metric_cols(row: dict, m: dict | None) -> None:
        if m:
            for h in HORIZONS:
                v = m["cum_returns"].get(h)
                row[h] = fmt_pct(v * 100) if v is not None else "N/A"
            row["Volatility (Ann.)"]  = fmt_pct(m["volatility"] * 100)
            row["VaR 95% (1d)"]       = fmt_pct(m["var_95"] * 100)
            row["VaR 99% (1d)"]       = fmt_pct(m["var_99"] * 100)
            row["Max Drawdown"]       = fmt_pct(m["max_drawdown"] * 100)
            row["Current Drawdown"]   = fmt_pct(m["current_drawdown"] * 100)
        else:
            for col in METRIC_COLS:
                row[col] = "No price data"

    # ── Aggregate KPIs ────────────────────────────────────────────────────────
    total_positions = sum(len(p.positions) for p in portfolios_by_name.values())
    total_cost_all  = sum(p.total_cost() for p in portfolios_by_name.values())
    total_value_all = sum(_market_value(p) for p in portfolios_by_name.values())
    total_pnl_all   = total_value_all - total_cost_all
    total_pnl_pct   = (total_pnl_all / total_cost_all * 100) if total_cost_all else None

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Portfolios",    len(portfolios_by_name))
    k2.metric("Positions",     total_positions)
    k3.metric("Total Cost",    fmt_usd(total_cost_all))
    k4.metric("Current Value", fmt_usd(total_value_all))
    if total_pnl_pct is not None:
        k5.metric("Unrealised P&L", fmt_usd(total_pnl_all), delta=fmt_pct(total_pnl_pct))
    else:
        k5.metric("Unrealised P&L", fmt_usd(total_pnl_all))

    st.markdown("---")

    # ── Aggregate Exposure (with optional lookthrough) ────────────────────────
    _dash_db = get_db()
    # Find funds across all portfolios with either source of lookthrough data.
    vendor_set: set[str] = set()
    yfinance_set: set[str] = set()
    for p in portfolios_by_name.values():
        for pos in p.positions:
            if pos.asset.asset_type.value not in ("ETF", "Fund"):
                continue
            t = pos.asset.ticker
            if t in vendor_set or t in yfinance_set:
                continue
            if not _dash_db.get_fund_holdings(t).empty:
                vendor_set.add(t)
                continue
            prof = _dash_db.get_fund_profile(t)
            if (prof.get("asset_classes") or {}) or (prof.get("sector_weightings") or {}):
                yfinance_set.add(t)

    st.subheader("Aggregate Exposure")
    if vendor_set or yfinance_set:
        dash_lookthrough = st.toggle(
            "🔍 Apply ETF / Fund lookthrough",
            value=False, key="dashboard_lookthrough_toggle",
            help=(
                "When on, ETF/Fund positions are replaced by their constituents. "
                "Dollar totals stay the same — only the breakdown changes.\n\n"
                f"• **Vendor holdings** (ticker-level): "
                f"{', '.join(sorted(vendor_set)) if vendor_set else '—'}\n"
                f"• **yfinance profile fallback** (sector-level): "
                f"{', '.join(sorted(yfinance_set)) if yfinance_set else '—'}"
            ),
        )
    else:
        dash_lookthrough = False
        st.caption(
            "💡 No ETF/Fund holdings or profiles loaded yet — upload a vendor CSV "
            "or use **Fetch Profile from yfinance** in any portfolio's "
            "**🔍 Lookthrough** tab to enable decomposition here."
        )

    all_rows: list[dict] = []
    for pname, p in portfolios_by_name.items():
        for r in expand_lookthrough_rows(p, _dash_db, latest, enabled=dash_lookthrough):
            r["Portfolio"] = pname
            all_rows.append(r)

    if all_rows:
        agg_df = pd.DataFrame(all_rows)
        type_agg = agg_df.groupby("Type")["Current Value"].sum().reset_index()
        type_agg = type_agg[type_agg["Current Value"] > 0]
        sector_agg = (
            agg_df.groupby("Sector")["Current Value"].sum().reset_index()
            .sort_values("Current Value", ascending=True)
        )
        sector_agg = sector_agg[sector_agg["Current Value"] > 0]

        col_t, col_s = st.columns(2)
        with col_t:
            if not type_agg.empty:
                title_suffix = " — with lookthrough" if dash_lookthrough else ""
                fig_t = px.pie(
                    type_agg, names="Type", values="Current Value",
                    title=f"By Asset Type{title_suffix}", hole=0.45,
                )
                fig_t.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig_t, use_container_width=True)
        with col_s:
            if not sector_agg.empty:
                fig_s = px.bar(
                    sector_agg, x="Current Value", y="Sector", orientation="h",
                    title="By Sector", labels={"Current Value": "Value (USD)"},
                )
                fig_s.update_layout(yaxis_title="", xaxis_tickformat="$,.0f")
                st.plotly_chart(fig_s, use_container_width=True)

        # Top tickers table — most useful with lookthrough since it surfaces
        # underlying concentrations even when held via different ETFs.
        top_ticker = (
            agg_df.groupby("Ticker")
            .agg(**{
                "Current Value": ("Current Value", "sum"),
                "Type":          ("Type", "first"),
                "Sector":        ("Sector", "first"),
                "Held Via":      ("Via",  lambda s: ", ".join(sorted({v for v in s if v})) or "—"),
            })
            .reset_index()
            .sort_values("Current Value", ascending=False)
            .head(15)
        )
        if not top_ticker.empty:
            top_ticker["Current Value"] = top_ticker["Current Value"].map(fmt_usd)
            label = "Top 15 underlying exposures" if dash_lookthrough else "Top 15 positions"
            st.markdown(f"**{label}**")
            st.dataframe(top_ticker, use_container_width=True, hide_index=True)

    st.markdown("---")

    summary_rows = []
    metrics_by_name: dict = {}

    for name, p in portfolios_by_name.items():
        m = compute_portfolio_metrics(p)
        metrics_by_name[name] = m
        row: dict = {
            "Portfolio":     name,
            "Positions":     len(p.positions),
            "Total Cost":    fmt_usd(p.total_cost()),
            "Current Value": fmt_usd(_market_value(p)),
        }
        _fill_metric_cols(row, m)
        summary_rows.append(row)

    # ── TOTAL row: aggregate metrics from a merged synthetic portfolio ────────
    if portfolios_by_name:
        merged: dict[str, Position] = {}
        for p in portfolios_by_name.values():
            for pos in p.positions:
                t = pos.asset.ticker
                if t in merged:
                    e = merged[t]
                    new_qty = e.quantity + pos.quantity
                    new_cb = (
                        (e.quantity * e.cost_basis + pos.quantity * pos.cost_basis) / new_qty
                        if new_qty else e.cost_basis
                    )
                    merged[t] = Position(asset=e.asset, quantity=new_qty, cost_basis=new_cb)
                else:
                    merged[t] = pos
        combined = Portfolio(name="__ALL__", positions=list(merged.values()))
        total_row: dict = {
            "Portfolio":     "TOTAL",
            "Positions":     total_positions,
            "Total Cost":    fmt_usd(total_cost_all),
            "Current Value": fmt_usd(total_value_all),
        }
        _fill_metric_cols(total_row, compute_portfolio_metrics(combined))
        summary_rows.append(total_row)

    summary_df = pd.DataFrame(summary_rows)
    st.subheader("Summary")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Returns comparison ────────────────────────────────────────────────────
    st.subheader("Cumulative Returns by Horizon")
    names_with_data = [n for n, m in metrics_by_name.items() if m]
    if names_with_data:
        returns_rows = []
        for name in names_with_data:
            m = metrics_by_name[name]
            for h in HORIZONS:
                v = m["cum_returns"].get(h)
                if v is not None:
                    returns_rows.append({"Portfolio": name, "Horizon": h, "Return (%)": round(v * 100, 2)})
        if returns_rows:
            ret_df = pd.DataFrame(returns_rows)
            fig_ret = px.bar(
                ret_df, x="Horizon", y="Return (%)", color="Portfolio",
                barmode="group",
                category_orders={"Horizon": HORIZONS},
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_ret.update_layout(yaxis_ticksuffix="%", hovermode="x unified")
            st.plotly_chart(fig_ret, use_container_width=True)
    else:
        st.warning("No price data available for any portfolio. Run `invest-monitor collect` first.")

    st.markdown("---")

    # ── Risk comparison ───────────────────────────────────────────────────────
    col_risk, col_dd = st.columns(2)

    with col_risk:
        st.subheader("Risk Metrics")
        if names_with_data:
            risk_rows = []
            for name in names_with_data:
                m = metrics_by_name[name]
                risk_rows.append({
                    "Portfolio": name,
                    "Metric": "Volatility (Ann.)",
                    "Value (%)": round(m["volatility"] * 100, 2),
                })
                risk_rows.append({
                    "Portfolio": name,
                    "Metric": "VaR 95% (1d)",
                    "Value (%)": round(m["var_95"] * 100, 2),
                })
                risk_rows.append({
                    "Portfolio": name,
                    "Metric": "VaR 99% (1d)",
                    "Value (%)": round(m["var_99"] * 100, 2),
                })
            risk_df = pd.DataFrame(risk_rows)
            fig_risk = px.bar(
                risk_df, x="Metric", y="Value (%)", color="Portfolio",
                barmode="group",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_risk.update_layout(yaxis_ticksuffix="%", xaxis_title="")
            st.plotly_chart(fig_risk, use_container_width=True)

    with col_dd:
        st.subheader("Drawdown")
        if names_with_data:
            dd_rows = []
            for name in names_with_data:
                m = metrics_by_name[name]
                dd_rows.append({"Portfolio": name, "Metric": "Max Drawdown",     "Value (%)": round(m["max_drawdown"] * 100, 2)})
                dd_rows.append({"Portfolio": name, "Metric": "Current Drawdown", "Value (%)": round(m["current_drawdown"] * 100, 2)})
            dd_df = pd.DataFrame(dd_rows)
            fig_dd = px.bar(
                dd_df, x="Metric", y="Value (%)", color="Portfolio",
                barmode="group",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_dd.update_layout(yaxis_ticksuffix="%", xaxis_title="")
            st.plotly_chart(fig_dd, use_container_width=True)

    # ── Income Projection ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Income Projection")
    st.caption(
        "Annual cash flow from coupons (Bond/CD), interest (Cash), and dividends "
        "(Stock/ETF/Fund). Driven by **income_rate** in the Security Master."
    )

    _reporting = get_reporting()
    all_income_rows = []
    income_by_portfolio = {}
    for pname, p in portfolios_by_name.items():
        df_inc = _reporting.compute_portfolio_income(p, latest_prices=latest)
        if not df_inc.empty:
            df_inc.insert(0, "Portfolio", pname)
            all_income_rows.append(df_inc)
            income_by_portfolio[pname] = float(df_inc["Annual Income"].sum())

    if all_income_rows:
        income_df = pd.concat(all_income_rows, ignore_index=True)
        total_annual    = float(income_df["Annual Income"].sum())
        total_monthly   = total_annual / 12.0
        total_yield_pct = (total_annual / total_value_all * 100.0) if total_value_all else 0.0

        i1, i2, i3, i4 = st.columns(4)
        i1.metric("Annual Income",    fmt_usd(total_annual))
        i2.metric("Monthly Average",  fmt_usd(total_monthly))
        i3.metric("Portfolio Yield",  fmt_pct(total_yield_pct))
        i4.metric("Income-Generating", f"{(income_df['Annual Income'] > 0).sum()} of {len(income_df)} positions")

        # Per-portfolio summary
        pf_rows = []
        for pname in portfolios_by_name:
            ann = income_by_portfolio.get(pname, 0.0)
            value = _market_value(portfolios_by_name[pname])
            pf_rows.append({
                "Portfolio": pname,
                "Annual Income": fmt_usd(ann),
                "Monthly": fmt_usd(ann / 12.0),
                "Yield (%)": fmt_pct((ann / value * 100.0) if value else 0.0),
            })
        if len(pf_rows) > 1:
            pf_rows.append({
                "Portfolio": "TOTAL",
                "Annual Income": fmt_usd(total_annual),
                "Monthly": fmt_usd(total_monthly),
                "Yield (%)": fmt_pct(total_yield_pct),
            })
        st.markdown("**By Portfolio**")
        st.dataframe(pd.DataFrame(pf_rows), use_container_width=True, hide_index=True)

        # Income by asset type
        col_ai, col_ap = st.columns(2)
        with col_ai:
            type_inc = income_df.groupby("Type")["Annual Income"].sum().reset_index()
            type_inc = type_inc[type_inc["Annual Income"] > 0]
            if not type_inc.empty:
                fig_inc = px.pie(
                    type_inc, names="Type", values="Annual Income",
                    title="Annual Income by Asset Type", hole=0.4,
                )
                fig_inc.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig_inc, use_container_width=True)
            else:
                st.info("No income-generating positions. Set **Income Rate** in the Security Master.")

        # Monthly schedule — payment_frequency-aware
        with col_ap:
            months = list(range(1, 13))
            schedule = {m: 0.0 for m in months}
            for _, r in income_df.iterrows():
                ann = float(r["Annual Income"])
                if ann <= 0:
                    continue
                freq = int(r["Payment Frequency"]) or 1
                per_payment = ann / freq
                step = max(1, 12 // freq)
                for m in range(step, 13, step):
                    schedule[m] += per_payment
            sched_df = pd.DataFrame({
                "Month": [pd.Timestamp(2026, m, 1).strftime("%b") for m in months],
                "Income": [schedule[m] for m in months],
            })
            fig_sched = px.bar(
                sched_df, x="Month", y="Income",
                title="Income by Calendar Month (next 12)",
                labels={"Income": "Income (USD)"},
            )
            fig_sched.update_layout(yaxis_tickprefix="$", yaxis_tickformat=",.0f")
            st.plotly_chart(fig_sched, use_container_width=True)

        # Per-position table — only show positions with positive income
        st.markdown("**Per-Position Detail**")
        contrib = income_df[income_df["Annual Income"] > 0].copy()
        if contrib.empty:
            st.info("No positions have a non-zero income_rate set yet.")
        else:
            contrib = contrib.sort_values("Annual Income", ascending=False)
            contrib_disp = contrib.copy()
            contrib_disp["Base Value"]        = contrib_disp["Base Value"].map(fmt_usd)
            contrib_disp["Income Rate"]       = contrib_disp.apply(_fmt_income_rate, axis=1)
            contrib_disp["Annual Income"]     = contrib_disp["Annual Income"].map(fmt_usd)
            contrib_disp["Monthly Income"]    = contrib_disp["Monthly Income"].map(fmt_usd)
            contrib_disp["Yield on Base (%)"] = contrib_disp["Yield on Base (%)"].map(lambda v: f"{v:.2f}%")
            contrib_disp = contrib_disp.drop(columns=["Income Rate Unit"], errors="ignore")
            st.dataframe(contrib_disp, use_container_width=True, hide_index=True)
    else:
        st.info("No income data — add positions or set **Income Rate** in the Security Master.")

    # ── Performance Attribution ──────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Performance Attribution")
    st.caption(
        "Daily portfolio returns decomposed into per-position contributions. "
        "Click **Refresh metrics** in the sidebar to (re)compute. "
        "Each portfolio uses **trade replay** if any trades are recorded for it "
        "(positions reconstructed by cumulative-summing the BUY/SELL ledger), "
        "otherwise falls back to **static current positions**."
    )

    _attr_db = get_db()
    port_metrics_all = _attr_db.get_daily_portfolio_metrics()
    # Scope the persisted metrics to the active portfolio set. In combined
    # view, aggregate member portfolios into a synthetic series by summing
    # daily total_value across members and re-deriving daily_return /
    # cum_return / drawdown / rolling vol from the merged value series.
    if not port_metrics_all.empty:
        if combined_view and combined_members and combined_name:
            pm = port_metrics_all[
                port_metrics_all["portfolio_name"].isin(combined_members)
            ].copy()
            pm["date"] = pd.to_datetime(pm["date"])
            if not pm.empty:
                agg = (
                    pm.groupby("date", as_index=False)["total_value"].sum()
                    .sort_values("date").reset_index(drop=True)
                )
                agg["portfolio_name"]  = combined_name
                agg["daily_return"]    = agg["total_value"].pct_change()
                first_v = float(agg["total_value"].iloc[0]) if len(agg) else 0.0
                agg["cum_return"]      = (agg["total_value"] / first_v - 1.0) if first_v > 0 else np.nan
                agg["rolling_vol_21d"] = agg["daily_return"].rolling(21).std() * np.sqrt(252.0)
                cum_value = agg["total_value"]
                cummax    = cum_value.cummax()
                agg["drawdown"]     = (cum_value - cummax) / cummax
                agg["max_drawdown"] = agg["drawdown"].cummin()
                port_metrics_all = agg
            else:
                port_metrics_all = pm  # empty
        else:
            port_metrics_all = port_metrics_all[
                port_metrics_all["portfolio_name"].isin(portfolio_names)
            ]

    if port_metrics_all.empty:
        st.info(
            "No daily metrics stored yet. Use **Refresh metrics** in the sidebar "
            "(or `invest-monitor metrics refresh`) to compute them."
        )
    else:
        port_metrics_all["date"] = pd.to_datetime(port_metrics_all["date"])

        # Period filter
        latest_dt = port_metrics_all["date"].max()
        period_label = st.radio(
            "Period",
            ["1M", "3M", "6M", "1Y", "YTD", "All"],
            horizontal=True, index=2, key="attr_period",
        )
        period_days = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365}
        if period_label == "All":
            cutoff = port_metrics_all["date"].min()
        elif period_label == "YTD":
            cutoff = pd.Timestamp(latest_dt.year, 1, 1)
        else:
            cutoff = latest_dt - pd.Timedelta(days=period_days[period_label])

        pm = port_metrics_all[port_metrics_all["date"] >= cutoff].copy()

        # Cumulative return — re-anchor to the start of the selected window so
        # the chart reads "+X% over the period" rather than "since-inception".
        pm = pm.sort_values(["portfolio_name", "date"])
        pm["window_cum"] = (
            pm.groupby("portfolio_name")["daily_return"]
            .transform(lambda s: (1.0 + s.fillna(0.0)).cumprod() - 1.0)
        )

        # Benchmark overlay selection
        from src.benchmarks import (
            BENCHMARKS, benchmark_daily_returns, benchmark_stats,
        )
        selected_benchmarks = st.multiselect(
            "Overlay benchmarks",
            options=list(BENCHMARKS.keys()),
            default=[],
            key="attr_bench_select",
            help=(
                "Compare each portfolio against canonical benchmark recipes "
                "(60/40, All Seasons, Golden Butterfly, etc.). Benchmarks are "
                "built from public ETF proxies — if the chart line is missing "
                "or sparse, run `invest-monitor benchmarks fetch` to pull prices "
                "for the proxy tickers, then **Refresh metrics**."
            ),
        )

        # Build the cumulative-return chart, optionally overlaying benchmarks.
        col_ret, col_dd = st.columns(2)
        with col_ret:
            fig_ret = px.line(
                pm, x="date", y="window_cum", color="portfolio_name",
                title=f"Cumulative return — {period_label}",
                labels={"window_cum": "Cumulative Return", "date": ""},
            )
            # Overlay each selected benchmark as a dashed line, rebased to the
            # same window start so directly comparable to the portfolio lines.
            cutoff_str = cutoff.strftime("%Y-%m-%d")
            for bname in selected_benchmarks:
                b = BENCHMARKS[bname]
                daily_b = benchmark_daily_returns(b, _attr_db, start_date=cutoff_str)
                if daily_b.empty:
                    continue
                cum_b = (1.0 + daily_b).cumprod() - 1.0
                fig_ret.add_trace(go.Scatter(
                    x=cum_b.index, y=cum_b.values, mode="lines",
                    name=f"{bname} (benchmark)",
                    line=dict(dash="dash", width=2),
                ))
            fig_ret.update_layout(yaxis_tickformat=".1%", hovermode="x unified")
            st.plotly_chart(fig_ret, use_container_width=True)
        with col_dd:
            fig_dd = px.area(
                pm, x="date", y="drawdown", color="portfolio_name",
                title="Drawdown (peak-to-trough, since inception)",
                labels={"drawdown": "Drawdown", "date": ""},
            )
            fig_dd.update_layout(yaxis_tickformat=".1%", hovermode="x unified")
            st.plotly_chart(fig_dd, use_container_width=True)

        # End-of-period KPI strip per portfolio
        end_kpi_rows = []
        for name, grp in pm.groupby("portfolio_name"):
            grp = grp.sort_values("date")
            last = grp.iloc[-1]
            end_kpi_rows.append({
                "Portfolio": name,
                "Period Return": f"{last['window_cum']:+.2%}",
                "Annualised Vol (21d)": f"{(last['rolling_vol_21d'] or 0)*100:.2f}%",
                "Current Drawdown": f"{(last['drawdown'] or 0)*100:.2f}%",
                "Max Drawdown (since inception)": f"{(last['max_drawdown'] or 0)*100:.2f}%",
                "Latest Value": fmt_usd(last["total_value"]),
            })
        st.dataframe(pd.DataFrame(end_kpi_rows), use_container_width=True, hide_index=True)

        # Benchmark stats table over the same window (when overlays are picked)
        if selected_benchmarks:
            bench_rows = []
            for bname in selected_benchmarks:
                stats_b = benchmark_stats(BENCHMARKS[bname], _attr_db, start_date=cutoff_str)
                pr = stats_b.get("period_return")
                vol = stats_b.get("vol_annualised")
                mdd = stats_b.get("max_drawdown")
                bench_rows.append({
                    "Benchmark": bname,
                    "Period Return": f"{pr:+.2%}" if pr is not None else "—",
                    "Annualised Vol": f"{vol*100:.2f}%" if vol is not None else "—",
                    "Max Drawdown (window)": f"{mdd*100:.2f}%" if mdd is not None else "—",
                    "# Proxies": len(BENCHMARKS[bname].proxies),
                })
            st.markdown("**Benchmark stats over the same window**")
            st.dataframe(pd.DataFrame(bench_rows), use_container_width=True, hide_index=True)

            # vs-benchmark delta: portfolio period return minus the first
            # selected benchmark's period return. Quick "did I beat it" read.
            primary_bench = selected_benchmarks[0]
            primary_pr = benchmark_stats(
                BENCHMARKS[primary_bench], _attr_db, start_date=cutoff_str,
            ).get("period_return")
            if primary_pr is not None:
                delta_rows = []
                for r in end_kpi_rows:
                    # Re-parse the period return string back to a float for math.
                    pr_pct = float(r["Period Return"].rstrip("%")) / 100.0
                    delta_rows.append({
                        "Portfolio": r["Portfolio"],
                        "Period Return": r["Period Return"],
                        f"vs {primary_bench}": f"{(pr_pct - primary_pr) * 100:+.2f}%",
                    })
                st.markdown(f"**vs {primary_bench} (period return delta)**")
                st.dataframe(pd.DataFrame(delta_rows), use_container_width=True, hide_index=True)

        # Attribution: top contributors / detractors in the window.
        # Scope to the active portfolio set, and in combined view re-label
        # every member row so the table aggregates across them.
        attr_all = _attr_db.get_daily_attribution(start_date=cutoff.strftime("%Y-%m-%d"))
        if not attr_all.empty:
            if combined_view and combined_members and combined_name:
                attr_all = attr_all[attr_all["portfolio_name"].isin(combined_members)].copy()
                attr_all["portfolio_name"] = combined_name
            else:
                attr_all = attr_all[attr_all["portfolio_name"].isin(portfolio_names)]
        if not attr_all.empty:
            attr_all["date"] = pd.to_datetime(attr_all["date"])
            sum_contrib = (
                attr_all.groupby(["portfolio_name", "ticker", "asset_type", "sector"])
                ["contribution_to_return"].sum()
                .reset_index()
                .sort_values("contribution_to_return", ascending=False)
            )

            st.markdown(f"**Top 10 contributors over {period_label} (Σ daily contributions)**")
            top = sum_contrib.head(10).copy()
            top["contribution_to_return"] = top["contribution_to_return"].map(lambda v: f"{v*100:+.2f}%")
            st.dataframe(top, use_container_width=True, hide_index=True)

            st.markdown(f"**Top 10 detractors over {period_label}**")
            bot = sum_contrib.tail(10).sort_values("contribution_to_return").copy()
            bot["contribution_to_return"] = bot["contribution_to_return"].map(lambda v: f"{v*100:+.2f}%")
            st.dataframe(bot, use_container_width=True, hide_index=True)

            # Cumulative contribution by asset type, stacked over time
            by_at = (
                attr_all.groupby(["date", "asset_type"])["contribution_to_return"]
                .sum().reset_index()
            )
            by_at = by_at.sort_values(["asset_type", "date"])
            by_at["cum_contrib"] = (
                by_at.groupby("asset_type")["contribution_to_return"]
                .transform(lambda s: s.cumsum())
            )
            fig_at = px.area(
                by_at, x="date", y="cum_contrib", color="asset_type",
                title=f"Cumulative contribution by asset type — {period_label}",
                labels={"cum_contrib": "Contribution (sum)", "date": ""},
            )
            fig_at.update_layout(yaxis_tickformat=".1%", hovermode="x unified")
            st.plotly_chart(fig_at, use_container_width=True)

    # ── Wealth Projection ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Wealth Projection")

    method = st.radio(
        "Method", ["Deterministic", "Monte Carlo"],
        horizontal=True, key="wp_method",
        help=(
            "Deterministic: fixed expected return per asset type, possibly with "
            "multiple time periods. Monte Carlo: draw random annual returns "
            "from N(μ, σ) per asset type for many simulated futures."
        ),
    )

    ASSET_TYPES = ["Stock", "ETF", "Bond", "Fund", "Cash", "CD"]
    DEFAULT_RETURNS = {"Stock": 8.0, "ETF": 7.0, "Bond": 3.5, "Fund": 6.0, "Cash": 4.5, "CD": 4.5}
    DEFAULT_VOLS    = {"Stock": 18.0, "ETF": 14.0, "Bond": 5.0, "Fund": 11.0, "Cash": 0.5, "CD": 0.0}

    current_year = pd.Timestamp.now().year
    milestone_year_options = [5, 10, 15, 20, 30, 40, 50]

    def _start_value(pos) -> float:
        price = latest.get(pos.asset.ticker)
        if price is None or (isinstance(price, float) and np.isnan(price)):
            return pos.quantity * pos.cost_basis
        return pos.quantity * float(price)

    # ── Shared withdrawal settings (Safe Withdrawal Rate) ─────────────────────
    with st.expander("💰 Withdrawals (Safe Withdrawal Rate)", expanded=False):
        apply_withdrawals = st.checkbox(
            "Apply annual withdrawals", value=False, key="wp_apply_withdrawals",
            help=(
                "Subtract an annual cash withdrawal from the portfolio. Classic "
                "Bengen 4% rule: dollar amount = SWR% × today's portfolio value, "
                "fixed in real terms (with inflation adjustment) for the horizon."
            ),
        )
        if apply_withdrawals:
            col_swr, col_inf = st.columns(2)
            with col_swr:
                primary_swr_pct = st.number_input(
                    "Primary withdrawal rate (% of starting value)",
                    min_value=0.0, max_value=20.0, value=4.0, step=0.25,
                    format="%.2f", key="wp_swr_primary",
                )
            with col_inf:
                inflation_pct = st.number_input(
                    "Inflation adjustment (%/yr)",
                    min_value=0.0, max_value=20.0, value=3.0, step=0.25,
                    format="%.2f", key="wp_inflation",
                    help="Withdrawal grows by this rate each year. Set to 0 for a flat nominal withdrawal.",
                )

            rebalance_annually = st.checkbox(
                "Rebalance to starting weights each year",
                value=True, key="wp_rebalance",
                help=(
                    "After applying returns + withdrawal, snap each position back to "
                    "its starting-year weight × current total. Models a disciplined "
                    "annual rebalance — keeps the asset mix from drifting away from "
                    "target as different types compound at different rates."
                ),
            )

            if method == "Monte Carlo":
                compare_swrs = st.multiselect(
                    "Compare success rate at additional withdrawal rates",
                    options=[2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0],
                    default=[3.0, 4.0, 5.0],
                    key="wp_compare_swrs",
                    help=(
                        "For each rate, the simulation reports the % of paths that "
                        "still have money at the horizon. Useful for finding the "
                        "highest rate that meets your target success threshold."
                    ),
                )
            else:
                compare_swrs = []
        else:
            primary_swr_pct = 0.0
            inflation_pct = 0.0
            compare_swrs = []
            rebalance_annually = False

    if method == "Deterministic":
        with st.expander("Projection Settings", expanded=True):
            col_h, col_p = st.columns([3, 1])
            with col_h:
                horizon = st.slider("Projection horizon (years)", 5, 50, 20, step=5)
            with col_p:
                n_periods = st.radio("Growth periods", [1, 2, 3], horizontal=True)

            # Period split year inputs
            split_years: list[int] = []
            if n_periods >= 2:
                s1 = st.number_input(
                    "Period 1 ends at year", min_value=1, max_value=horizon - 1,
                    value=min(5, horizon - 1), step=1, key="wp_split1",
                )
                split_years.append(int(s1))
            if n_periods == 3:
                s2_min = split_years[0] + 1
                s2 = st.number_input(
                    "Period 2 ends at year", min_value=s2_min, max_value=horizon - 1,
                    value=min(split_years[0] + 5, horizon - 1), step=1, key="wp_split2",
                )
                split_years.append(int(s2))

            starts = [1] + [s + 1 for s in split_years]
            ends   = split_years + [horizon]

            # Return inputs — one column per period
            period_cols = st.columns(n_periods)
            periods_cfg: list[dict] = []
            for i, col in enumerate(period_cols):
                with col:
                    label = f"Period {i + 1}  —  Year {starts[i]}–{ends[i]}"
                    st.markdown(f"**{label}**")
                    returns: dict[str, float] = {}
                    for at in ASSET_TYPES:
                        returns[at] = st.number_input(
                            f"{at} (% / yr)", min_value=-20.0, max_value=50.0,
                            value=DEFAULT_RETURNS[at], step=0.5, format="%.1f",
                            key=f"wp_ret_{i}_{at}",
                        ) / 100.0
                    periods_cfg.append({"start": starts[i], "end": ends[i], "returns": returns})

        def _annual_rate(year: int, at: str) -> float:
            for pc in periods_cfg:
                if pc["start"] <= year <= pc["end"]:
                    return pc["returns"].get(at, 0.0)
            return 0.0

        years_axis = list(range(horizon + 1))
        x_labels = [current_year + y for y in years_axis]

        fig_wealth = go.Figure()
        milestone_rows = []
        total_values = [0.0] * (horizon + 1)
        milestone_years = [yr for yr in milestone_year_options if yr <= horizon]
        # Track year-of-depletion per portfolio so the milestone table can flag it.
        depletion_year: dict[str, int | None] = {}

        for pname, p in portfolios_by_name.items():
            # Per-position state — (value, asset_type). Maintaining per-position
            # values lets us apply different annual returns AND pro-rata withdraw.
            pos_state: list[list] = [
                [_start_value(pos), pos.asset.asset_type.value] for pos in p.positions
            ]
            initial_total = sum(v for v, _ in pos_state)
            values = [initial_total]
            base_withdrawal = initial_total * (primary_swr_pct / 100.0) if apply_withdrawals else 0.0
            # Snapshot target weights for optional annual rebalancing.
            target_weights = (
                [(v / initial_total) for v, _ in pos_state] if initial_total > 0
                else [0.0 for _ in pos_state]
            )

            depleted_at: int | None = None
            for yr in range(1, horizon + 1):
                # 1) Apply returns to each position (independent compounding).
                for i, (v, at) in enumerate(pos_state):
                    pos_state[i][0] = max(0.0, v * (1 + _annual_rate(yr, at)))
                total_after_returns = sum(v for v, _ in pos_state)

                # 2) Apply pro-rata withdrawal (Bengen-style: $ amount fixed in
                #    real terms, grown by inflation each year).
                if apply_withdrawals and total_after_returns > 0:
                    wd = base_withdrawal * ((1 + inflation_pct / 100.0) ** (yr - 1))
                    actual = min(wd, total_after_returns)
                    ratio = (total_after_returns - actual) / total_after_returns
                    for i in range(len(pos_state)):
                        pos_state[i][0] *= ratio

                # 3) Optional rebalance to starting weights so the asset mix
                #    doesn't drift as different types compound at different rates.
                if apply_withdrawals and rebalance_annually:
                    year_total = sum(v for v, _ in pos_state)
                    if year_total > 0:
                        for i in range(len(pos_state)):
                            pos_state[i][0] = year_total * target_weights[i]

                year_total = sum(v for v, _ in pos_state)
                values.append(year_total)
                if depleted_at is None and apply_withdrawals and year_total <= 1e-6:
                    depleted_at = yr

            depletion_year[pname] = depleted_at

            for i, v in enumerate(values):
                total_values[i] += v

            fig_wealth.add_trace(go.Scatter(
                x=x_labels, y=values, name=pname,
                mode="lines", line=dict(width=2),
                hovertemplate="%{x}: $%{y:,.0f}<extra>" + pname + "</extra>",
            ))

            milestones = {"Portfolio": pname, "Today": fmt_usd(values[0])}
            for yr in milestone_years:
                milestones[f"Year {yr}"] = fmt_usd(values[yr])
            if apply_withdrawals:
                milestones["Depletes"] = (
                    f"Year {depleted_at}" if depleted_at is not None else "—"
                )
            milestone_rows.append(milestones)

        if len(portfolios_by_name) > 1:
            fig_wealth.add_trace(go.Scatter(
                x=x_labels, y=total_values, name="TOTAL",
                mode="lines", line=dict(width=3, dash="dash", color="black"),
                hovertemplate="%{x}: $%{y:,.0f}<extra>TOTAL</extra>",
            ))
            total_row = {"Portfolio": "TOTAL", "Today": fmt_usd(total_values[0])}
            for yr in milestone_years:
                total_row[f"Year {yr}"] = fmt_usd(total_values[yr])
            if apply_withdrawals:
                # TOTAL depletes at the latest depletion year across portfolios
                # — if any portfolio survives, the aggregate isn't depleted.
                survivors = [pname for pname, dy in depletion_year.items() if dy is None]
                if survivors:
                    total_row["Depletes"] = "—"
                else:
                    latest_dep = max(d for d in depletion_year.values() if d is not None)
                    total_row["Depletes"] = f"Year {latest_dep}"
            milestone_rows.append(total_row)

        title_suffix = (
            f" — withdrawing {primary_swr_pct:.1f}%/yr"
            f"{f' (+{inflation_pct:.1f}% inflation)' if (apply_withdrawals and inflation_pct) else ''}"
            f"{', annual rebalance' if (apply_withdrawals and rebalance_annually) else ''}"
            if apply_withdrawals else ""
        )
        fig_wealth.update_layout(
            title=f"Wealth Projection{title_suffix}" if apply_withdrawals else None,
            xaxis_title="Year",
            yaxis_title="Projected Value",
            yaxis_tickprefix="$",
            yaxis_tickformat=",.0f",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_wealth, use_container_width=True)

        if milestone_rows:
            st.markdown("**Projected value at milestones**")
            st.dataframe(pd.DataFrame(milestone_rows), use_container_width=True, hide_index=True)

    else:
        # ── Monte Carlo ──────────────────────────────────────────────────────
        from src.scenarios import DEFAULT_ASSET_CORRELATIONS, WEALTH_MC_PRESETS

        with st.expander("Monte Carlo Settings", expanded=True):
            # Historical regime preset selector — picking one re-seeds the
            # return / vol / correlation inputs from that period's stats.
            preset_options = ["Default (forward-looking)"] + list(WEALTH_MC_PRESETS.keys())
            preset_choice = st.selectbox(
                "Regime preset",
                preset_options,
                key="mc_preset",
                help=(
                    "Load μ, σ, and the cross-asset correlation matrix from a "
                    "historical period. The values below are the preset's defaults; "
                    "edits persist until you switch presets."
                ),
            )
            if preset_choice == "Default (forward-looking)":
                use_returns = DEFAULT_RETURNS
                use_vols    = DEFAULT_VOLS
                use_corr    = DEFAULT_ASSET_CORRELATIONS
            else:
                preset = WEALTH_MC_PRESETS[preset_choice]
                st.caption(preset["description"])
                use_returns = preset["returns"]
                use_vols    = preset["vols"]
                use_corr    = preset["correlations"]
            # Slug used to key widgets so switching presets re-seeds defaults
            # (Streamlit retains widget state per-key; new key → fresh default).
            preset_slug = preset_choice.replace(" ", "_").replace("/", "_")

            col_h, col_n, col_g = st.columns([1, 1, 1])
            with col_h:
                horizon = st.slider(
                    "Projection horizon (years)", 5, 50, 20, step=5, key="mc_horizon",
                )
            with col_n:
                n_sims = st.select_slider(
                    "Number of simulations",
                    options=[100, 500, 1000, 2000, 5000, 10000],
                    value=2000, key="mc_nsims",
                )
            with col_g:
                goal = st.number_input(
                    "Goal amount ($, optional)",
                    min_value=0, value=0, step=10000, key="mc_goal",
                    help="If > 0, the chart marks this line and the KPI strip shows the probability of reaching it.",
                )

            st.markdown("**Annual return & volatility by asset type** (% per year)")
            cols = st.columns(2)
            mc_returns: dict[str, float] = {}
            mc_vols: dict[str, float] = {}
            with cols[0]:
                st.markdown("**Expected Return (μ)**")
                for at in ASSET_TYPES:
                    mc_returns[at] = st.number_input(
                        at, min_value=-50.0, max_value=50.0,
                        value=float(use_returns.get(at, DEFAULT_RETURNS[at])),
                        step=0.5, format="%.1f",
                        key=f"mc_ret_{preset_slug}_{at}",
                    ) / 100.0
            with cols[1]:
                st.markdown("**Volatility (σ)**")
                for at in ASSET_TYPES:
                    mc_vols[at] = st.number_input(
                        at, min_value=0.0, max_value=200.0,
                        value=float(use_vols.get(at, DEFAULT_VOLS[at])),
                        step=0.5, format="%.1f",
                        key=f"mc_vol_{preset_slug}_{at}",
                    ) / 100.0

            st.markdown("**Cross-asset correlations** — preset-driven; edit cells to override")
            default_corr_df = pd.DataFrame(
                [[use_corr[a][b] for b in ASSET_TYPES] for a in ASSET_TYPES],
                index=ASSET_TYPES, columns=ASSET_TYPES,
            )
            edited_corr = st.data_editor(
                default_corr_df,
                use_container_width=True,
                num_rows="fixed",
                column_config={
                    c: st.column_config.NumberColumn(c, min_value=-1.0, max_value=1.0, step=0.05, format="%.2f")
                    for c in ASSET_TYPES
                },
                key=f"mc_corr_editor_{preset_slug}",
            )
            # Symmetrize (so an edit on one side propagates) and force unit diag.
            corr_matrix = (edited_corr.values + edited_corr.values.T) / 2.0
            np.fill_diagonal(corr_matrix, 1.0)
            corr_matrix = np.clip(corr_matrix, -1.0, 1.0)

        milestone_years = [yr for yr in milestone_year_options if yr <= horizon]
        x_labels = [current_year + y for y in range(horizon + 1)]

        # ── Build covariance matrix and pre-draw correlated annual returns ───
        mu_vec  = np.array([mc_returns[at]  for at in ASSET_TYPES])
        sig_vec = np.array([mc_vols[at]     for at in ASSET_TYPES])
        cov_matrix = corr_matrix * np.outer(sig_vec, sig_vec)
        # Nudge onto the PSD cone if user edits break it (replace negative
        # eigenvalues with a small positive floor).
        eigvals, eigvecs = np.linalg.eigh(cov_matrix)
        if (eigvals < 0).any():
            eigvals = np.clip(eigvals, 1e-10, None)
            cov_matrix = (eigvecs * eigvals) @ eigvecs.T

        rng = np.random.default_rng(seed=42)
        # One multivariate normal draw per (sim, year) → returns per asset type.
        # Shape: (n_sims, horizon, n_types). Within-type positions share the
        # draw; cross-type relationships honour the correlation matrix.
        type_returns = rng.multivariate_normal(
            mean=mu_vec, cov=cov_matrix, size=(n_sims, horizon),
        )
        np.clip(type_returns, -0.99, None, out=type_returns)
        # Cumulative growth per asset type per sim: (n_sims, horizon, n_types)
        type_growth = np.cumprod(1.0 + type_returns, axis=1)

        type_idx = {at: i for i, at in enumerate(ASSET_TYPES)}

        def _simulate(swr_pct: float) -> tuple[dict[str, np.ndarray], np.ndarray]:
            """Run the per-position MC under a given SWR.
            Returns (paths_by_portfolio, total_paths). swr_pct=0 → no withdrawals."""
            pbp: dict[str, np.ndarray] = {}
            tp = np.zeros((n_sims, horizon + 1))
            apply_wd = (apply_withdrawals and swr_pct > 0)
            for pname, p in portfolios_by_name.items():
                # Per-position arrays so we can compound positions independently
                # AND subtract withdrawals pro-rata each year.
                position_info: list[tuple[float, int]] = []
                for pos in p.positions:
                    at = pos.asset.asset_type.value
                    if at not in type_idx:
                        continue
                    position_info.append((_start_value(pos), type_idx[at]))

                paths = np.zeros((n_sims, horizon + 1))
                if not position_info:
                    pbp[pname] = paths
                    continue

                pos_values = np.zeros((n_sims, len(position_info)))
                for i, (sv, _) in enumerate(position_info):
                    pos_values[:, i] = sv
                initial_total = float(sum(sv for sv, _ in position_info))
                paths[:, 0] = initial_total
                base_withdrawal = initial_total * (swr_pct / 100.0) if apply_wd else 0.0
                # Snapshot target weights once for optional annual rebalancing.
                # Shape (n_positions,) — broadcast across sims at apply time.
                tgt_weights = np.array(
                    [sv / initial_total for sv, _ in position_info]
                    if initial_total > 0 else
                    [0.0] * len(position_info),
                    dtype=float,
                )
                do_rebal = bool(apply_wd and rebalance_annually)

                for yr in range(horizon):
                    for i, (_, ti) in enumerate(position_info):
                        pos_values[:, i] *= (1.0 + type_returns[:, yr, ti])
                    np.clip(pos_values, 0.0, None, out=pos_values)

                    total_after = pos_values.sum(axis=1)
                    if apply_wd:
                        wd = base_withdrawal * ((1.0 + inflation_pct / 100.0) ** yr)
                        actual = np.minimum(wd, total_after)
                        with np.errstate(divide="ignore", invalid="ignore"):
                            ratio = np.where(
                                total_after > 0,
                                (total_after - actual) / total_after,
                                0.0,
                            )
                        pos_values *= ratio[:, None]

                    # Annual rebalance: snap each sim's position values back to
                    # target weights × current total. Vectorised: outer product
                    # of (n_sims,) totals with (n_positions,) weights.
                    if do_rebal:
                        year_total = pos_values.sum(axis=1)
                        pos_values = year_total[:, None] * tgt_weights[None, :]

                    paths[:, yr + 1] = pos_values.sum(axis=1)

                pbp[pname] = paths
                tp += paths
            return pbp, tp

        with st.spinner(f"Running {n_sims:,} correlated Monte Carlo paths…"):
            paths_by_portfolio, total_paths = _simulate(
                primary_swr_pct if apply_withdrawals else 0.0
            )

        # ── Fan chart (combined TOTAL) ───────────────────────────────────────
        pcts = [10, 25, 50, 75, 90]
        p_curves = {pct: np.percentile(total_paths, pct, axis=0) for pct in pcts}

        fig_mc = go.Figure()
        fig_mc.add_trace(go.Scatter(
            x=x_labels, y=p_curves[90], mode="lines",
            line=dict(width=0), showlegend=False, name="P90",
        ))
        fig_mc.add_trace(go.Scatter(
            x=x_labels, y=p_curves[10], mode="lines",
            line=dict(width=0), fill="tonexty",
            fillcolor="rgba(99,110,250,0.15)", name="P10–P90",
        ))
        fig_mc.add_trace(go.Scatter(
            x=x_labels, y=p_curves[75], mode="lines",
            line=dict(width=0), showlegend=False, name="P75",
        ))
        fig_mc.add_trace(go.Scatter(
            x=x_labels, y=p_curves[25], mode="lines",
            line=dict(width=0), fill="tonexty",
            fillcolor="rgba(99,110,250,0.32)", name="P25–P75",
        ))
        fig_mc.add_trace(go.Scatter(
            x=x_labels, y=p_curves[50], mode="lines",
            line=dict(width=3, color="rgb(99,110,250)"), name="P50 (median)",
        ))

        if goal > 0:
            fig_mc.add_hline(
                y=goal, line_dash="dash", line_color="red",
                annotation_text=f"Goal: ${goal:,.0f}",
                annotation_position="top right",
            )

        mc_title = f"Monte Carlo — Combined Portfolios ({n_sims:,} simulations)"
        if apply_withdrawals:
            inf_note = f" +{inflation_pct:.1f}% inflation" if inflation_pct else ""
            rebal_note = ", annual rebalance" if rebalance_annually else ""
            mc_title += f" — withdrawing {primary_swr_pct:.2f}%/yr{inf_note}{rebal_note}"
        fig_mc.update_layout(
            title=mc_title,
            xaxis_title="Year",
            yaxis_title="Projected Value",
            yaxis_tickprefix="$", yaxis_tickformat=",.0f",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_mc, use_container_width=True)

        # ── KPIs ─────────────────────────────────────────────────────────────
        final = total_paths[:, -1]

        def _depletion_year(paths: np.ndarray) -> float | None:
            """Median year-of-depletion across paths that hit zero. None if no path depletes."""
            # First year (1-indexed) each path's value drops to ~0
            zero_mask = paths <= 1e-6  # shape (n_sims, horizon+1)
            depleted = zero_mask.any(axis=1)
            if not depleted.any():
                return None
            # argmax over the mask gives first True index; safe because depleted=True ensures one exists
            first_zero = np.where(depleted, zero_mask.argmax(axis=1), -1)
            valid = first_zero[first_zero > 0]
            return float(np.median(valid)) if len(valid) else None

        # Build KPI strip with 4 or 5 cols depending on whether withdrawals are on
        if apply_withdrawals:
            survival = float((final > 1e-6).mean()) * 100.0
            dep_year = _depletion_year(total_paths)
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Median (P50)",        fmt_usd(float(np.percentile(final, 50))))
            k2.metric("Worst quartile (P25)", fmt_usd(float(np.percentile(final, 25))))
            k3.metric("Best quartile (P75)",  fmt_usd(float(np.percentile(final, 75))))
            k4.metric(f"Survival @ {primary_swr_pct:.1f}%", f"{survival:.1f}%",
                      help="Share of paths still > $0 at the horizon.")
            k5.metric(
                "Median depletion year",
                f"Year {int(dep_year)}" if dep_year is not None else "—",
                help="Median first-zero year across paths that ran out. — = no path depleted.",
            )
        else:
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Median (P50)",        fmt_usd(float(np.percentile(final, 50))))
            k2.metric("Worst quartile (P25)", fmt_usd(float(np.percentile(final, 25))))
            k3.metric("Best quartile (P75)",  fmt_usd(float(np.percentile(final, 75))))
            if goal > 0:
                prob = float((final >= goal).mean()) * 100.0
                k4.metric("P(reach goal)", f"{prob:.1f}%")
            else:
                k4.metric("Expected (mean)", fmt_usd(float(final.mean())))

        # ── Milestone percentile table (combined) ───────────────────────────
        if milestone_years:
            st.markdown("**Combined percentiles at milestones**")
            rows = []
            for pct in pcts:
                row = {"Percentile": f"P{pct}", "Today": fmt_usd(float(p_curves[pct][0]))}
                for yr in milestone_years:
                    row[f"Year {yr}"] = fmt_usd(float(p_curves[pct][yr]))
                rows.append(row)
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # ── SWR comparison table (when extra rates requested) ───────────────
        if apply_withdrawals and compare_swrs:
            st.markdown("**Survival across withdrawal rates**")
            st.caption(
                "Same return paths (identical RNG seed), only the withdrawal rate "
                "changes. Find the highest SWR that still meets your target "
                f"success threshold over {horizon} years."
            )
            rows = []
            # Always include the primary rate; dedupe with compare list.
            swr_list = sorted({primary_swr_pct, *compare_swrs})
            for swr in swr_list:
                if swr == primary_swr_pct:
                    tp_for_swr = total_paths
                else:
                    _, tp_for_swr = _simulate(swr)
                final_swr = tp_for_swr[:, -1]
                survival = float((final_swr > 1e-6).mean()) * 100.0
                dep_year = _depletion_year(tp_for_swr)
                rows.append({
                    "Withdrawal rate":   f"{swr:.2f}%",
                    "Survival @ horizon": f"{survival:.1f}%",
                    "Median terminal":   fmt_usd(float(np.percentile(final_swr, 50))),
                    "P10 terminal":      fmt_usd(float(np.percentile(final_swr, 10))),
                    "P90 terminal":      fmt_usd(float(np.percentile(final_swr, 90))),
                    "Median depletion year": f"Year {int(dep_year)}" if dep_year is not None else "—",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # ── Per-portfolio summary at horizon end ─────────────────────────────
        if len(portfolios_by_name) > 1:
            st.markdown(f"**Per-portfolio outcome at year {horizon}**")
            rows = []
            for pname, paths in paths_by_portfolio.items():
                final_p = paths[:, -1]
                rows.append({
                    "Portfolio": pname,
                    "Today":     fmt_usd(float(paths[0, 0])),
                    "P10":       fmt_usd(float(np.percentile(final_p, 10))),
                    "P25":       fmt_usd(float(np.percentile(final_p, 25))),
                    "P50":       fmt_usd(float(np.percentile(final_p, 50))),
                    "P75":       fmt_usd(float(np.percentile(final_p, 75))),
                    "P90":       fmt_usd(float(np.percentile(final_p, 90))),
                })
            rows.append({
                "Portfolio": "TOTAL",
                "Today":     fmt_usd(float(total_paths[0, 0])),
                "P10":       fmt_usd(float(np.percentile(final, 10))),
                "P25":       fmt_usd(float(np.percentile(final, 25))),
                "P50":       fmt_usd(float(np.percentile(final, 50))),
                "P75":       fmt_usd(float(np.percentile(final, 75))),
                "P90":       fmt_usd(float(np.percentile(final, 90))),
            })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Agent Chat ───────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🤖 Ask the Agents")
    st.caption(
        "Chat with Claude-powered agents that can call the same tools you have "
        "in the CLI. Each tab keeps its own conversation history."
    )

    def _render_agent_chat(agent_key: str, agent_cls, label: str):
        # Scope the agent instance to the active data dir so the demo-mode
        # toggle gives each mode its own agent + history.
        from src import agent_summaries
        active_dir = _active_data_dir()
        state_key = f"agent_{agent_key}_{active_dir}"
        msgs_key  = f"agent_{agent_key}_{active_dir}_msgs"

        if msgs_key not in st.session_state:
            st.session_state[msgs_key] = []

        # ── Load past summaries as context (any agent's past convo can prime any agent) ──
        existing_summaries = agent_summaries.list_summaries(data_dir=active_dir)
        if existing_summaries:
            with st.expander(
                f"📂 Load past conversation context ({len(existing_summaries)} saved)",
                expanded=False,
            ):
                opt_map = {
                    s["key"]: (
                        f"[{s['agent']}] {s['started_at']}  ·  "
                        f"{s['message_count']} msgs  ·  "
                        f"{(s.get('summary') or '')[:80].strip()}…"
                    )
                    for s in existing_summaries
                }
                picked_keys = st.multiselect(
                    "Pick conversations to prime this chat with",
                    options=list(opt_map.keys()),
                    format_func=lambda k: opt_map[k],
                    key=f"load_ctx_{agent_key}_{active_dir}",
                )
                if st.button(
                    "Load context",
                    key=f"load_ctx_btn_{agent_key}_{active_dir}",
                    disabled=not picked_keys,
                ):
                    selected = [agent_summaries.get_summary(k, data_dir=active_dir)
                                for k in picked_keys]
                    selected = [s for s in selected if s]
                    primer = agent_summaries.build_context_prompt(selected)
                    # Lazy-init agent for the priming round-trip
                    if state_key not in st.session_state:
                        try:
                            st.session_state[state_key] = agent_cls(data_dir=active_dir)
                        except Exception as exc:
                            st.error(
                                f"Could not start the {label} agent: {exc}. "
                                "Make sure `ANTHROPIC_API_KEY` is set."
                            )
                            return
                    label_text = (
                        f"_📂 Loaded context from {len(selected)} past "
                        f"conversation(s): {', '.join(s['key'] for s in selected)}_"
                    )
                    st.session_state[msgs_key].append({"role": "user", "content": label_text})
                    with st.spinner(f"Priming {label} agent with past context…"):
                        try:
                            ack = st.session_state[state_key].chat(primer)
                        except Exception as exc:
                            ack = f"⚠️ Agent error while loading context: {exc}"
                    st.session_state[msgs_key].append({"role": "assistant", "content": ack})
                    st.rerun()

        for msg in st.session_state[msgs_key]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        prompt = st.chat_input(
            f"Ask the {label} agent…", key=f"input_{agent_key}",
        )

        # Action buttons row: Clear + Save summary
        col_clear, col_save = st.columns(2)
        with col_clear:
            if st.button("Clear conversation", key=f"clear_{agent_key}"):
                st.session_state.pop(state_key, None)
                st.session_state[msgs_key] = []
                st.rerun()
        with col_save:
            can_save = bool(st.session_state[msgs_key])
            if st.button(
                "💾 Save summary", key=f"save_summary_{agent_key}_{active_dir}",
                disabled=not can_save,
                help="Compress this conversation via Claude Haiku and store it "
                     "in agent_summaries.json so you can reload it later.",
            ):
                try:
                    with st.spinner("Summarising conversation…"):
                        # Use the agent's Anthropic client when available to
                        # avoid double-instantiating Anthropic().
                        client = (
                            st.session_state[state_key].client
                            if state_key in st.session_state else None
                        )
                        key, entry = agent_summaries.save_summary(
                            agent=agent_key,
                            messages=st.session_state[msgs_key],
                            client=client,
                            data_dir=active_dir,
                        )
                    st.success(f"Saved as `{key}`")
                    with st.expander("Summary preview", expanded=True):
                        st.markdown(entry["summary"])
                except Exception as exc:
                    st.error(f"Could not save summary: {exc}")

        if prompt:
            # Lazy-init the agent only when the user actually sends a message,
            # so a missing ANTHROPIC_API_KEY doesn't break the whole dashboard.
            if state_key not in st.session_state:
                try:
                    st.session_state[state_key] = agent_cls(data_dir=active_dir)
                except Exception as exc:
                    with st.chat_message("assistant"):
                        st.error(
                            f"Could not start the {label} agent: {exc}.\n\n"
                            "Make sure `ANTHROPIC_API_KEY` is set in your environment."
                        )
                    return

            st.session_state[msgs_key].append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner(f"{label} agent thinking…"):
                    try:
                        reply = st.session_state[state_key].chat(prompt)
                    except Exception as exc:
                        reply = f"⚠️ Agent error: {exc}"
                st.markdown(reply)

            st.session_state[msgs_key].append({"role": "assistant", "content": reply})

    (
        tab_risk_chat,
        tab_wealth_chat,
        tab_research_chat,
        tab_pm_chat,
        tab_cio_chat,
    ) = st.tabs([
        "⚠️ Risk", "💰 Wealth", "🔬 Research", "💼 PM", "🎩 CIO",
    ])
    with tab_risk_chat:
        _render_agent_chat("risk", RiskAgent, "Risk")
    with tab_wealth_chat:
        _render_agent_chat("wealth", WealthAgent, "Wealth")
    with tab_research_chat:
        _render_agent_chat("research", ResearchAgent, "Research")
    with tab_pm_chat:
        _render_agent_chat("pm", PortfolioManagerAgent, "PM")
    with tab_cio_chat:
        _render_agent_chat("cio", CIOAgent, "CIO")

    st.stop()

# ── Production view ───────────────────────────────────────────────────────────

if view == "⚙️ Production":
    from src.production import JobRunner, JOB_REGISTRY
    st.title("⚙️ Analytics Production")
    st.caption(
        "Scheduled jobs that keep the analytics fresh: price collection, "
        "attribution refresh, sector beta rebuild, and fund-profile updates. "
        "Run them ad-hoc from this view, or wire `invest-monitor production run` "
        "into cron / systemd for true automation."
    )

    _prod_db = get_db()
    _runner = JobRunner(_prod_db)
    jobs_df = _prod_db.get_production_jobs()
    now = pd.Timestamp.now()
    if not jobs_df.empty:
        jobs_df = jobs_df.sort_values("job_name").reset_index(drop=True)

    # ── KPI strip ─────────────────────────────────────────────────────────────
    n_jobs   = len(jobs_df)
    n_failed = int((jobs_df["last_status"] == "error").sum()) if n_jobs else 0
    n_due    = sum(_runner.is_due(r, now=now) for _, r in jobs_df.iterrows()) if n_jobs else 0

    k1, k2, k3 = st.columns(3)
    k1.metric("Jobs",            n_jobs)
    k2.metric("Failed (last)",   n_failed)
    k3.metric("Due now",         n_due)

    if n_failed:
        st.error(f"⚠️ {n_failed} job(s) failed in their last run. See the **🚨 Issues** tab below.")

    st.markdown("---")

    # ── Run controls ──────────────────────────────────────────────────────────
    col_a, col_b = st.columns([1, 3])
    with col_a:
        if st.button("Run all due now", type="primary", key="prod_run_due_btn"):
            with st.spinner("Running due jobs…"):
                results = _runner.run_due_jobs()
            if not results:
                st.info("No jobs were due.")
            else:
                for r in results:
                    icon = "✅" if r["status"] == "success" else "❌" if r["status"] == "error" else "⏭️"
                    st.write(f"{icon} **{r['job_name']}** — {r['status']} "
                             f"({r.get('duration_seconds', 0):.1f}s)"
                             + (f"  \n`{r.get('error', '')}`" if r['status'] == 'error' else ""))
            st.rerun()
    with col_b:
        st.caption(
            "“Run all due now” executes any job whose interval has elapsed since its last run. "
            "Use the **Run** button next to each row below to force-run a specific job."
        )

    # ── Jobs table with per-row actions ───────────────────────────────────────
    st.subheader("Jobs")
    if jobs_df.empty:
        st.info("No jobs registered. (Should auto-seed on first load.)")
    else:
        for _, r in jobs_df.iterrows():
            jname = r["job_name"]
            desc  = JOB_REGISTRY.get(jname, {}).get("description", "")
            interval_h = round(int(r["interval_minutes"]) / 60, 1) if r["interval_minutes"] else 0
            last_run = r["last_run_at"]
            last_run_str = last_run.strftime("%Y-%m-%d %H:%M") if pd.notna(last_run) else "—"
            status_icon = {
                "success":   "✅", "error":     "❌",
                "never_run": "⏸️",  "running":   "⏳",
            }.get(r["last_status"], "❔")
            due_icon = "🔔" if _runner.is_due(r, now=now) else "  "

            with st.container(border=True):
                row_cols = st.columns([3, 2, 2, 2, 1, 1])
                with row_cols[0]:
                    st.markdown(f"**{jname}**  {due_icon}")
                    st.caption(desc)
                with row_cols[1]:
                    st.caption("Interval")
                    st.markdown(f"`{interval_h} h`")
                with row_cols[2]:
                    st.caption("Last run")
                    st.markdown(last_run_str)
                with row_cols[3]:
                    st.caption("Status")
                    st.markdown(f"{status_icon} {r['last_status'] or '—'}")
                with row_cols[4]:
                    enabled = st.toggle(
                        "On", value=bool(r["enabled"]),
                        key=f"prod_enabled_{jname}",
                        label_visibility="collapsed",
                    )
                    if enabled != bool(r["enabled"]):
                        _prod_db.upsert_production_job(jname, enabled=enabled)
                        st.rerun()
                with row_cols[5]:
                    if st.button("Run", key=f"prod_run_{jname}"):
                        with st.spinner(f"Running {jname}…"):
                            result = _runner.run_job(jname, force=True)
                        if result["status"] == "success":
                            st.toast(f"✅ {jname} succeeded ({result.get('duration_seconds', 0):.1f}s)")
                        elif result["status"] == "error":
                            st.toast(f"❌ {jname} failed: {result.get('error')}", icon="🚨")
                        st.rerun()
                if r["last_status"] == "error" and r["last_error"]:
                    st.error(f"`{r['last_error']}`")

    # ── systemd scheduling ────────────────────────────────────────────────────
    from src import scheduler as _sched
    st.markdown("---")
    st.subheader("📅 Schedule with systemd")
    if not _sched.is_systemd_available():
        st.info(
            "`systemctl --user` is not available on this system "
            "(non-Linux, or no user systemd session). To automate jobs, run "
            "`invest-monitor production run` from cron or any other scheduler."
        )
    else:
        sched_dir = _sched.systemd_user_dir()
        st.caption(
            f"User-level timers are written to `{sched_dir}`. Each job gets a "
            f"`.service` (one-shot `invest-monitor production run-now <job>`) and "
            f"a `.timer` that fires every `interval_minutes`."
        )

        sched_states = _sched.list_scheduled()
        for _, r in jobs_df.iterrows():
            jname    = r["job_name"]
            interval = int(r["interval_minutes"]) if r["interval_minutes"] else 1440
            state    = sched_states.get(jname, {})
            installed = state.get("installed", False)
            active    = state.get("active", False)
            enabled   = state.get("enabled", False)
            next_run  = state.get("next_run") or "—"

            if installed and active and enabled:
                badge = "✅ Active"
            elif installed:
                badge = f"⚠️ Installed ({state.get('active_raw', '?')}/{state.get('enabled_raw', '?')})"
            else:
                badge = "⏸️ Not installed"

            with st.container(border=True):
                cols = st.columns([2, 2, 2, 1])
                cols[0].markdown(f"**{jname}**  \n_{badge}_")
                cols[1].caption("Interval")
                cols[1].markdown(f"`{interval} min` (≈ {round(interval / 60, 1)} h)")
                cols[2].caption("Next run")
                cols[2].markdown(f"`{next_run}`")
                with cols[3]:
                    if installed:
                        if st.button("Uninstall", key=f"sched_uninstall_{jname}"):
                            res = _sched.uninstall(jname)
                            (st.success if res["ok"] else st.error)(res["detail"])
                            st.rerun()
                    else:
                        if st.button("Install", key=f"sched_install_{jname}", type="primary"):
                            res = _sched.install(jname, interval)
                            (st.success if res["ok"] else st.error)(res["detail"])
                            st.rerun()

                with st.expander("Preview unit files", expanded=False):
                    st.caption(f"`{_sched.UNIT_PREFIX}{jname}.service`")
                    st.code(_sched.service_unit(jname), language="ini")
                    st.caption(f"`{_sched.UNIT_PREFIX}{jname}.timer`")
                    st.code(_sched.timer_unit(jname, interval), language="ini")

    # ── Run log + Issues tabs ─────────────────────────────────────────────────
    st.markdown("---")
    tab_recent, tab_issues = st.tabs(["📜 Recent Runs", "🚨 Issues"])
    runs_df = _prod_db.get_production_runs(limit=200)

    def _fmt_runs(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        out = df.copy()
        out["started_at"] = out["started_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
        out["ended_at"]   = out["ended_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
        if "duration_seconds" in out.columns:
            out["duration_seconds"] = out["duration_seconds"].round(2)
        # Truncate the details column so the table stays readable.
        if "details" in out.columns:
            out["details"] = out["details"].fillna("").astype(str).str.slice(0, 200)
        if "error_message" in out.columns:
            out["error_message"] = out["error_message"].fillna("").astype(str).str.slice(0, 300)
        cols = ["started_at", "job_name", "status", "duration_seconds",
                "error_message", "ended_at", "details", "run_id"]
        cols = [c for c in cols if c in out.columns]
        return out[cols]

    with tab_recent:
        if runs_df.empty:
            st.info("No runs recorded yet. Click **Run all due now** above to get started.")
        else:
            st.dataframe(_fmt_runs(runs_df), use_container_width=True, hide_index=True)

    with tab_issues:
        errors_df = runs_df[runs_df["status"] == "error"] if not runs_df.empty else runs_df
        if errors_df.empty:
            st.success("✅ No errors recorded.")
        else:
            st.warning(f"{len(errors_df)} failed run(s) in the last {len(runs_df)} logged.")
            st.dataframe(_fmt_runs(errors_df), use_container_width=True, hide_index=True)

    st.stop()


# ── Guard ─────────────────────────────────────────────────────────────────────

if "portfolio" not in st.session_state:
    st.title("Invest Monitor")
    st.info("Upload a portfolio CSV in the sidebar to get started.")
    with st.expander("Expected CSV format"):
        st.markdown("""
| Ticker | Name | Type | Quantity | CostBasis | Currency | Sector |
|--------|------|------|----------|-----------|----------|--------|
| AAPL | Apple Inc. | STOCK | 10 | 150.00 | USD | Technology |
| BND | Vanguard Bond ETF | ETF | 50 | 78.50 | USD | Fixed Income |
""")
    st.stop()

portfolio: Portfolio = st.session_state["portfolio"]
tickers = [pos.asset.ticker for pos in portfolio.positions]
reporting = get_reporting()

(tab_overview, tab_prices, tab_exposure, tab_risk, tab_income,
 tab_positions, tab_security, tab_trades, tab_lookthrough) = st.tabs([
    "📊 Overview", "📈 Price History", "🥧 Exposure", "⚠️ Risk", "💵 Income",
    "✏️ Positions", "🏢 Security Master", "📋 Trades", "🔍 Lookthrough",
])

# ── Overview ──────────────────────────────────────────────────────────────────

with tab_overview:
    st.header(portfolio.name)

    cur_prices = latest_prices(tickers)

    # ── Quick-edit group memberships ───────────────────────────────────────────
    _ov_db = get_db()
    _ov_all_groups = _ov_db.list_groups()
    if _ov_all_groups:
        _ov_current = _ov_db.get_groups_for_portfolio(portfolio.name)
        col_g, col_save = st.columns([5, 1])
        with col_g:
            _ov_picked = st.multiselect(
                "🏷 Groups",
                options=_ov_all_groups,
                default=_ov_current,
                key=f"overview_groups_{portfolio.name}",
                help=(
                    "Tag this portfolio with one or more groups. The "
                    "Multi-Portfolio Dashboard's Group filter then scopes every "
                    "section to a group, and the **View as combined portfolio** "
                    "toggle merges the group's members into one synthetic entity."
                ),
            )
        with col_save:
            st.write("")  # vertical alignment with the multiselect
            if set(_ov_picked) != set(_ov_current):
                if st.button("Save groups", key="overview_save_groups", type="primary"):
                    _ov_db.set_groups_for_portfolio(portfolio.name, _ov_picked)
                    st.success(
                        f"Groups for **{portfolio.name}**: "
                        f"{', '.join(_ov_picked) if _ov_picked else '— none —'}"
                    )
                    st.rerun()
    else:
        st.caption(
            "💡 No portfolio groups yet — create one in the sidebar's "
            "**🏷 Portfolio Groups** expander to start grouping accounts."
        )

    if not portfolio.positions:
        st.info("No positions yet. Add some via the **📋 Trades** tab.")
    else:
        # Detect which positions can actually be looked through. A fund counts
        # as lookthroughable if EITHER vendor holdings OR a yfinance fund_profile
        # is available; the helper falls back from one to the other automatically.
        _db = get_db()
        vendor_funds: list[str] = []
        yfinance_funds: list[str] = []
        for pos in portfolio.positions:
            if pos.asset.asset_type.value not in ("ETF", "Fund"):
                continue
            t = pos.asset.ticker
            if not _db.get_fund_holdings(t).empty:
                vendor_funds.append(t)
                continue
            prof = _db.get_fund_profile(t)
            if (prof.get("asset_classes") or {}) or (prof.get("sector_weightings") or {}):
                yfinance_funds.append(t)

        if vendor_funds or yfinance_funds:
            lookthrough = st.toggle(
                "🔍 Apply ETF / Fund lookthrough",
                value=False, key="overview_lookthrough_toggle",
                help=(
                    "When on, ETF/Fund positions are replaced by their constituents.\n\n"
                    f"• **Vendor holdings** (ticker-level): "
                    f"{', '.join(vendor_funds) if vendor_funds else '—'}\n"
                    f"• **yfinance profile fallback** (sector-level): "
                    f"{', '.join(yfinance_funds) if yfinance_funds else '—'}"
                ),
            )
        else:
            lookthrough = False
            st.caption(
                "💡 No ETF/Fund holdings or profiles loaded for this portfolio yet — "
                "upload a vendor CSV or click **Fetch Profile from yfinance** in the "
                "**🔍 Lookthrough** tab to enable lookthrough."
            )

        rows = expand_lookthrough_rows(portfolio, _db, cur_prices, enabled=lookthrough)
        df = pd.DataFrame(rows)

        total_cost  = df["Total Cost"].sum()
        total_value = df["Current Value"].sum() if df["Current Value"].notna().any() else None
        total_pnl   = (total_value - total_cost) if total_value is not None else None
        total_pnl_pct = (total_pnl / total_cost * 100) if (total_pnl is not None and total_cost) else None

        c1, c2, c3, c4 = st.columns(4)
        if lookthrough:
            n_native    = int((~df["_synthetic"]).sum())
            n_synth     = int(df["_synthetic"].sum())
            c1.metric("Positions", f"{len(df)}", delta=f"{n_native} native + {n_synth} looked-through")
        else:
            c1.metric("Positions", len(portfolio.positions))
        c2.metric("Total Cost",    fmt_usd(total_cost))
        c3.metric("Current Value", fmt_usd(total_value))
        if total_pnl is not None:
            c4.metric("Total P&L",  fmt_usd(total_pnl), delta=fmt_pct(total_pnl_pct))

        st.markdown("---")

        display = df.copy()
        for col in ("Cost Basis", "Total Cost", "Current Price", "Current Value", "P&L"):
            if col in display.columns:
                display[col] = display[col].map(fmt_usd)
        if "P&L %" in display.columns:
            display["P&L %"] = display["P&L %"].map(fmt_pct)
        if not lookthrough:
            display = display.drop(columns=["Via", "_synthetic"], errors="ignore")
        else:
            display = display.drop(columns=["_synthetic"], errors="ignore")
        st.dataframe(display, use_container_width=True, hide_index=True)

        # Allocation donut — uses the same (possibly disaggregated) rows.
        type_df = (
            df.groupby("Type")["Total Cost"]
            .sum().reset_index()
            .sort_values("Total Cost", ascending=False)
        )
        title_suffix = " — with lookthrough" if lookthrough else ""
        fig = px.pie(
            type_df, names="Type", values="Total Cost",
            title=f"Allocation by Asset Type (cost basis){title_suffix}",
            hole=0.45,
        )
        fig.update_traces(textposition="inside", textinfo="percent+label")
        st.plotly_chart(fig, use_container_width=True)

# ── Price History ─────────────────────────────────────────────────────────────

with tab_prices:
    st.header("Price History")

    prices_df = fetch_prices(tuple(tickers))

    if prices_df.empty:
        st.warning("No price data found. Use **Collect Prices** in the sidebar first.")
    else:
        col_left, col_right = st.columns([3, 1])
        with col_left:
            selected = st.multiselect("Tickers", options=prices_df.columns.tolist(),
                                      default=prices_df.columns.tolist())
        with col_right:
            normalize = st.checkbox("Normalize to 100", value=True)

        if selected:
            plot_df = prices_df[selected].dropna(how="all")
            if normalize:
                plot_df = plot_df.div(plot_df.iloc[0]) * 100

            fig = go.Figure()
            for col in plot_df.columns:
                fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df[col], name=col, mode="lines"))
            fig.update_layout(
                title="Price History" + (" (normalized, base=100)" if normalize else ""),
                xaxis_title="Date",
                yaxis_title="Index" if normalize else "Price",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig, use_container_width=True)

            # Cumulative returns
            st.subheader("Cumulative Return")
            cum_df = reporting.calculate_cumulative_returns(selected)
            if not cum_df.empty:
                fig2 = go.Figure()
                for col in cum_df.columns:
                    fig2.add_trace(go.Scatter(x=cum_df.index, y=cum_df[col], name=col, mode="lines"))
                fig2.update_layout(
                    xaxis_title="Date",
                    yaxis_title="Cumulative Return",
                    yaxis_tickformat=".1%",
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                )
                st.plotly_chart(fig2, use_container_width=True)

            # Daily returns
            st.subheader("Daily Returns")
            ret_df = prices_df[selected].pct_change().dropna()
            fig3 = go.Figure()
            for col in ret_df.columns:
                fig3.add_trace(go.Bar(x=ret_df.index, y=ret_df[col], name=col))
            fig3.update_layout(
                barmode="overlay",
                xaxis_title="Date",
                yaxis_title="Daily Return",
                yaxis_tickformat=".1%",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig3, use_container_width=True)

# ── Exposure ──────────────────────────────────────────────────────────────────

with tab_exposure:
    st.header("Portfolio Exposure")
    db = get_db()

    if not portfolio.positions:
        st.info("No positions yet. Add some via the **📋 Trades** tab.")
    else:
        # Categorise funds by which lookthrough source they have.
        vendor_funds: list[str] = []
        yfinance_funds: list[str] = []
        for pos in portfolio.positions:
            if pos.asset.asset_type.value not in ("ETF", "Fund"):
                continue
            t = pos.asset.ticker
            if not db.get_fund_holdings(t).empty:
                vendor_funds.append(t)
                continue
            prof = db.get_fund_profile(t)
            if (prof.get("asset_classes") or {}) or (prof.get("sector_weightings") or {}):
                yfinance_funds.append(t)

        if vendor_funds or yfinance_funds:
            lookthrough = st.toggle(
                "🔍 Apply ETF / Fund lookthrough",
                value=True, key="exposure_lookthrough_toggle",
                help=(
                    "When on, ETF/Fund positions are replaced by their constituents.\n\n"
                    f"• **Vendor holdings** (ticker-level): "
                    f"{', '.join(vendor_funds) if vendor_funds else '—'}\n"
                    f"• **yfinance profile fallback** (sector-level): "
                    f"{', '.join(yfinance_funds) if yfinance_funds else '—'}\n\n"
                    "Upload vendor holdings or click **Fetch Profile from yfinance** "
                    "in the **🔍 Lookthrough** tab to widen coverage."
                ),
            )
        else:
            lookthrough = False
            st.caption(
                "💡 No ETF/Fund holdings or profiles loaded yet — upload a vendor CSV "
                "or click **Fetch Profile from yfinance** in the **🔍 Lookthrough** tab "
                "to enable lookthrough."
            )

        try:
            # Use the shared lookthrough helper (handles vendor → yfinance →
            # native fallback automatically) and groupby (Type, Sector) for
            # the Exposure breakdown.
            exp_rows = expand_lookthrough_rows(
                portfolio, db, cur_prices or {}, enabled=lookthrough,
            )
            exp_df_raw = pd.DataFrame(exp_rows)
            if not exp_df_raw.empty:
                exposure_df = (
                    exp_df_raw.groupby(["Type", "Sector"])["Current Value"]
                    .sum().reset_index().rename(columns={"Current Value": "Value"})
                )
            else:
                exposure_df = pd.DataFrame(columns=["Type", "Sector", "Value"])

            total_exp = exposure_df["Value"].sum()
            exposure_df["Weight %"] = exposure_df["Value"] / total_exp * 100

            col1, col2 = st.columns(2)

            with col1:
                type_exp = exposure_df.groupby("Type")["Value"].sum().reset_index()
                fig = px.pie(type_exp, names="Type", values="Value",
                             title="By Asset Type", hole=0.4)
                fig.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig, use_container_width=True)

            with col2:
                sector_exp = exposure_df.groupby("Sector")["Value"].sum().reset_index().sort_values("Value", ascending=True)
                fig2 = px.bar(sector_exp, x="Value", y="Sector", orientation="h",
                              title="By Sector", labels={"Value": "Value (USD)"})
                fig2.update_layout(yaxis_title="", xaxis_tickformat="$,.0f")
                st.plotly_chart(fig2, use_container_width=True)

            st.subheader("Exposure Table")
            disp = exposure_df.copy()
            disp["Value"] = disp["Value"].map(lambda x: f"${x:,.0f}")
            disp["Weight %"] = disp["Weight %"].map(lambda x: f"{x:.1f}%")
            st.dataframe(disp, use_container_width=True, hide_index=True)

        except Exception as e:
            st.error(f"Could not compute exposure: {e}")

# ── Risk ──────────────────────────────────────────────────────────────────────

with tab_risk:
    st.header("Risk Metrics")

    if not portfolio.positions:
        st.info("No positions yet. Add some via the **📋 Trades** tab.")
        prices_df_risk = pd.DataFrame()
    else:
        prices_df_risk = fetch_prices(tuple(tickers))

    if portfolio.positions and prices_df_risk.empty:
        st.warning("No price data found. Use **Collect Prices** in the sidebar first.")
    elif portfolio.positions and not prices_df_risk.empty:
        try:
            metrics = reporting.get_portfolio_risk_metrics(portfolio)
            cov_matrix: pd.DataFrame = metrics.pop("Covariance Matrix")

            m1, m2, m3 = st.columns(3)
            m1.metric("Annualised Volatility", fmt_pct(metrics["Volatility"] * 100))
            m2.metric("Historical VaR (95%, 1d)", fmt_pct(metrics["Historical VaR (95%)"] * 100))
            m3.metric("Monte Carlo VaR (95%, 1d)", fmt_pct(metrics["Monte Carlo VaR (95%)"] * 100))

            st.markdown("---")

            col_left, col_right = st.columns(2)

            # Correlation heatmap
            with col_left:
                st.subheader("Correlation Matrix")
                returns = reporting.calculate_returns(tickers)
                corr = returns.corr()
                fig_corr = go.Figure(go.Heatmap(
                    z=corr.values,
                    x=corr.columns.tolist(),
                    y=corr.index.tolist(),
                    colorscale="RdBu",
                    zmid=0,
                    text=corr.round(2).values,
                    texttemplate="%{text}",
                ))
                fig_corr.update_layout(title="Asset Correlation")
                st.plotly_chart(fig_corr, use_container_width=True)

            # Portfolio return distribution
            with col_right:
                st.subheader("Portfolio Return Distribution")
                weights = np.array([p.quantity * p.cost_basis for p in portfolio.positions])
                weights /= weights.sum()
                port_returns = reporting.calculate_returns(tickers).dot(weights)

                hist_var = metrics["Historical VaR (95%)"]
                fig_dist = go.Figure()
                fig_dist.add_trace(go.Histogram(
                    x=port_returns,
                    nbinsx=60,
                    name="Returns",
                    marker_color="steelblue",
                    opacity=0.75,
                ))
                fig_dist.add_vline(
                    x=hist_var,
                    line_dash="dash",
                    line_color="red",
                    annotation_text=f"VaR {hist_var:.2%}",
                    annotation_position="top right",
                )
                fig_dist.update_layout(
                    xaxis_title="Daily Return",
                    xaxis_tickformat=".1%",
                    yaxis_title="Frequency",
                    showlegend=False,
                )
                st.plotly_chart(fig_dist, use_container_width=True)

            # Covariance matrix
            st.subheader("Annualised Covariance Matrix")
            fig_cov = go.Figure(go.Heatmap(
                z=cov_matrix.values,
                x=cov_matrix.columns.tolist(),
                y=cov_matrix.index.tolist(),
                colorscale="Blues",
                text=cov_matrix.round(4).values,
                texttemplate="%{text}",
                colorbar=dict(title="Cov"),
            ))
            st.plotly_chart(fig_cov, use_container_width=True)

        except Exception as e:
            st.error(f"Could not compute risk metrics: {e}")

    # ── Sector Stress Test ────────────────────────────────────────────────────
    if portfolio.positions:
        from src.scenarios import (
            SECTOR_KEYS, SECTOR_DISPLAY,
            SECTOR_STRESS_SCENARIOS, NON_EQUITY_SHOCKS,
        )

        st.markdown("---")
        st.subheader("Sector Stress Test")
        st.caption(
            "Apply per-sector one-day shocks. Stock positions use their stored sector. "
            "ETF / Fund positions are decomposed via the `sector_weightings` profile "
            "fetched from yfinance in the **🔍 Lookthrough** tab — pick the position, "
            "then click **Fetch Profile from yfinance**."
        )

        IMPLIED_OPT = "Implied (beta from driver sector)"
        scenario_name = st.selectbox(
            "Scenario",
            ["Custom", IMPLIED_OPT] + list(SECTOR_STRESS_SCENARIOS.keys()),
            key="stress_scenario_select",
        )
        if scenario_name == "Custom":
            base_sector = {k: 0.0 for k in SECTOR_KEYS}
            base_other  = {"Bond": 0.0, "Crypto": 0.0, "Cash": 0.0, "CD": 0.0}
        elif scenario_name == IMPLIED_OPT:
            base_other = {"Bond": 0.0, "Crypto": 0.0, "Cash": 0.0, "CD": 0.0}

            betas_df = get_db().get_sector_betas()
            beta_dates = get_db().list_sector_beta_dates()

            col_drv, col_sh, col_re = st.columns([2, 1, 1])
            with col_drv:
                driver = st.selectbox(
                    "Driver sector",
                    SECTOR_KEYS,
                    format_func=lambda k: SECTOR_DISPLAY[k],
                    key="implied_driver",
                )
            with col_sh:
                driver_shock_pct = st.number_input(
                    "Shock %", value=-20.0, step=1.0,
                    min_value=-99.0, max_value=200.0,
                    key="implied_shock_pct",
                )
            with col_re:
                st.write("")  # vertical alignment with the inputs above
                if st.button("Refresh betas", key="refresh_sector_betas_btn"):
                    try:
                        with st.spinner("Fetching 20y of SPDR sector ETFs from yfinance…"):
                            new_betas = Collector.fetch_sector_betas(years=20)
                            get_db().save_sector_betas(new_betas)
                        st.success(f"Computed {len(new_betas)} pairwise betas (20y window).")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not refresh betas: {exc}")

            if betas_df.empty:
                st.warning(
                    "No sector betas saved yet. Click **Refresh betas** to fetch "
                    "SPDR sector ETF prices and compute the matrix."
                )
                base_sector = {k: 0.0 for k in SECTOR_KEYS}
            else:
                st.caption(
                    f"Betas as of **{beta_dates[0]}** "
                    f"({int(betas_df['sector_a'].nunique())} × "
                    f"{int(betas_df['sector_b'].nunique())} pairs). "
                    f"Implied shock for sector S = β(S, {SECTOR_DISPLAY[driver]}) × "
                    f"{driver_shock_pct:+.1f}%."
                )
                driver_shock = driver_shock_pct / 100.0
                base_sector = {}
                beta_lookup = betas_df.set_index(["sector_a", "sector_b"])["beta"].to_dict()
                for sec in SECTOR_KEYS:
                    beta = float(beta_lookup.get((sec, driver), 0.0))
                    base_sector[sec] = beta * driver_shock

                with st.expander("Implied shocks (read-only preview)", expanded=False):
                    preview = pd.DataFrame([
                        {
                            "Sector": SECTOR_DISPLAY[sec],
                            "β vs driver": f"{beta_lookup.get((sec, driver), 0.0):+.3f}",
                            "Implied shock": f"{base_sector[sec] * 100:+.2f}%",
                        }
                        for sec in SECTOR_KEYS
                    ])
                    st.dataframe(preview, use_container_width=True, hide_index=True)
        else:
            base_sector = SECTOR_STRESS_SCENARIOS[scenario_name]
            base_other  = NON_EQUITY_SHOCKS.get(
                scenario_name, {"Bond": 0.0, "Crypto": 0.0, "Cash": 0.0, "CD": 0.0}
            )

        with st.expander("Edit shocks (%) — overrides reset when scenario changes", expanded=False):
            st.markdown("**By Sector**")
            sec_cols = st.columns(3)
            sector_shocks: dict[str, float] = {}
            for i, sk in enumerate(SECTOR_KEYS):
                with sec_cols[i % 3]:
                    sector_shocks[sk] = st.number_input(
                        SECTOR_DISPLAY[sk],
                        min_value=-99.0, max_value=200.0,
                        value=float(base_sector.get(sk, 0.0) * 100),
                        step=1.0, format="%.1f",
                        key=f"stress_sec_{scenario_name}_{sk}",
                    ) / 100.0

            st.markdown("**By Non-Equity Asset Type**")
            other_types = ["Bond", "Cash", "CD", "Crypto"]
            other_cols = st.columns(len(other_types))
            non_equity_shocks: dict[str, float] = {}
            for i, at in enumerate(other_types):
                with other_cols[i]:
                    non_equity_shocks[at] = st.number_input(
                        at,
                        min_value=-99.0, max_value=200.0,
                        value=float(base_other.get(at, 0.0) * 100),
                        step=1.0, format="%.1f",
                        key=f"stress_other_{scenario_name}_{at}",
                    ) / 100.0

        stress_df = reporting.compute_sector_stress(
            portfolio, sector_shocks, non_equity_shocks, latest_prices=cur_prices,
        )

        if not stress_df.empty:
            total_base = float(stress_df["Base Value"].sum())
            total_new  = float(stress_df["New Value"].sum())
            total_change = total_new - total_base
            total_pct = (total_change / total_base * 100) if total_base else 0.0

            s1, s2, s3 = st.columns(3)
            s1.metric("Base Value",     fmt_usd(total_base))
            s2.metric("Stressed Value", fmt_usd(total_new),
                      delta=fmt_pct(total_pct))
            s3.metric("Total Change",   fmt_usd(total_change))

            disp = stress_df.copy()
            disp["Base Value"] = disp["Base Value"].map(fmt_usd)
            disp["Shock %"]    = disp["Shock %"].map(lambda v: f"{v:+.2f}%")
            disp["New Value"]  = disp["New Value"].map(fmt_usd)
            disp["Change $"]   = disp["Change $"].map(fmt_usd)
            st.dataframe(disp, use_container_width=True, hide_index=True)

            fig_stress = px.bar(
                stress_df.sort_values("Change $"),
                x="Change $", y="Ticker", orientation="h",
                title="Stressed P&L by Position",
                color="Change $",
                color_continuous_scale="RdYlGn",
            )
            fig_stress.update_layout(xaxis_tickformat="$,.0f", yaxis_title="")
            st.plotly_chart(fig_stress, use_container_width=True)

# ── Income ───────────────────────────────────────────────────────────────────

with tab_income:
    st.header("Income Projection")
    st.caption(
        "Annual cash flow from coupons (Bond/CD), interest (Cash), and dividends "
        "(Stock/ETF/Fund). Driven by **Income Rate** in the Security Master."
    )

    if not portfolio.positions:
        st.info("No positions yet. Add some via the **📋 Trades** tab.")
    else:
        inc_df = reporting.compute_portfolio_income(portfolio, latest_prices=cur_prices)
        base_total   = float(inc_df["Base Value"].sum()) if not inc_df.empty else 0.0
        annual_total = float(inc_df["Annual Income"].sum()) if not inc_df.empty else 0.0
        yield_pct    = (annual_total / base_total * 100.0) if base_total else 0.0

        i1, i2, i3, i4 = st.columns(4)
        i1.metric("Annual Income",   fmt_usd(annual_total))
        i2.metric("Monthly Average", fmt_usd(annual_total / 12.0))
        i3.metric("Portfolio Yield", fmt_pct(yield_pct))
        i4.metric(
            "Income-Generating",
            f"{int((inc_df['Annual Income'] > 0).sum())} of {len(inc_df)} positions",
        )

        if annual_total <= 0:
            st.info(
                "No positions have a non-zero **Income Rate** yet. "
                "Set the rate in the **🏢 Security Master** tab "
                "(coupon for Bond/CD, yield for Cash, dividend rate for Stock/ETF/Fund)."
            )
        else:
            col_a, col_b = st.columns(2)

            with col_a:
                type_inc = inc_df.groupby("Type")["Annual Income"].sum().reset_index()
                type_inc = type_inc[type_inc["Annual Income"] > 0]
                if not type_inc.empty:
                    fig_inc = px.pie(
                        type_inc, names="Type", values="Annual Income",
                        title="Annual Income by Asset Type", hole=0.4,
                    )
                    fig_inc.update_traces(textposition="inside", textinfo="percent+label")
                    st.plotly_chart(fig_inc, use_container_width=True)

            with col_b:
                months = list(range(1, 13))
                schedule = {m: 0.0 for m in months}
                for _, r in inc_df.iterrows():
                    ann = float(r["Annual Income"])
                    if ann <= 0:
                        continue
                    freq = int(r["Payment Frequency"]) or 1
                    per_payment = ann / freq
                    step = max(1, 12 // freq)
                    for m in range(step, 13, step):
                        schedule[m] += per_payment
                sched_df = pd.DataFrame({
                    "Month":  [pd.Timestamp(2026, m, 1).strftime("%b") for m in months],
                    "Income": [schedule[m] for m in months],
                })
                fig_sched = px.bar(
                    sched_df, x="Month", y="Income",
                    title="Income by Calendar Month (next 12)",
                    labels={"Income": "Income (USD)"},
                )
                fig_sched.update_layout(yaxis_tickprefix="$", yaxis_tickformat=",.0f")
                st.plotly_chart(fig_sched, use_container_width=True)

            st.markdown("**Per-Position Detail**")
            contrib = inc_df[inc_df["Annual Income"] > 0].sort_values(
                "Annual Income", ascending=False,
            ).copy()
            contrib["Base Value"]        = contrib["Base Value"].map(fmt_usd)
            contrib["Income Rate"]       = contrib.apply(_fmt_income_rate, axis=1)
            contrib["Annual Income"]     = contrib["Annual Income"].map(fmt_usd)
            contrib["Monthly Income"]    = contrib["Monthly Income"].map(fmt_usd)
            contrib["Yield on Base (%)"] = contrib["Yield on Base (%)"].map(lambda v: f"{v:.2f}%")
            contrib = contrib.drop(columns=["Income Rate Unit"], errors="ignore")
            st.dataframe(contrib, use_container_width=True, hide_index=True)

# ── Positions Editor ──────────────────────────────────────────────────────────

with tab_positions:
    st.header("Edit Portfolio Positions")
    db = get_db()

    # Build editable dataframe from current positions
    pos_rows = []
    for pos in portfolio.positions:
        pos_rows.append({
            "Delete": False,
            "Ticker": pos.asset.ticker,
            "Name": pos.asset.name,
            "Type": pos.asset.asset_type.value,
            "Sector": pos.asset.sector or "",
            "Quantity": pos.quantity,
            "Cost Basis (per share)": pos.cost_basis,
        })
    pos_df = pd.DataFrame(pos_rows) if pos_rows else pd.DataFrame(
        columns=["Delete", "Ticker", "Name", "Type", "Sector", "Quantity", "Cost Basis (per share)"]
    )
    for col in ("Ticker", "Name", "Type", "Sector"):
        if col in pos_df.columns:
            pos_df[col] = pos_df[col].fillna("").astype(str)

    edited_pos = st.data_editor(
        pos_df,
        column_config={
            "Delete": st.column_config.CheckboxColumn("🗑️", default=False),
            "Ticker": st.column_config.TextColumn("Ticker", disabled=True),
            "Name": st.column_config.TextColumn("Name", disabled=True),
            "Type": st.column_config.TextColumn("Type", disabled=True),
            "Sector": st.column_config.TextColumn("Sector", disabled=True),
            "Quantity": st.column_config.NumberColumn("Quantity", min_value=0, step=0.0001, format="%.4f"),
            "Cost Basis (per share)": st.column_config.NumberColumn(
                "Cost Basis (per share)", min_value=0, step=0.01, format="%.4f"
            ),
        },
        use_container_width=True,
        hide_index=True,
        key="pos_editor",
    )

    if st.button("Save Position Changes", type="primary", key="save_pos"):
        keep = edited_pos[~edited_pos["Delete"]]
        new_rows = [
            {"ticker": r["Ticker"], "quantity": r["Quantity"], "cost_basis": r["Cost Basis (per share)"]}
            for _, r in keep.iterrows()
            if r["Quantity"] > 0
        ]
        db.update_positions_direct(portfolio.name, new_rows)
        st.session_state["portfolio"] = db.get_portfolio(portfolio.name)
        deleted = edited_pos[edited_pos["Delete"]]["Ticker"].tolist()
        msg = f"Saved. {len(new_rows)} position(s) kept."
        if deleted:
            msg += f" Removed: {', '.join(deleted)}."
        st.success(msg)
        st.rerun()

    st.markdown("---")

    # ── Add new position ──────────────────────────────────────────────────────
    with st.expander("➕ Add New Position"):
        all_assets = db.get_all_assets()
        known_tickers = all_assets["ticker"].tolist() if not all_assets.empty else []

        with st.form("add_position_form"):
            st.markdown("Enter details for the new position. If the ticker is not yet in the Security Master it will be created automatically.")
            col_a, col_b = st.columns(2)
            with col_a:
                new_ticker = st.text_input("Ticker *", placeholder="e.g. AAPL").strip().upper()
                new_qty = st.number_input("Quantity *", min_value=0.0001, step=0.01, format="%.4f")
                new_cost = st.number_input("Per-share Cost Basis *", min_value=0.0001, step=0.01, format="%.4f")
            with col_b:
                new_name = st.text_input("Name", placeholder="e.g. Apple Inc.")
                new_type = st.selectbox("Asset Type", [at.value for at in AssetType])
                new_sector = st.text_input("Sector", placeholder="e.g. Technology")

            if st.form_submit_button("Add Position", type="primary"):
                if not new_ticker:
                    st.error("Ticker is required.")
                else:
                    # Create asset if missing
                    if new_ticker not in known_tickers:
                        asset = Asset(
                            ticker=new_ticker,
                            name=new_name or new_ticker,
                            asset_type=AssetType(new_type),
                            sector=new_sector or None,
                        )
                        db.add_asset(asset)
                    # Add position (BUY trade so average cost blending applies
                    # if the ticker already has a position)
                    db._apply_trade_to_positions(portfolio.name, new_ticker, "BUY", new_qty, new_cost)
                    # Ensure portfolio record exists
                    if portfolio.name not in db.list_portfolios():
                        db.save_portfolio(portfolio)
                    st.session_state["portfolio"] = db.get_portfolio(portfolio.name)
                    st.success(f"Added {new_ticker} × {new_qty} @ {new_cost:.4f}")
                    st.rerun()

# ── Security Master ───────────────────────────────────────────────────────────

with tab_security:
    st.header("Security Master")
    db = get_db()
    st.caption("Edit security metadata for any asset. Ticker is the unique key and cannot be changed here.")

    assets_df = db.get_all_assets()
    asset_type_options = [at.value for at in AssetType]

    if assets_df.empty:
        st.info("No assets in the database yet.")
    else:
        edited_assets = st.data_editor(
            assets_df,
            column_config={
                "ticker": st.column_config.TextColumn("Ticker", disabled=True),
                "name": st.column_config.TextColumn("Name"),
                "asset_type": st.column_config.SelectboxColumn("Type", options=asset_type_options),
                "currency": st.column_config.TextColumn("Currency"),
                "sector": st.column_config.TextColumn("Sector"),
                "income_rate": st.column_config.NumberColumn(
                    "Income Rate",
                    help=(
                        "Units depend on Type:\n"
                        "• Stock / ETF / Fund → $ per share PER PAYMENT "
                        "(e.g. BLK paying $5.72 quarterly → enter 5.72, Pay Freq 4).\n"
                        "• Bond / CD / Cash → annual % "
                        "(e.g. 4.5 for a 4.5% coupon or yield).\n"
                        "0 if unknown."
                    ),
                    min_value=0.0, max_value=10000.0, step=0.05, format="%.4f",
                ),
                "payment_frequency": st.column_config.SelectboxColumn(
                    "Pay Freq",
                    help="Payments per year. Only meaningful for Bond/CD (1 = annual, 2 = semi-annual, 4 = quarterly, 12 = monthly).",
                    options=[1, 2, 4, 12],
                ),
            },
            use_container_width=True,
            hide_index=True,
            key="security_editor",
        )

        if st.button("Save Security Master Changes", type="primary", key="save_sec"):
            saved = edited_assets.copy()
            saved["income_rate"] = pd.to_numeric(
                saved.get("income_rate"), errors="coerce"
            ).fillna(0.0)
            saved["payment_frequency"] = (
                pd.to_numeric(saved.get("payment_frequency"), errors="coerce")
                .fillna(1).astype(int)
            )
            db.update_assets_direct(saved)
            st.success(f"Security master updated — {len(saved)} records.")

    st.markdown("---")

    # ── Add new asset ─────────────────────────────────────────────────────────
    with st.expander("➕ Add New Security"):
        with st.form("add_asset_form"):
            col1, col2 = st.columns(2)
            with col1:
                a_ticker = st.text_input("Ticker *", placeholder="e.g. BND").strip().upper()
                a_name = st.text_input("Name *", placeholder="e.g. Vanguard Total Bond Market ETF")
                a_type = st.selectbox("Asset Type *", asset_type_options)
            with col2:
                a_currency = st.text_input("Currency", value="USD")
                a_sector = st.text_input("Sector", placeholder="e.g. Fixed Income")
                a_income = st.number_input(
                    "Income Rate",
                    min_value=0.0, max_value=10000.0, value=0.0, step=0.05, format="%.4f",
                    help=(
                        "Stock/ETF/Fund → $ per share PER PAYMENT "
                        "(combined with Payment Frequency for annual). "
                        "Bond/CD/Cash → annual %. 0 if unknown."
                    ),
                )
                a_freq = st.selectbox(
                    "Payment Frequency",
                    options=[1, 2, 4, 12],
                    format_func=lambda n: {1:"Annual", 2:"Semi-annual", 4:"Quarterly", 12:"Monthly"}[n],
                    help="Payments per year. Only meaningful for Bond/CD.",
                )

            if st.form_submit_button("Add Security", type="primary"):
                if not a_ticker or not a_name:
                    st.error("Ticker and Name are required.")
                else:
                    existing = db.get_all_assets()
                    if not existing.empty and a_ticker in existing["ticker"].values:
                        st.warning(f"{a_ticker} already exists — edit it in the table above.")
                    else:
                        db.add_asset(Asset(
                            ticker=a_ticker,
                            name=a_name,
                            asset_type=AssetType(a_type),
                            currency=a_currency or "USD",
                            sector=a_sector or None,
                            income_rate=float(a_income or 0.0),
                            payment_frequency=int(a_freq or 1),
                        ))
                        st.success(f"Added {a_ticker} to the security master.")
                        st.rerun()

# ── Trade Blotter ─────────────────────────────────────────────────────────────

with tab_trades:
    st.header("Trade Blotter")
    db = get_db()

    # ── Record a new trade ────────────────────────────────────────────────────
    with st.expander("📝 Record New Trade", expanded=True):
        with st.form("trade_form"):
            col_t1, col_t2, col_t3 = st.columns(3)
            with col_t1:
                t_portfolio = st.selectbox(
                    "Portfolio *",
                    options=db.list_portfolios() or [portfolio.name],
                    index=0,
                )
                t_ticker = st.text_input("Ticker *", placeholder="e.g. AAPL").strip().upper()
                t_side = st.radio("Side *", ["BUY", "SELL"], horizontal=True)
            with col_t2:
                t_quantity = st.number_input("Quantity *", min_value=0.0001, step=0.01, format="%.4f",
                                             help="Always enter a positive number. Use Side to indicate direction.")
                t_price = st.number_input("Trade Price *", min_value=0.0001, step=0.01, format="%.4f",
                                          help="Price per unit at execution.")
            with col_t3:
                t_date = st.date_input("Trade Date *", value=pd.Timestamp.today().date())

            submitted = st.form_submit_button("Record Trade", type="primary")

        if submitted:
            if not t_ticker:
                st.error("Ticker is required.")
            elif t_quantity <= 0:
                st.error("Quantity must be positive.")
            elif t_price <= 0:
                st.error("Trade price must be positive.")
            else:
                # Ensure asset exists in security master
                existing_assets = db.get_all_assets()
                if existing_assets.empty or t_ticker not in existing_assets["ticker"].values:
                    db.add_asset(Asset(ticker=t_ticker, name=t_ticker, asset_type=AssetType.STOCK))
                    st.info(f"{t_ticker} was not in the security master — added with default type Stock. Update it in the Security Master tab.")

                # Ensure portfolio record exists
                if t_portfolio not in db.list_portfolios():
                    st.error(f"Portfolio '{t_portfolio}' not found.")
                else:
                    db.record_trade(
                        portfolio_name=t_portfolio,
                        ticker=t_ticker,
                        side=t_side,
                        quantity=t_quantity,
                        trade_price=t_price,
                        trade_date=str(t_date),
                    )
                    # Refresh active portfolio if it's the one we traded in
                    if t_portfolio == portfolio.name:
                        st.session_state["portfolio"] = db.get_portfolio(portfolio.name)

                    notional = t_quantity * t_price
                    st.success(
                        f"{'Bought' if t_side == 'BUY' else 'Sold'} {t_quantity:,.4f} × "
                        f"{t_ticker} @ ${t_price:,.4f} = ${notional:,.2f} "
                        f"in '{t_portfolio}' on {t_date}."
                    )
                    st.rerun()

    st.markdown("---")

    # ── Trade history ─────────────────────────────────────────────────────────
    st.subheader("Trade History")
    show_all = st.checkbox("Show all portfolios", value=False)
    trades_df = db.list_trades(None if show_all else portfolio.name)

    if trades_df.empty:
        st.info("No trades recorded yet.")
    else:
        display_trades = trades_df.copy()
        display_trades["trade_price"] = display_trades["trade_price"].map(lambda x: f"${x:,.4f}")
        display_trades["notional"] = (
            trades_df["quantity"] * trades_df["trade_price"]
        ).map(lambda x: f"${x:,.2f}")
        display_trades = display_trades.rename(columns={
            "trade_id": "ID",
            "portfolio_name": "Portfolio",
            "ticker": "Ticker",
            "side": "Side",
            "quantity": "Quantity",
            "trade_price": "Price",
            "trade_date": "Date",
            "notional": "Notional",
        })[["ID", "Date", "Portfolio", "Ticker", "Side", "Quantity", "Price", "Notional"]]
        st.dataframe(display_trades, use_container_width=True, hide_index=True)

# ── Lookthrough ───────────────────────────────────────────────────────────────

with tab_lookthrough:
    st.header("ETF / Fund Lookthrough")
    st.caption(
        "Upload monthly holdings files from an ETF or fund vendor (iShares, Vanguard, etc.) "
        "to see the underlying exposure for any fund position in this portfolio."
    )

    db = get_db()

    # Only show ETF/Fund positions from the active portfolio.
    # Compare by .value rather than the enum member — when Streamlit hot-reloads
    # modules, `AssetType` can get re-imported under a different class identity,
    # so `pos.asset.asset_type in (AssetType.ETF, AssetType.FUND)` returns False
    # for genuine ETF positions. The string value is stable across reloads.
    _FUND_LIKE = {"ETF", "Fund"}
    fund_positions = [
        pos for pos in portfolio.positions
        if pos.asset.asset_type.value in _FUND_LIKE
    ]

    if not fund_positions:
        n_total = len(portfolio.positions)
        type_summary = ", ".join(
            f"{t} × {sum(1 for p in portfolio.positions if p.asset.asset_type.value == t)}"
            for t in sorted({p.asset.asset_type.value for p in portfolio.positions})
        ) or "no positions"
        st.info(
            f"No ETF or Fund positions in the active portfolio **{portfolio.name}** "
            f"({n_total} positions: {type_summary}).\n\n"
            "If you meant a different portfolio, pick it in the sidebar and click "
            "**Open**. The currently-loaded portfolio is shown as **Active:** "
            "above the action buttons."
        )
        st.stop()

    fund_tickers = [pos.asset.ticker for pos in fund_positions]
    selected_fund = st.selectbox(
        "Select fund / ETF",
        fund_tickers,
        format_func=lambda t: f"{t} — {next(p.asset.name for p in fund_positions if p.asset.ticker == t)}",
    )

    st.markdown("---")

    col_upload, col_snapshots = st.columns([1, 1])

    with col_upload:
        st.subheader("Upload Holdings Snapshot")
        uploaded_holdings = st.file_uploader(
            "Holdings CSV from the fund vendor",
            type=["csv"],
            key="holdings_upload",
        )
        snap_date = st.date_input(
            "As-of date (e.g. end of month)",
            value=pd.Timestamp.today().date(),
            key="snap_date",
        )
        if st.button("Import Holdings", type="primary", disabled=uploaded_holdings is None):
            try:
                ingester = Ingester(db)
                holdings_df = ingester.parse_fund_holdings_csv(
                    uploaded_holdings.getbuffer().tobytes(),
                    selected_fund,
                )
                db.save_fund_holdings(selected_fund, str(snap_date), holdings_df)
                st.success(
                    f"Imported {len(holdings_df)} holdings for {selected_fund} "
                    f"as of {snap_date}."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to parse holdings file: {exc}")

        with st.expander("Expected CSV format"):
            st.markdown("""
The parser auto-detects common vendor layouts. It looks for columns matching:

| Logical field | Common column names |
|---|---|
| Ticker/symbol | `Ticker`, `Symbol`, `ISIN`, `SEDOL` |
| Name | `Name`, `Holding`, `Description`, `Security` |
| Weight | `Weight (%)`, `% of fund`, `Weighting`, `Allocation` |
| Sector | `Sector`, `Industry`, `GICS Sector` |
| Asset type | `Asset Class`, `Type`, `Instrument` |

iShares and Vanguard formats are detected automatically, including their metadata header rows.
""")

    with col_snapshots:
        st.subheader("Saved Snapshots")
        dates = db.list_fund_holdings_dates(selected_fund)
        if not dates:
            st.info("No snapshots yet — upload a holdings file.")
        else:
            snap_df = pd.DataFrame({"Date": dates})
            st.dataframe(snap_df, use_container_width=True, hide_index=True)

            del_date = st.selectbox("Delete snapshot", dates, key="del_snap_date")
            if st.button("Delete", type="secondary", key="del_snap_btn"):
                db.delete_fund_holdings(selected_fund, del_date)
                st.success(f"Deleted {selected_fund} snapshot for {del_date}.")
                st.rerun()

    st.markdown("---")

    # ── Fund Profile (yfinance) ───────────────────────────────────────────────
    st.subheader("Fund Profile (yfinance)")
    st.caption(
        "Aggregate asset-class and sector breakdown fetched from yfinance "
        "(no constituent-level CSV needed)."
    )

    col_fetch, col_prof_dates = st.columns([1, 1])

    with col_fetch:
        if st.button("Fetch Profile from yfinance", type="primary", key="fetch_profile_btn"):
            try:
                profile = Collector(db).fetch_fund_profile(selected_fund)
                today = pd.Timestamp.today().date().isoformat()
                db.save_fund_profile(
                    selected_fund,
                    today,
                    profile["asset_classes"],
                    profile["sector_weightings"],
                )
                st.success(f"Saved profile for {selected_fund} as of {today}.")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to fetch profile: {exc}")

    with col_prof_dates:
        prof_dates = db.list_fund_profile_dates(selected_fund)
        if prof_dates:
            del_prof_date = st.selectbox("Delete profile snapshot", prof_dates, key="del_prof_date")
            if st.button("Delete profile", type="secondary", key="del_prof_btn"):
                db.delete_fund_profile(selected_fund, del_prof_date)
                st.success(f"Deleted {selected_fund} profile for {del_prof_date}.")
                st.rerun()

    prof_dates = db.list_fund_profile_dates(selected_fund)
    if prof_dates:
        view_prof_date = st.selectbox(
            "Profile snapshot date", prof_dates, key="view_prof_date",
        )
        profile = db.get_fund_profile(selected_fund, view_prof_date)
        ac = profile["asset_classes"]
        sectors = profile["sector_weightings"]

        # Dominant asset class → label the fund
        if ac:
            dominant = max(ac.items(), key=lambda kv: kv[1])
            label_map = {
                "stockPosition": "Equity",
                "bondPosition": "Bond",
                "cashPosition": "Cash",
                "preferredPosition": "Preferred",
                "convertiblePosition": "Convertible",
                "otherPosition": "Other",
            }
            kind = label_map.get(dominant[0], dominant[0])
            st.metric(
                f"Fund Type — {kind}",
                f"{dominant[1] * 100:.1f}%",
                help="Dominant asset class from yfinance asset_classes.",
            )

        col_ac, col_sec = st.columns([1, 2])

        with col_ac:
            st.markdown("**Asset Class Breakdown**")
            if ac:
                ac_df = pd.DataFrame(
                    [{"Class": label_map.get(k, k), "Weight": v} for k, v in ac.items() if v > 0]
                ).sort_values("Weight", ascending=False)
                ac_disp = ac_df.copy()
                ac_disp["Weight"] = ac_disp["Weight"].map(lambda x: f"{x * 100:.2f}%")
                st.dataframe(ac_disp, use_container_width=True, hide_index=True)
            else:
                st.info("No asset_classes data.")

        with col_sec:
            st.markdown("**Sector Weightings**")
            if sectors:
                sec_df = (
                    pd.DataFrame(
                        [{"Sector": k.replace("_", " ").title(), "Weight": v}
                         for k, v in sectors.items() if v > 0]
                    )
                    .sort_values("Weight", ascending=True)
                )
                fig_prof = px.bar(
                    sec_df, x="Weight", y="Sector", orientation="h",
                    labels={"Weight": "Fund Weight", "Sector": ""},
                )
                fig_prof.update_layout(xaxis_tickformat=".1%", yaxis_title="")
                st.plotly_chart(fig_prof, use_container_width=True)
            else:
                st.info("No sector_weightings data (typical for bond ETFs).")
    else:
        st.info("No profile saved yet — click **Fetch Profile from yfinance**.")

    st.markdown("---")

    # ── View holdings ─────────────────────────────────────────────────────────
    dates = db.list_fund_holdings_dates(selected_fund)
    if dates:
        st.subheader(f"Holdings — {selected_fund}")

        view_date = st.selectbox("Snapshot date", dates, key="view_snap_date")
        holdings = db.get_fund_holdings(selected_fund, view_date)

        if holdings.empty:
            st.info("No holdings data for this snapshot.")
        else:
            # ── Summary metrics ───────────────────────────────────────────────
            coverage = holdings["weight"].sum()
            n_holdings = len(holdings)
            top5_weight = holdings.nlargest(5, "weight")["weight"].sum()

            m1, m2, m3 = st.columns(3)
            m1.metric("# Holdings", n_holdings)
            m2.metric("Weight Coverage", f"{coverage * 100:.1f}%")
            m3.metric("Top-5 Concentration", f"{top5_weight * 100:.1f}%")

            # ── Sector chart ──────────────────────────────────────────────────
            has_sector = holdings["sector"].ne("").any()
            if has_sector:
                sector_agg = (
                    holdings.groupby("sector")["weight"].sum()
                    .reset_index()
                    .sort_values("weight", ascending=True)
                )
                fig_sector = px.bar(
                    sector_agg, x="weight", y="sector", orientation="h",
                    title="Sector Breakdown",
                    labels={"weight": "Portfolio Weight", "sector": ""},
                )
                fig_sector.update_layout(xaxis_tickformat=".1%", yaxis_title="")
                st.plotly_chart(fig_sector, use_container_width=True)

            # ── Holdings table ────────────────────────────────────────────────
            disp = holdings.copy()
            disp["weight"] = disp["weight"].map(lambda x: f"{x * 100:.3f}%")
            disp = disp.rename(columns={
                "holding_ticker": "Ticker",
                "holding_name": "Name",
                "weight": "Weight",
                "sector": "Sector",
                "asset_type": "Asset Class",
            })
            st.dataframe(disp, use_container_width=True, hide_index=True)

            # ── Lookthrough contribution to portfolio ─────────────────────────
            st.markdown("---")
            st.subheader("Lookthrough — Portfolio Contribution")

            pos = next(p for p in portfolio.positions if p.asset.ticker == selected_fund)
            cp = cur_prices.get(selected_fund)
            fund_value = pos.quantity * (cp if cp is not None else pos.cost_basis)

            contrib = holdings.copy()
            contrib["value"] = contrib["weight"] * fund_value
            total_port_cost = sum(p.quantity * p.cost_basis for p in portfolio.positions)
            contrib["port_weight"] = contrib["value"] / total_port_cost * 100

            disp2 = contrib[["holding_ticker", "holding_name", "weight", "value", "port_weight", "sector"]].copy()
            disp2["weight"] = disp2["weight"].map(lambda x: f"{x * 100:.3f}%")
            disp2["value"] = disp2["value"].map(lambda x: f"${x:,.0f}")
            disp2["port_weight"] = disp2["port_weight"].map(lambda x: f"{x:.3f}%")
            disp2 = disp2.rename(columns={
                "holding_ticker": "Ticker",
                "holding_name": "Name",
                "weight": "Fund Weight",
                "value": "Est. Value",
                "port_weight": "% of Portfolio",
                "sector": "Sector",
            })
            st.dataframe(disp2, use_container_width=True, hide_index=True)
