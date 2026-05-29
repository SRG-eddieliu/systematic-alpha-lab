def test_consolidated_imports():
    from systematic_alpha_lab.alpha import AlphaDataLoader
    from systematic_alpha_lab.data_pipeline import get_final_data
    from systematic_alpha_lab.factor_research import DataLoader, FactorBase

    assert get_final_data.__name__ == "get_final_data"
    assert DataLoader.__name__ == "DataLoader"
    assert FactorBase.__name__ == "FactorBase"
    assert AlphaDataLoader.__name__ == "AlphaDataLoader"
