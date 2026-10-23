"""Pipeline entrypoints; offline reads do not import collection/credential clients."""
from importlib import import_module

from .offline_reader import DataRead, OfflineDataReader

_LAZY = {
    "run_ingestion": (".ingestion", "run_ingestion"),
    "fetch_ff_factors": (".wrds_client", "fetch_ff_factors"),
    "transform_raw_to_final": (".transform", "transform_raw_to_final"),
    "run_quality_checks": (".quality", "run_quality_checks"),
    "get_final_data": (".final_data", "get_final_data"),
    "export_fundamental_failures": (".failure_utils", "export_fundamental_failures"),
    "export_company_overview_failures": (".failure_utils", "export_company_overview_failures"),
    "refetch_failures": (".failure_utils", "refetch_failures"),
}


def __getattr__(name):
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attribute = _LAZY[name]
    value = getattr(import_module(module, __name__), attribute)
    globals()[name] = value
    return value


__all__ = [
    "DataRead",
    "OfflineDataReader",
    "export_company_overview_failures",
    "export_fundamental_failures",
    "get_final_data",
    "refetch_failures",
    "run_ingestion",
    "run_quality_checks",
    "transform_raw_to_final",
]
