from __future__ import annotations

from pathlib import Path
from typing import Optional
import json

import pandas as pd

from app.core.processing_log import ProcessingLog


class DataExporter:
    def __init__(self, units: str = "m"):
        self.units = units

    def export_csv(self, df: pd.DataFrame, path: str | Path, encoding: str = "utf-8-sig") -> Path:
        if df is None:
            raise ValueError("Нет DataFrame для экспорта CSV")
        path = Path(path)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False, encoding=encoding)
        return path

    def export_excel(self, df: pd.DataFrame, path: str | Path) -> Path:
        if df is None:
            raise ValueError("Нет DataFrame для экспорта Excel")
        path = Path(path)
        if path.suffix.lower() not in (".xlsx", ".xls"):
            path = path.with_suffix(".xlsx")
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(path, index=False)
        return path

    def export_log_text(self, log: ProcessingLog, path: str | Path) -> Path:
        if not isinstance(log, ProcessingLog):
            raise TypeError("log должен быть экземпляром ProcessingLog")
        return log.save(path, fmt="txt")

    def export_log_json(self, log: ProcessingLog, path: str | Path) -> Path:
        if not isinstance(log, ProcessingLog):
            raise TypeError("log должен быть экземпляром ProcessingLog")
        return log.save(path, fmt="json")

    def export_json(self, data: dict, path: str | Path) -> Path:
        path = Path(path)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def export_stage_bundle(
        self,
        df: pd.DataFrame,
        base_path: str | Path,
        log: Optional[ProcessingLog] = None,
        export_excel: bool = False,
    ) -> dict:
        base_path = Path(base_path)
        base_path.parent.mkdir(parents=True, exist_ok=True)

        out = {}
        out["csv"] = str(self.export_csv(df, base_path.with_suffix(".csv")))

        if export_excel:
            out["xlsx"] = str(self.export_excel(df, base_path.with_suffix(".xlsx")))

        if log is not None:
            out["log_txt"] = str(self.export_log_text(log, base_path.with_name(base_path.stem + "_log.txt")))
            out["log_json"] = str(self.export_log_json(log, base_path.with_name(base_path.stem + "_log.json")))

        return out
