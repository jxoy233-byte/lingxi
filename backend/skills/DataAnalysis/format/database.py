"""Helpers for turning database query results into DataAnalysis artifacts."""
from __future__ import annotations

import json
from typing import Any

from .core import ChatDataAnalysisFormat


def save_database_result(
    data_analysis: ChatDataAnalysisFormat,
    result: dict[str, Any],
    filename: str = "database_result.json",
) -> str:
    """Persist a bounded database result through the normal generation layout."""
    if not filename.endswith(".json"):
        filename = f"{filename}.json"
    return data_analysis.save_data(
        json.dumps(result, ensure_ascii=False, default=str, indent=2),
        filename,
    )


__all__ = ["save_database_result"]
