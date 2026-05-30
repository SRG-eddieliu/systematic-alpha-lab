"""Run a credential-free Systematic Alpha Lab demo."""

from systematic_alpha_lab.workflows import run_synthetic_equity_alpha_demo


def main() -> None:
    data, factor_result, alpha_result = run_synthetic_equity_alpha_demo()

    print("Synthetic data")
    print(f"- prices: {data.prices.shape[0]} dates x {data.prices.shape[1]} assets")
    print(f"- sectors: {data.sectors.nunique()} sectors")

    print("\nFactor analytics")
    for name, metrics in factor_result.analytics.items():
        print(
            f"- {name}: "
            f"mean IC={metrics['mean_ic']:.4f}, "
            f"IC IR={metrics['ic_ir']:.4f}, "
            f"LS Sharpe={metrics['ls_sharpe']:.4f}"
        )

    print("\nCombined alpha")
    print(f"- IC: {alpha_result.metrics['ic']:.4f}")
    print(f"- IR: {alpha_result.metrics['ir']:.4f}")
    print(f"- turnover: {alpha_result.metrics['turnover']:.4f}")
    decay = {horizon: round(float(value), 4) for horizon, value in alpha_result.metrics["decay"].items()}
    print(f"- decay: {decay}")


if __name__ == "__main__":
    main()
