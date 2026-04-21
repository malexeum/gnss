"""
DataImporter v0.3
- Единый контракт импорта для GNSS: utc_time, height
- Поддержка CSV/TXT/TSV/XLS/XLSX/POS
- Автосклейка date + time -> utc_time
- Детектирование системы времени и кандидатов столбцов
- Без преобразования локального времени в UTC: это обязанность TimeValidator
"""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import chardet
import pandas as pd

SUPPORTED_FORMATS = [".csv", ".txt", ".tsv", ".xls", ".xlsx", ".pos"]


def _norm(name: str) -> str:
    s = str(name).strip().lower()
    for ch in (" ", "-", ".", "/", "\\", "(", ")", "[", "]"):
        s = s.replace(ch, "_")
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")


def _find_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    norm_map = {_norm(c): c for c in df.columns}
    for cand in candidates:
        key = _norm(cand)
        if key in norm_map:
            return norm_map[key]
    return None


@dataclass
class ImportSchema:
    time_col: str = ""
    height_col: str = ""
    separator: str = ","
    encoding: str = "utf-8"
    skiprows: int = 0
    decimal: str = "."
    source_format: str = ""
    extra_cols: list[str] = field(default_factory=list)
    date_col: str = ""
    time_only_col: str = ""
    time_source_kind: str = "unknown"
    time_system: str = "UNKNOWN"
    detected_time_col: str = ""
    detected_height_col: str = ""
    pos_time_scale: str = "UNKNOWN"


@dataclass
class RawTable:
    df: pd.DataFrame
    filepath: str
    source_format: str
    schema: ImportSchema
    n_rows: int
    n_cols: int
    column_names: list[str]
    warnings: list[str] = field(default_factory=list)


class DataImporter:
    SUPPORTED_FORMATS = SUPPORTED_FORMATS

    def __init__(self):
        self.schema = ImportSchema()
        self._raw_table: Optional[RawTable] = None

    @property
    def raw_table(self) -> Optional[RawTable]:
        return self._raw_table

    def load(self, filepath: str, schema: Optional[ImportSchema] = None) -> RawTable:
        filepath = str(filepath)
        self._validate_path(filepath)
        ext = Path(filepath).suffix.lower()

        self.schema = schema if schema else ImportSchema()
        self.schema.source_format = ext
        if ext in (".csv", ".txt", ".tsv", ".pos"):
            self.schema.encoding = self._detect_encoding(filepath)
            self.schema.separator = self._detect_separator(filepath, self.schema.encoding, ext)

        df = self._read_file(filepath, ext)
        df = self._merge_date_time_cols(df)
        self._autodetect_core_columns(df)
        warnings = self._basic_checks(df)

        self._raw_table = RawTable(
            df=df,
            filepath=filepath,
            source_format=ext,
            schema=self.schema,
            n_rows=len(df),
            n_cols=len(df.columns),
            column_names=list(df.columns),
            warnings=warnings,
        )
        return self._raw_table

    def preview(self, filepath: str, n: int = 20) -> pd.DataFrame:
        filepath = str(filepath)
        self._validate_path(filepath)
        ext = Path(filepath).suffix.lower()
        if ext == ".pos":
            self.schema.encoding = self._detect_encoding(filepath)
            df = self._read_pos(filepath).head(n)
        elif ext in (".csv", ".txt", ".tsv"):
            enc = self._detect_encoding(filepath)
            sep = self._detect_separator(filepath, enc, ext)
            df = pd.read_csv(filepath, sep=sep, encoding=enc, nrows=n, engine="python", dtype=str)
        elif ext in (".xls", ".xlsx"):
            df = pd.read_excel(filepath, nrows=n, dtype=str)
        else:
            raise ValueError(f"Неподдерживаемый формат: {ext}")
        df.columns = [str(c).strip() for c in df.columns]
        df = self._merge_date_time_cols(df)
        return df.head(n)

    def get_column_names(self) -> list[str]:
        if self._raw_table is None:
            raise RuntimeError("Файл не загружен. Вызовите load() сначала.")
        return self._raw_table.column_names

    def set_columns(self, time_col: str, height_col: str, extra_cols: Optional[list[str]] = None) -> None:
        if self._raw_table:
            real_time = _find_col(self._raw_table.df, [time_col, "utc_time", "utc_time_utc", "datetime_utc"])
            real_height = _find_col(self._raw_table.df, [height_col, "height", "height_m"])
            real_time = real_time or time_col
            real_height = real_height or height_col
        else:
            real_time, real_height = time_col, height_col

        self.schema.time_col = real_time
        self.schema.height_col = real_height
        self.schema.detected_time_col = real_time
        self.schema.detected_height_col = real_height
        self.schema.extra_cols = extra_cols or []

        if self._raw_table:
            self._raw_table.schema = self.schema
            cols = self._raw_table.column_names
            for col in [real_time, real_height] + (extra_cols or []):
                if col not in cols:
                    raise ValueError(f"Столбец '{col}' не найден. Доступные: {cols}")

    def save_schema(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self.schema), f, ensure_ascii=False, indent=2)

    def load_schema(self, path: str) -> ImportSchema:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.schema = ImportSchema(**data)
        return self.schema

    def detect_separator(self, filepath: str) -> str:
        enc = self._detect_encoding(filepath)
        ext = Path(filepath).suffix.lower()
        return self._detect_separator(filepath, enc, ext)

    def _validate_path(self, filepath: str) -> None:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл не найден: {filepath}")
        ext = Path(filepath).suffix.lower()
        if ext not in SUPPORTED_FORMATS:
            raise ValueError(f"Формат '{ext}' не поддерживается. Допустимые: {SUPPORTED_FORMATS}")

    def _detect_encoding(self, filepath: str, sample_bytes: int = 32768) -> str:
        with open(filepath, "rb") as f:
            raw = f.read(sample_bytes)
        result = chardet.detect(raw)
        enc = (result.get("encoding") or "utf-8").lower().replace("-", "_")
        if enc in ("ascii", "utf_8_sig"):
            enc = "utf-8"
        return enc

    def _detect_separator(self, filepath: str, encoding: str, ext: str = "", sample_lines: int = 10) -> str:
        if ext == ".pos":
            return r"\s+"
        candidates = [";", ",", "\t", " "]
        best_sep = ","
        best_score = 0
        try:
            with open(filepath, "r", encoding=encoding, errors="replace") as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= sample_lines + 5:
                        break
                    stripped = line.strip()
                    if stripped and not stripped.startswith(("%", "#", "!")):
                        lines.append(stripped)
            lines = lines[:sample_lines]
            for sep in candidates:
                counts = [len(line.split(sep)) for line in lines if line]
                if not counts:
                    continue
                median_count = sorted(counts)[len(counts) // 2]
                stability = sum(1 for c in counts if c == median_count)
                score = median_count * stability
                if score > best_score and median_count > 1:
                    best_score = score
                    best_sep = sep
        except Exception:
            pass
        return best_sep

    def _find_pos_header_line(self, filepath: str, encoding: str) -> tuple[int, str]:
        header_idx = 0
        pos_time_scale = "UNKNOWN"
        with open(filepath, "r", encoding=encoding, errors="replace") as f:
            for i, line in enumerate(f):
                s = line.strip()
                low = s.lower()
                if s.startswith("%") and ("height(" in low) and ("utc" in low or "gpst" in low):
                    header_idx = i
                    if "gpst" in low:
                        pos_time_scale = "GPST"
                    elif "utc" in low:
                        pos_time_scale = "UTC"
                    # нашли первый подходящий заголовок — выходим
                    break
        return header_idx, pos_time_scale

    def _read_file(self, filepath: str, ext: str) -> pd.DataFrame:
        if ext == ".pos":
            return self._read_pos(filepath)
        if ext in (".csv", ".txt", ".tsv"):
            df = pd.read_csv(
                filepath,
                sep=self.schema.separator,
                encoding=self.schema.encoding,
                skiprows=self.schema.skiprows,
                decimal=self.schema.decimal,
                dtype=str,
                engine="python",
            )
        elif ext in (".xls", ".xlsx"):
            df = pd.read_excel(filepath, skiprows=self.schema.skiprows, dtype=str)
        else:
            raise ValueError(f"Неподдерживаемый формат: {ext}")
        df.dropna(how="all", axis=1, inplace=True)
        df.dropna(how="all", axis=0, inplace=True)
        df.reset_index(drop=True, inplace=True)
        df.columns = [str(c).strip() for c in df.columns]
        return df

    def _read_pos(self, filepath: str) -> pd.DataFrame:
        enc = self.schema.encoding or self._detect_encoding(filepath)
        header_idx, pos_time_scale = self._find_pos_header_line(filepath, enc)
        self.schema.pos_time_scale = pos_time_scale
        self.schema.time_system = pos_time_scale if pos_time_scale != "UNKNOWN" else self.schema.time_system
        self.schema.time_source_kind = "pos"

        df = pd.read_csv(
            filepath,
            sep=r"\s+",
            encoding=enc,
            skiprows=header_idx + 1,
            header=None,
            dtype=str,
            engine="python",
        )
        df.dropna(how="all", axis=1, inplace=True)
        df.dropna(how="all", axis=0, inplace=True)
        df.reset_index(drop=True, inplace=True)

        if df.shape[1] < 5:
            raise ValueError(f"Не удалось корректно разобрать POS-файл: найдено только {df.shape[1]} столбцов")

        base_cols = [
            "date", "time", "latitude_deg", "longitude_deg", "height",
            "Q", "ns", "sdn_m", "sde_m", "sdu_m", "sdne_m", "sdeu_m", "sdun_m",
            "age_s", "ratio"
        ]
        n = df.shape[1]
        cols = base_cols[:n] + [f"extra_{i}" for i in range(max(0, n - len(base_cols)))]
        df.columns = cols[:n]

        if "date" in df.columns and "time" in df.columns:
            df.insert(0, "utc_time", df["date"].astype(str).str.strip() + " " + df["time"].astype(str).str.strip())

        return df

    def _merge_date_time_cols(self, df: pd.DataFrame) -> pd.DataFrame:
        existing = _find_col(df, ["utc_time", "utc_time_utc", "datetime_utc", "datetime"])
        if existing and existing != "utc_time":
            df = df.copy()
            df.insert(0, "utc_time", df[existing].astype(str).str.strip())
            self.schema.time_source_kind = "single_column"
            self.schema.detected_time_col = existing
            return df
        if existing == "utc_time":
            self.schema.time_source_kind = "single_column"
            self.schema.detected_time_col = "utc_time"
            return df

        date_col = _find_col(df, ["date", "дата", "date_utc", "date_local"])
        time_col = _find_col(df, ["time_local", "time_utc", "time", "время"])
        if date_col and time_col and date_col != time_col:
            combined = df[date_col].astype(str).str.strip() + " " + df[time_col].astype(str).str.strip()
            combined = combined.str.replace("/", "-", regex=False)
            df = df.copy()
            df.insert(0, "utc_time", combined)
            self.schema.date_col = date_col
            self.schema.time_only_col = time_col
            self.schema.detected_time_col = "utc_time"
            self.schema.time_source_kind = "date_time_split"
        return df

    def _autodetect_core_columns(self, df: pd.DataFrame) -> None:
        time_col = _find_col(df, ["utc_time", "utc_time_utc", "datetime_utc", "datetime"])
        height_col = _find_col(df, ["height", "height_m", "heightm", "h", "ellipsoidal_height"])

        if time_col and not self.schema.time_col:
            self.schema.time_col = time_col
            self.schema.detected_time_col = time_col
        if height_col and not self.schema.height_col:
            self.schema.height_col = height_col
            self.schema.detected_height_col = height_col

        if self.schema.time_system == "UNKNOWN":
            note_col = _find_col(df, ["note", "comment", "примечание"])
            if note_col:
                notes = df[note_col].astype(str).str.upper()
                if notes.str.contains("MSK\\+3", regex=True).any():
                    self.schema.time_system = "LOCAL_MSK+3"
                elif notes.str.contains("UTC", regex=False).any():
                    self.schema.time_system = "UTC"
            if self.schema.time_system == "UNKNOWN" and self.schema.time_source_kind == "pos":
                self.schema.time_system = self.schema.pos_time_scale or "UNKNOWN"

    def _basic_checks(self, df: pd.DataFrame) -> list[str]:
        warnings = []
        if len(df) == 0:
            warnings.append("ПРЕДУПРЕЖДЕНИЕ: файл пустой.")
        if len(df.columns) < 2:
            warnings.append("ПРЕДУПРЕЖДЕНИЕ: найден только 1 столбец. Возможно, неверный разделитель.")
        if len(df) < 10:
            warnings.append(f"ПРЕДУПРЕЖДЕНИЕ: очень мало строк ({len(df)}). Проверьте skiprows и формат.")
        if not _find_col(df, ["utc_time", "utc_time_utc", "datetime_utc", "datetime"]):
            warnings.append("Не найден явный столбец времени или пара date+time.")
        if not _find_col(df, ["height", "height_m", "heightm", "h", "ellipsoidal_height"]):
            warnings.append("Не найден явный столбец высоты.")
        return warnings
