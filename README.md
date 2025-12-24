# Investment Monitor

A simple Python application to manage an investment portfolio, collect historical data, and generate risk reports.

## Architecture

This project uses:
- **DuckDB**: For querying and data manipulation.
- **Parquet**: For efficient data storage.
- **UV**: For fast package management.

The data is stored in the `data/parquet/` directory as Parquet files:
- `assets.parquet`: Stores asset metadata.
- `constituents.parquet`: Stores ETF/Fund constituents.
- `prices.parquet`: Stores historical price data.

## Setup

1. **Install UV** (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Initialize and Sync Dependencies**:
   ```bash
   uv sync
   ```

## Usage

### 1. Load Portfolio
Load a portfolio from a CSV file.
```bash
uv run python src/cli.py load data/sample_portfolio.csv --name "My Portfolio"
```

### 2. Collect Data
Fetch historical price data for the assets in the portfolio.
```bash
uv run python src/cli.py collect --period 1y
```

### 3. Generate Report
Generate a risk and exposure report.
```bash
uv run python src/cli.py report data/sample_portfolio.csv --output report.md
```

## Running Tests
```bash
uv run pytest
```
