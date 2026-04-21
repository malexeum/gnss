from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

MIN_WINDOW = 5
MAX_WINDOW = 39
MIN_THRESHOLD_MM = 2.0
MAX_THRESHOLD_MM = 99.0
DEFAULT_WINDOW = 9
DEFAULT_THRESHOLD_MM = 5.0


@dataclass
class MedianFilterConfig:
    value_column: str = "height_bw"
    output_column: str = "height_med"
    residual_column: str = "residual_med_mm"
    outlier_flag_column: str = "is_median_outlier"
    local_median_column: str = "median_local"
    window_points: int = DEFAULT_WINDOW
    threshold_mm: float = DEFAULT_THRESHOLD_MM

    def validate(self):
        if not isinstance(self.window_points, int):
            raise ValueError(f"Окно должно быть целым числом. Получено: {self.window_points}")
        if self.window_points < MIN_WINDOW or self.window_points > MAX_WINDOW:
            raise ValueError(
                f"Окно должно быть в диапазоне {MIN_WINDOW}..{MAX_WINDOW} точек. Получено: {self.window_points}"
            )
        if self.window_points % 2 == 0:
            raise ValueError(
                f"Окно должно быть нечётным числом точек: 5, 7, 9, ..., 39. Получено: {self.window_points}"
            )
        if not (MIN_THRESHOLD_MM <= float(self.threshold_mm) <= MAX_THRESHOLD_MM):
            raise ValueError(
                f"Порог должен быть в диапазоне {MIN_THRESHOLD_MM}..{MAX_THRESHOLD_MM} мм. Получено: {self.threshold_mm}"
            )


class MedianResidualFilter:
    def __init__(self, config: Optional[MedianFilterConfig] = None):
        self.config = config or MedianFilterConfig()
        self.config.validate()

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        cfg = self.config
        if cfg.value_column not in df.columns:
            raise ValueError(f"В таблице нет столбца '{cfg.value_column}'")

        out = df.copy()
        if "utc_time" in out.columns:
            out["utc_time"] = pd.to_datetime(out["utc_time"], errors="coerce", utc=True).dt.strftime("%Y-%m-%d %H:%M:%S")

        y = pd.to_numeric(out[cfg.value_column], errors="coerce")
        median_local = y.rolling(window=cfg.window_points, center=True, min_periods=1).median()
        raw_residual_mm = (y - median_local) * 1000.0
        is_outlier = raw_residual_mm.abs() > float(cfg.threshold_mm)
        height_med = y.where(~is_outlier, median_local)

        out[cfg.local_median_column] = median_local
        out[cfg.output_column] = height_med
        out[cfg.residual_column] = (y - height_med) * 1000.0
        out[cfg.outlier_flag_column] = is_outlier.fillna(False)

        keep = [
            c for c in [
                "utc_time",
                "height",
                "qc_flag",
                "height_bw",
                "residual_bw_mm",
                cfg.output_column,
                cfg.residual_column,
                cfg.outlier_flag_column,
                cfg.local_median_column,
            ] if c in out.columns
        ]
        return out[keep]

    @staticmethod
    def summary(df: pd.DataFrame, output_column: str = "height_med") -> dict:
        total = len(df)
        replaced = int(df.get("is_median_outlier", pd.Series(dtype=bool)).fillna(False).sum())
        valid = pd.to_numeric(df.get(output_column, pd.Series(dtype=float)), errors="coerce").dropna()
        residual = pd.to_numeric(df.get("residual_med_mm", pd.Series(dtype=float)), errors="coerce").dropna()
        return {
            "n_total": total,
            "n_replaced": replaced,
            "share_replaced_percent": round((replaced / total) * 100.0, 4) if total else 0.0,
            "output_mean_m": float(valid.mean()) if len(valid) else np.nan,
            "output_std_m": float(valid.std(ddof=1)) if len(valid) > 1 else np.nan,
            "residual_median_abs_mm": float(residual.abs().median()) if len(residual) else np.nan,
            "residual_max_abs_mm": float(residual.abs().max()) if len(residual) else np.nan,
        }


def apply_median_filter(
    df: pd.DataFrame,
    value_column: str = "height_bw",
    output_column: str = "height_med",
    residual_column: str = "residual_med_mm",
    window_points: int = DEFAULT_WINDOW,
    threshold_mm: float = DEFAULT_THRESHOLD_MM,
) -> pd.DataFrame:
    cfg = MedianFilterConfig(
        value_column=value_column,
        output_column=output_column,
        residual_column=residual_column,
        window_points=window_points,
        threshold_mm=threshold_mm,
    )
    return MedianResidualFilter(cfg).apply(df)
