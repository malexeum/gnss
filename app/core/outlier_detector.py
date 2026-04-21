from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd


@dataclass
class OutlierResult:
    df_clean: pd.DataFrame
    df_removed: pd.DataFrame
    df_flagged: pd.DataFrame
    n_input: int
    n_duplicates_removed: int
    n_single_outliers: int
    n_group_removed: int
    n_flagged_loss_of_lock: int
    n_output: int
    window_sec: float
    k_sigma: float
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=== OutlierDetector: итог ===",
            f" Входных эпох : {self.n_input}",
            f" Удалено дублей : {self.n_duplicates_removed}",
            f" Удалено одиночных : {self.n_single_outliers}",
            f" Удалено мультипасинг : {self.n_group_removed}",
            f" Помечено loss_of_lock : {self.n_flagged_loss_of_lock}",
            f" Выходных эпох : {self.n_output}",
            f" Окно фильтра : {self.window_sec:.0f} с",
            f" Порог k : {self.k_sigma}σ (MAD-based)",
        ]
        if self.warnings:
            lines.append(" Предупреждения:")
            for w in self.warnings:
                lines.append(f" ! {w}")
        return "\n".join(lines)


class OutlierDetector:
    def __init__(
        self,
        time_col: str = "utc_time",
        height_col: str = "height",
        k_sigma: float = 4.0,
        window_sec: float = 3600.0,
        min_group: int = 3,
        max_group_epochs: int = 120,
    ):
        self.time_col = time_col
        self.height_col = height_col
        self.k_sigma = k_sigma
        self.window_sec = window_sec
        self.min_group = min_group
        self.max_group_epochs = max_group_epochs

    def _normalize_input(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.time_col not in df.columns:
            raise ValueError(f"Не найден столбец времени '{self.time_col}'.")
        if self.height_col not in df.columns:
            raise ValueError(f"Не найден столбец высоты '{self.height_col}'.")

        out = df.copy()
        out[self.time_col] = pd.to_datetime(out[self.time_col], errors="coerce", utc=True)
        out[self.height_col] = pd.to_numeric(out[self.height_col], errors="coerce")
        if "qc_flag" not in out.columns:
            out["qc_flag"] = 0
        out["qc_flag"] = pd.to_numeric(out["qc_flag"], errors="coerce").fillna(0).astype(int)
        out = out.dropna(subset=[self.time_col, self.height_col]).sort_values(self.time_col).reset_index(drop=True)
        return out

    def _format_time(self, s: pd.Series) -> pd.Series:
        return pd.to_datetime(s, errors="coerce", utc=True).dt.strftime("%Y-%m-%d %H:%M:%S")

    def _estimate_step_sec(self, t: pd.Series) -> float:
        diffs = t.diff().dropna().dt.total_seconds()
        if diffs.empty:
            return 0.0
        mode_vals = diffs.mode()
        return float(mode_vals.iloc[0]) if len(mode_vals) else float(diffs.median())

    def _classify_outliers(self, mask: pd.Series):
        arr = mask.values.astype(bool)
        n = len(arr)
        remove = np.zeros(n, dtype=bool)
        flag = np.zeros(n, dtype=bool)
        single = np.zeros(n, dtype=bool)
        multipath = np.zeros(n, dtype=bool)
        i = 0
        while i < n:
            if arr[i]:
                j = i
                while j < n and arr[j]:
                    j += 1
                group_len = j - i
                if group_len < self.min_group:
                    remove[i:j] = True
                    single[i:j] = True
                elif group_len <= self.max_group_epochs:
                    remove[i:j] = True
                    multipath[i:j] = True
                else:
                    flag[i:j] = True
                i = j
            else:
                i += 1
        return (
            pd.Series(remove, index=mask.index),
            pd.Series(flag, index=mask.index),
            pd.Series(single, index=mask.index),
            pd.Series(multipath, index=mask.index),
        )

    def run(self, df: pd.DataFrame):
        result = self.process_df(df)
        return result.df_clean, result.df_removed, result.df_flagged, result.summary()

    def process_df(self, df: pd.DataFrame) -> OutlierResult:
        df = self._normalize_input(df)
        warnings = []
        n_input = len(df)

        dup_mask = df[self.time_col].duplicated(keep="first")
        n_dup = int(dup_mask.sum())
        df_dups_removed = df.loc[dup_mask].copy()
        if len(df_dups_removed):
            df_dups_removed["remove_reason"] = "duplicate"
            df_dups_removed["deviation_mm"] = np.nan
            df_dups_removed["threshold_mm"] = np.nan
            df = df.loc[~dup_mask].reset_index(drop=True)
            warnings.append(f"Удалено {n_dup} дублирующих эпох.")

        step = self._estimate_step_sec(df[self.time_col])
        h = pd.to_numeric(df[self.height_col], errors="coerce")
        half_win = max(5, int(round(self.window_sec / step / 2))) if step > 0 else 60

        rolling_median = h.rolling(window=2 * half_win + 1, center=True, min_periods=5).median()
        rolling_mad = (h - rolling_median).abs().rolling(window=2 * half_win + 1, center=True, min_periods=5).median()
        threshold = self.k_sigma * 1.4826 * rolling_mad
        deviation = (h - rolling_median).abs()
        outlier_mask = (deviation > threshold).fillna(False)

        remove_mask, flag_mask, single_mask, multipath_mask = self._classify_outliers(outlier_mask)
        n_single = int(single_mask.sum())
        n_group_removed = int(multipath_mask.sum())
        n_flagged = int(flag_mask.sum())

        df_removed_single = df.loc[single_mask].copy()
        if len(df_removed_single):
            df_removed_single["remove_reason"] = "single_outlier"
            df_removed_single["deviation_mm"] = (deviation.loc[single_mask] * 1000.0).round(3)
            df_removed_single["threshold_mm"] = (threshold.loc[single_mask] * 1000.0).round(3)

        df_removed_multipath = df.loc[multipath_mask].copy()
        if len(df_removed_multipath):
            df_removed_multipath["remove_reason"] = "multipath"
            df_removed_multipath["deviation_mm"] = (deviation.loc[multipath_mask] * 1000.0).round(3)
            df_removed_multipath["threshold_mm"] = (threshold.loc[multipath_mask] * 1000.0).round(3)

        df_flagged = df.loc[flag_mask].copy()
        if len(df_flagged):
            df_flagged["flag_reason"] = "loss_of_lock"
            df_flagged["deviation_mm"] = (deviation.loc[flag_mask] * 1000.0).round(3)
            df_flagged["threshold_mm"] = (threshold.loc[flag_mask] * 1000.0).round(3)

        df_clean = df.loc[~remove_mask].copy().reset_index(drop=True)
        df_clean["qc_flag"] = 0
        if len(df_flagged):
            flagged_times = set(df_flagged[self.time_col])
            df_clean.loc[df_clean[self.time_col].isin(flagged_times), "qc_flag"] = 1

        df_clean[self.time_col] = self._format_time(df_clean[self.time_col])
        df_removed = pd.concat(
            [x for x in [df_dups_removed, df_removed_single, df_removed_multipath] if len(x) > 0],
            ignore_index=True,
        ) if any(len(x) > 0 for x in [df_dups_removed, df_removed_single, df_removed_multipath]) else pd.DataFrame()

        if len(df_removed):
            df_removed[self.time_col] = self._format_time(df_removed[self.time_col])
        if len(df_flagged):
            df_flagged[self.time_col] = self._format_time(df_flagged[self.time_col])

        keep_clean = [c for c in [self.time_col, self.height_col, "qc_flag"] if c in df_clean.columns]
        df_clean = df_clean[keep_clean]

        if len(df_removed):
            keep_removed = [c for c in [self.time_col, self.height_col, "qc_flag", "remove_reason", "deviation_mm", "threshold_mm"] if c in df_removed.columns]
            df_removed = df_removed[keep_removed]

        if len(df_flagged):
            keep_flagged = [c for c in [self.time_col, self.height_col, "qc_flag", "flag_reason", "deviation_mm", "threshold_mm"] if c in df_flagged.columns]
            df_flagged = df_flagged[keep_flagged]

        pct_removed = 100.0 * (n_single + n_group_removed) / max(1, n_input - n_dup)
        if pct_removed > 5.0:
            warnings.append(f"Удалено {pct_removed:.1f}% эпох как выбросы — проверьте k_sigma или window_sec.")
        if n_flagged > 0:
            warnings.append(f"Помечено {n_flagged} эпох как loss_of_lock. Они не удалены.")

        return OutlierResult(
            df_clean=df_clean,
            df_removed=df_removed,
            df_flagged=df_flagged,
            n_input=n_input,
            n_duplicates_removed=n_dup,
            n_single_outliers=n_single,
            n_group_removed=n_group_removed,
            n_flagged_loss_of_lock=n_flagged,
            n_output=len(df_clean),
            window_sec=self.window_sec,
            k_sigma=self.k_sigma,
            warnings=warnings,
        )
