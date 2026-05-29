"""Minimal import demo for the consolidated package."""

from systematic_alpha_lab.alpha import AlphaDataLoader
from systematic_alpha_lab.data_pipeline import get_final_data
from systematic_alpha_lab.factor_research import DataLoader, FactorBase


def main() -> None:
    print("Loaded consolidated modules:")
    print(f"- data pipeline function: {get_final_data.__name__}")
    print(f"- factor loader class: {DataLoader.__name__}")
    print(f"- factor base class: {FactorBase.__name__}")
    print(f"- alpha loader class: {AlphaDataLoader.__name__}")


if __name__ == "__main__":
    main()
