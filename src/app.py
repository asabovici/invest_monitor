import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.collector import Collector
from src.data.ingestion import Ingester
from src.database.database import Database
from src.models import Asset, AssetType, Portfolio
from src.reporting import ReportingEngine

st.set_page_config(
    page_title="Invest Monitor",
    page_icon="📈",
    layout="wide",
)

# ── Helpers ──────────────────────────────────────────────────────────────────

@st.cache_resource
def get_db() -> Database:
    return Database()


@st.cache_resource
def get_reporting() -> ReportingEngine:
    return ReportingEngine(get_db())


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
def fetch_prices(tickers: tuple[str, ...]) -> pd.DataFrame:
    return get_db().get_historical_prices(list(tickers))


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


def compute_portfolio_metrics(portfolio: Portfolio) -> dict | None:
    """Compute cross-portfolio comparable metrics. Returns None if no price data."""
    tickers = [pos.asset.ticker for pos in portfolio.positions]
    prices = get_db().get_historical_prices(tickers)
    if prices.empty:
        return None

    weights_map = {pos.asset.ticker: pos.quantity * pos.cost_basis for pos in portfolio.positions}
    total_cost = sum(weights_map.values())

    available = [t for t in tickers if t in prices.columns]
    if not available:
        return None

    # Normalize weights to only the tickers that have price data
    w_raw = np.array([weights_map.get(t, 0) for t in available])
    w = w_raw / w_raw.sum()

    # Drop rows where any ticker has NaN so the weighted series is clean
    port_series = prices[available].dropna(how="any").dot(w)
    if port_series.empty or len(port_series) < 2:
        return None

    daily_ret = port_series.pct_change().dropna()
    if daily_ret.empty:
        return None

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
    st.title("Invest Monitor")
    st.markdown("---")
    view = st.radio("View", ["Multi-Portfolio Dashboard", "Single Portfolio"], label_visibility="collapsed")
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

    if "portfolio" in st.session_state:
        p: Portfolio = st.session_state["portfolio"]
        st.markdown(f"**Active:** {p.name} ({len(p.positions)} positions)")
        st.markdown("---")

        period = st.selectbox("Price history period", ["1mo", "3mo", "6mo", "1y", "2y", "5y"], index=3)
        if st.button("Collect Prices"):
            with st.spinner("Fetching from yfinance…"):
                Collector(get_db()).update_all_assets(period=period)
                fetch_prices.clear()
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

    portfolio_names = get_db().list_portfolios()
    if not portfolio_names:
        st.info("No portfolios found. Import a portfolio CSV in the sidebar.")
        st.stop()

    HORIZONS = ["1M", "3M", "6M", "1Y"]
    CONFIDENCE_LEVELS = [("95%", "var_95"), ("99%", "var_99")]

    summary_rows = []
    metrics_by_name: dict = {}

    for name in portfolio_names:
        try:
            p = get_db().get_portfolio(name)
        except Exception:
            continue
        m = compute_portfolio_metrics(p)
        metrics_by_name[name] = m
        row: dict = {
            "Portfolio": name,
            "Positions": len(p.positions),
            "Total Cost": fmt_usd(sum(pos.quantity * pos.cost_basis for pos in p.positions)),
        }
        if m:
            for h in HORIZONS:
                v = m["cum_returns"].get(h)
                row[h] = fmt_pct(v * 100) if v is not None else "N/A"
            row["Volatility (Ann.)"] = fmt_pct(m["volatility"] * 100)
            row["VaR 95% (1d)"]  = fmt_pct(m["var_95"] * 100)
            row["VaR 99% (1d)"]  = fmt_pct(m["var_99"] * 100)
            row["Max Drawdown"]  = fmt_pct(m["max_drawdown"] * 100)
            row["Current Drawdown"] = fmt_pct(m["current_drawdown"] * 100)
        else:
            for col in HORIZONS + ["Volatility (Ann.)", "VaR 95% (1d)", "VaR 99% (1d)", "Max Drawdown", "Current Drawdown"]:
                row[col] = "No price data"
        summary_rows.append(row)

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

    # ── Wealth Projection ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Wealth Projection")

    ASSET_TYPES = ["Stock", "ETF", "Bond", "Fund", "Cash"]
    DEFAULT_RETURNS = {"Stock": 8.0, "ETF": 7.0, "Bond": 3.5, "Fund": 6.0, "Cash": 4.5}

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

    # Project each portfolio
    current_year = pd.Timestamp.now().year
    years_axis = list(range(horizon + 1))
    x_labels = [current_year + y for y in years_axis]

    fig_wealth = go.Figure()
    milestone_rows = []

    for pname in portfolio_names:
        try:
            p = get_db().get_portfolio(pname)
        except Exception:
            continue

        values = [0.0] * (horizon + 1)
        for pos in p.positions:
            at = pos.asset.asset_type.value
            cur = pos.quantity * pos.cost_basis
            values[0] += cur
            for yr in range(1, horizon + 1):
                cur *= 1 + _annual_rate(yr, at)
                values[yr] += cur

        fig_wealth.add_trace(go.Scatter(
            x=x_labels, y=values, name=pname,
            mode="lines", line=dict(width=2),
            hovertemplate="%{x}: $%{y:,.0f}<extra>" + pname + "</extra>",
        ))

        # Milestone table row
        milestones = {"Portfolio": pname, "Today": fmt_usd(values[0])}
        for yr in [5, 10, 15, 20, 30, 40, 50]:
            if yr <= horizon:
                milestones[f"Year {yr}"] = fmt_usd(values[yr])
        milestone_rows.append(milestones)

    fig_wealth.update_layout(
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

tab_overview, tab_prices, tab_exposure, tab_risk, tab_positions, tab_security, tab_trades, tab_lookthrough = st.tabs([
    "📊 Overview", "📈 Price History", "🥧 Exposure", "⚠️ Risk",
    "✏️ Positions", "🏢 Security Master", "📋 Trades", "🔍 Lookthrough",
])

# ── Overview ──────────────────────────────────────────────────────────────────

with tab_overview:
    st.header(portfolio.name)

    cur_prices = latest_prices(tickers)

    rows = []
    for pos in portfolio.positions:
        t = pos.asset.ticker
        cp = cur_prices.get(t)
        total_cost = pos.quantity * pos.cost_basis
        cur_val = pos.quantity * cp if cp is not None else None
        pnl = (cur_val - total_cost) if cur_val is not None else None
        pnl_pct = (pnl / total_cost * 100) if (pnl is not None and total_cost) else None
        rows.append({
            "Ticker": t,
            "Name": pos.asset.name or "",
            "Type": pos.asset.asset_type.value,
            "Sector": pos.asset.sector or "—",
            "Quantity": pos.quantity,
            "Cost Basis": pos.cost_basis,
            "Total Cost": total_cost,
            "Current Price": cp,
            "Current Value": cur_val,
            "P&L": pnl,
            "P&L %": pnl_pct,
        })

    df = pd.DataFrame(rows)

    total_cost = df["Total Cost"].sum()
    total_value = df["Current Value"].sum() if df["Current Value"].notna().any() else None
    total_pnl = (total_value - total_cost) if total_value is not None else None
    total_pnl_pct = (total_pnl / total_cost * 100) if (total_pnl is not None and total_cost) else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Positions", len(portfolio.positions))
    c2.metric("Total Cost", fmt_usd(total_cost))
    c3.metric("Current Value", fmt_usd(total_value))
    if total_pnl is not None:
        c4.metric("Total P&L", fmt_usd(total_pnl), delta=fmt_pct(total_pnl_pct))

    st.markdown("---")

    # Styled display dataframe
    display = df.copy()
    display["Cost Basis"] = display["Cost Basis"].map(fmt_usd)
    display["Total Cost"] = display["Total Cost"].map(fmt_usd)
    display["Current Price"] = display["Current Price"].map(fmt_usd)
    display["Current Value"] = display["Current Value"].map(fmt_usd)
    display["P&L"] = display["P&L"].map(fmt_usd)
    display["P&L %"] = display["P&L %"].map(fmt_pct)

    st.dataframe(display, use_container_width=True, hide_index=True)

    # Mini asset-type donut
    if not df.empty:
        type_df = df.groupby("Type")["Total Cost"].sum().reset_index()
        fig = px.pie(type_df, names="Type", values="Total Cost",
                     title="Allocation by Asset Type (cost basis)",
                     hole=0.45)
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

    try:
        exposure_df = reporting.get_portfolio_exposure(portfolio).reset_index()

        # Use current values if available, else fall back to cost basis already in df
        if cur_prices:
            value_map = {}
            for pos in portfolio.positions:
                cp = cur_prices.get(pos.asset.ticker)
                value_map[pos.asset.ticker] = pos.quantity * (cp if cp is not None else pos.cost_basis)
            # Rebuild with current values, applying lookthrough for ETF/Fund positions
            rows_exp = []
            for pos in portfolio.positions:
                base = value_map[pos.asset.ticker]
                is_fund = pos.asset.asset_type in (AssetType.ETF, AssetType.FUND)
                holdings = db.get_fund_holdings(pos.asset.ticker) if is_fund else pd.DataFrame()
                if is_fund and not holdings.empty:
                    for _, h in holdings.iterrows():
                        rows_exp.append({
                            "Type": h["asset_type"] or "Lookthrough",
                            "Sector": h["sector"] or "Unknown",
                            "Value": h["weight"] * base,
                            "Via": pos.asset.ticker,
                        })
                elif pos.asset.is_composite():
                    for c in pos.asset.constituents:
                        rows_exp.append({"Type": "Constituent", "Sector": "Look-through", "Value": c.weight * base, "Via": pos.asset.ticker})
                else:
                    rows_exp.append({"Type": pos.asset.asset_type.value, "Sector": pos.asset.sector or "Unknown", "Value": base, "Via": ""})
            exposure_df = pd.DataFrame(rows_exp).groupby(["Type", "Sector"])["Value"].sum().reset_index()
        else:
            exposure_df = exposure_df.rename(columns={"Weight": "Value"})

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

    prices_df_risk = fetch_prices(tuple(tickers))

    if prices_df_risk.empty:
        st.warning("No price data found. Use **Collect Prices** in the sidebar first.")
    else:
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
            st.dataframe(cov_matrix.style.format("{:.4f}").background_gradient(cmap="Blues"),
                         use_container_width=True)

        except Exception as e:
            st.error(f"Could not compute risk metrics: {e}")

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
            },
            use_container_width=True,
            hide_index=True,
            key="security_editor",
        )

        if st.button("Save Security Master Changes", type="primary", key="save_sec"):
            db.update_assets_direct(edited_assets)
            st.success(f"Security master updated — {len(edited_assets)} records.")

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

    # Only show ETF/Fund positions from the active portfolio
    fund_positions = [
        pos for pos in portfolio.positions
        if pos.asset.asset_type in (AssetType.ETF, AssetType.FUND)
    ]

    if not fund_positions:
        st.info("No ETF or Fund positions found in this portfolio. Add one in the Positions tab first.")
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
