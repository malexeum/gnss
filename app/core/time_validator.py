from dataclasses import dataclass, field
from typing import Optional, List

import pandas as pd


@dataclass
class TimeValidationReport:
    source_time_col: str
    detected_format: str
    tz_rule_text: str
    n_epochs: int
    monotonic: bool
    n_duplicates: int
    nominal_step_sec: float
    median_step_sec: float
    n_gaps: int
    max_gap_sec: float
    warnings: List[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [
            "=== TimeValidator Report ===",
            f"Исходный столбец времени : {self.source_time_col}",
            f"Определённый формат : {self.detected_format}",
            f"Правило TZ / UTC : {self.tz_rule_text}",
            f"Всего эпох : {self.n_epochs}",
            f"Монотонность : {'да' if self.monotonic else 'НЕТ'}",
            f"Дублей эпох : {self.n_duplicates}",
            f"Номинальный шаг : {self.nominal_step_sec:.1f} с",
            f"Медианный шаг : {self.median_step_sec:.1f} с",
            f"Разрывов : {self.n_gaps}",
            f"Максимальный разрыв : {self.max_gap_sec:.1f} с ({(self.max_gap_sec / self.nominal_step_sec) if self.nominal_step_sec > 0 else 0:.1f} шагов)",
        ]
        if self.warnings:
            lines.append("Предупреждения:")
            for w in self.warnings:
                lines.append(f"! {w}")
        return "\n".join(lines)


@dataclass
class NormalizedTable:
    df: pd.DataFrame
    nominal_step_sec: float
    median_step_sec: float
    report: TimeValidationReport


class TimeValidator:
    def __init__(self):
        self.tz_rule = "UTC"

    def set_tz_rule(self, rule: str):
        self.tz_rule = rule or "UTC"

    def _detect_format(self, sample: str) -> str:
        sample = str(sample)
        if "/" in sample and "." in sample:
            return "%Y/%m/%d %H:%M:%S.%f"
        if "/" in sample:
            return "%Y/%m/%d %H:%M:%S"
        if "-" in sample and "." in sample:
            return "%Y-%m-%d %H:%M:%S.%f"
        return "%Y-%m-%d %H:%M:%S"

    def _parse_datetime(self, series: pd.Series) -> pd.Series:
        return pd.to_datetime(series, errors="coerce", utc=False)

    def _apply_tz_rule(self, dt: pd.Series) -> tuple[pd.Series, str]:
        rule = str(self.tz_rule or "UTC").strip()
        upper = rule.upper()
        if upper == "UTC":
            if getattr(dt.dt, "tz", None) is None:
                return dt.dt.tz_localize("UTC"), "UTC (UTC) → UTC"
            return dt.dt.tz_convert("UTC"), "UTC (UTC) → UTC"
        if upper in {"LOCAL_MSK+3", "MSK+3", "EUROPE/MOSCOW"}:
            if getattr(dt.dt, "tz", None) is None:
                return dt.dt.tz_localize("Europe/Moscow").dt.tz_convert("UTC"), "LOCAL_MSK+3 (Europe/Moscow) → UTC"
            return dt.dt.tz_convert("UTC"), "LOCAL_MSK+3 (Europe/Moscow) → UTC"
        if getattr(dt.dt, "tz", None) is None:
            return dt.dt.tz_localize(rule).dt.tz_convert("UTC"), f"{rule} ({rule}) → UTC"
        return dt.dt.tz_convert("UTC"), f"{rule} ({rule}) → UTC"

    def validate(self, raw_table, time_col: str, height_col: str, date_col: Optional[str] = None) -> NormalizedTable:
        df = raw_table.df.copy()

        if time_col not in df.columns:
            raise ValueError(f"Колонка времени '{time_col}' не найдена")
        if height_col not in df.columns:
            raise ValueError(f"Колонка высоты '{height_col}' не найдена")

        if date_col and date_col in df.columns:
            time_series = df[date_col].astype(str).str.strip() + " " + df[time_col].astype(str).str.strip()
            source_time_col = f"{date_col}+{time_col}"
        else:
            time_series = df[time_col].astype(str).str.strip()
            source_time_col = time_col

        sample_nonnull = time_series.dropna().astype(str)
        sample_value = sample_nonnull.iloc[0] if len(sample_nonnull) else ""
        detected_format = self._detect_format(sample_value)

        dt = self._parse_datetime(time_series)
        dt_utc, tz_rule_text = self._apply_tz_rule(dt)

        out = pd.DataFrame()
        out["utc_time"] = dt_utc.dt.strftime("%Y-%m-%d %H:%M:%S")
        out["height"] = pd.to_numeric(df[height_col], errors="coerce")

        n_epochs = len(out)
        ts = dt_utc.dropna().sort_values()
        n_duplicates = int(ts.duplicated(keep="first").sum())
        monotonic = bool(dt_utc.dropna().is_monotonic_increasing)
        diffs = ts.diff().dropna().dt.total_seconds()

        if len(diffs) == 0:
            nominal_step = 0.0
            median_step = 0.0
            n_gaps = 0
            max_gap = 0.0
            irregular_count = 0
        else:
            mode_vals = diffs.mode()
            nominal_step = float(mode_vals.iloc[0]) if len(mode_vals) else float(diffs.median())
            median_step = float(diffs.median())
            gap_mask = diffs > (1.5 * nominal_step) if nominal_step > 0 else diffs > 0
            n_gaps = int(gap_mask.sum())
            max_gap = float(diffs.max())
            irregular_count = int((diffs != nominal_step).sum()) if nominal_step > 0 else int((diffs > 0).sum())

        warnings = []
        n_bad_time = int(dt_utc.isna().sum())
        n_bad_height = int(out["height"].isna().sum())
        if n_bad_time > 0:
            warnings.append(f"Не удалось распознать {n_bad_time} временных меток.")
        if n_bad_height > 0:
            warnings.append(f"Не удалось преобразовать {n_bad_height} значений высоты к числу.")
        if n_duplicates > 0:
            warnings.append(f"Найдено {n_duplicates} дублирующих временных меток.")
        if irregular_count > 0 and len(diffs) > 0:
            pct = 100.0 * irregular_count / max(1, len(diffs))
            warnings.append(f"Нерегулярных интервалов: {irregular_count} ({pct:.1f}%). Проверьте ряд перед фильтрацией.")
        if n_gaps > 0:
            warnings.append(f"Найдено {n_gaps} разрывов. Максимальный: {int(max_gap)} с ({max_gap / nominal_step if nominal_step > 0 else 0:.1f} шагов).")

        report = TimeValidationReport(
            source_time_col=source_time_col,
            detected_format=detected_format,
            tz_rule_text=tz_rule_text,
            n_epochs=n_epochs,
            monotonic=monotonic,
            n_duplicates=n_duplicates,
            nominal_step_sec=nominal_step,
            median_step_sec=median_step,
            n_gaps=n_gaps,
            max_gap_sec=max_gap,
            warnings=warnings,
        )
        return NormalizedTable(
            df=out,
            nominal_step_sec=nominal_step,
            median_step_sec=median_step,
            report=report,
        )
