"""Offline synthetic demonstration, with no market return or availability claim."""
import json

import pandas as pd

from systematic_alpha_lab.factor_research.financial_quality import quarterly_accrual_diagnostic


def main():
    statements = pd.DataFrame({
        "asset": "synthetic-company",
        "fiscal_year": [2020] * 4 + [2021] * 4,
        "fiscal_quarter": [1, 2, 3, 4] * 2,
        "period_end": pd.date_range("2020-03-31", periods=8, freq=pd.offsets.QuarterEnd()),
        "currency": "USD", "unit": "millions",
        "net_income": [10.] * 8,
        "operating_cash_flow_ytd": [6., 14., 24., 36., 5., 12., 21., 32.],
        "total_assets": [100., 110., 120., 130., 140., 150., 160., 170.],
    })
    result = quarterly_accrual_diagnostic(statements)
    print(json.dumps({
        "input": "explicitly synthetic",
        "statement_rows": len(result),
        "calculation_ready_rows": int(result.calculation_ready.sum()),
        "first_2021_quarter_cash_flow": float(result.operating_cash_flow_quarter.iloc[4]),
        "last_accrual_quality": float(result.accrual_quality.iloc[-1]),
        "timing_status": result.timing_status.iloc[-1],
    }, indent=2))


if __name__ == "__main__":
    main()
