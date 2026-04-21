from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import butter, sosfiltfilt


@dataclass
class ButterworthConfig:
    order: int = 4
    period_minutes: float = 30.0
    time_col: str = "utc_time"
    height_col: str = "height"


def _apply_butterworth(df: pd.DataFrame, time_col: str, height_col: str, order: int, period_minutes: float) -> pd.DataFrame:
    if time_col not in df.columns:
        raise ValueError(f"В таблице нет столбца времени '{time_col}'. Колонки: {list(df.columns)}")
    if height_col not in df.columns:
        raise ValueError(f"В таблице нет столбца высоты '{height_col}'. Колонки: {list(df.columns)}")

    out = df.copy()
    out[time_col] = pd.to_datetime(out[time_col], errors="coerce", utc=True)
    out[height_col] = pd.to_numeric(out[height_col], errors="coerce")
    out = out.dropna(subset=[time_col, height_col]).sort_values(time_col).reset_index(drop=True)

    dt = out[time_col].diff().dropna().dt.total_seconds()
    if dt.empty:
        raise ValueError("Невозможно оценить шаг по времени.")
    step = float(dt.median())
    if step <= 0:
        raise ValueError("Неверный шаг дискретизации (<=0). Нужен равномерный ряд.")

    fs = 1.0 / step
    nyq = 0.5 * fs
    tcut_sec = period_minutes * 60.0
    fc = 1.0 / tcut_sec
    if fc >= nyq:
        raise ValueError(f"Частота среза {fc:.3e} Гц >= Nyquist {nyq:.3e} Гц.")

    wn = fc / nyq
    sos = butter(order, wn, btype="low", output="sos")
    x = out[height_col].to_numpy(dtype=float)
    if len(x) < max(10, order * 3):
        raise ValueError("Слишком короткий ряд для устойчивой фильтрации Баттерворта.")

    y = sosfiltfilt(sos, x)
    out[time_col] = out[time_col].dt.strftime("%Y-%m-%d %H:%M:%S")
    out["height_bw"] = y
    out["residual_bw_mm"] = (out[height_col] - y) * 1000.0

    keep = [c for c in [time_col, height_col, "qc_flag", "height_bw", "residual_bw_mm"] if c in out.columns]
    return out[keep]


def butterworth_on_csv(
    input_csv: str | None = None,
    output_csv: str | None = None,
    df: pd.DataFrame | None = None,
    time_col: str = "utc_time",
    height_col: str = "height",
    order: int = 4,
    period_minutes: float = 30.0,
):
    if df is None and input_csv is None:
        raise ValueError("Нужно передать либо df, либо input_csv.")
    if df is not None and input_csv is not None:
        raise ValueError("Передавайте либо df, либо input_csv, но не оба сразу.")

    src_df = df.copy() if df is not None else pd.read_csv(input_csv)
    out = _apply_butterworth(src_df, time_col=time_col, height_col=height_col, order=order, period_minutes=period_minutes)

    if output_csv:
        Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(output_csv, index=False, encoding="utf-8-sig")
    return out
