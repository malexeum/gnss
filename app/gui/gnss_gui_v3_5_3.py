import sys
from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QDoubleSpinBox, QSpinBox, QSplitter,
    QGroupBox, QCheckBox, QComboBox
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.dates as mdates

from app.core.data_importer import DataImporter
from app.core.time_validator import TimeValidator
from app.core.outlier_detector import OutlierDetector
from app.core.butterworth_filter import butterworth_on_csv
from app.core.median_filter import MedianResidualFilter, MedianFilterConfig
from app.core.processing_log import ProcessingLog
from app.core.data_exporter import DataExporter


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None, width=9, height=6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)


class GNSSMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GNSS Processing GUI v3.5.4")
        self.resize(1720, 1020)

        self.current_file = None
        self.current_dir = None

        self.df_raw = None
        self.df_validated = None
        self.df_clean = None
        self.df_removed = None
        self.df_flagged = None
        self.df_bw = None
        self.df_med = None

        self.time_col = None
        self.height_col = None
        self.y_mode = "mean_mm"
        self.x_scale_mode = "all"

        self.log_model = ProcessingLog(version="0.3.5.4")
        self.exporter = DataExporter(units="m")
        self.importer = DataImporter()
        self.time_validator = TimeValidator()

        self._build_ui()
        self.setStyleSheet("""
            QGroupBox {
                font-weight: 600;
                border: 1px solid #cfcfcf;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px 0 4px;
                font-weight: 700;
            }
        """)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(14)

        import_group = QGroupBox("Импорт")
        import_layout = QVBoxLayout(import_group)
        import_layout.setSpacing(10)

        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Выберите файл CSV/TXT/TSV/XLS/XLSX/POS")
        btn_browse = QPushButton("Обзор...")
        btn_browse.clicked.connect(self.choose_file)
        file_row.addWidget(self.file_edit)
        file_row.addWidget(btn_browse)

        self.time_col_edit = QLineEdit()
        self.height_col_edit = QLineEdit()

        import_form = QFormLayout()
        import_form.setVerticalSpacing(10)
        import_form.addRow("Колонка времени:", self.time_col_edit)
        import_form.addRow("Колонка высоты:", self.height_col_edit)

        import_layout.addLayout(file_row)
        import_layout.addLayout(import_form)

        clean_group = QGroupBox("Очистка выбросов и пропусков")
        clean_form = QFormLayout(clean_group)
        clean_form.setVerticalSpacing(10)

        self.k_sigma_spin = QDoubleSpinBox()
        self.k_sigma_spin.setRange(0.1, 20.0)
        self.k_sigma_spin.setDecimals(2)
        self.k_sigma_spin.setValue(4.0)

        self.window_sec_spin = QSpinBox()
        self.window_sec_spin.setRange(60, 864000)
        self.window_sec_spin.setSingleStep(60)
        self.window_sec_spin.setValue(3600)

        self.min_group_spin = QSpinBox()
        self.min_group_spin.setRange(1, 10000)
        self.min_group_spin.setValue(3)

        self.max_group_spin = QSpinBox()
        self.max_group_spin.setRange(1, 100000)
        self.max_group_spin.setValue(120)

        clean_form.addRow("k_sigma:", self.k_sigma_spin)
        clean_form.addRow("Локальное окно, с:", self.window_sec_spin)
        clean_form.addRow("min_group:", self.min_group_spin)
        clean_form.addRow("max_group_epochs:", self.max_group_spin)

        butter_group = QGroupBox("Фильтр Баттерворта")
        butter_form = QFormLayout(butter_group)
        butter_form.setVerticalSpacing(10)

        self.order_spin = QSpinBox()
        self.order_spin.setRange(1, 10)
        self.order_spin.setValue(4)

        self.period_spin = QSpinBox()
        self.period_spin.setRange(1, 14400)
        self.period_spin.setValue(30)

        butter_form.addRow("Порядок:", self.order_spin)
        butter_form.addRow("Период, мин:", self.period_spin)

        median_group = QGroupBox("Медианный фильтр")
        median_form = QFormLayout(median_group)
        median_form.setVerticalSpacing(10)

        self.window_points_spin = QSpinBox()
        self.window_points_spin.setRange(5, 39)
        self.window_points_spin.setSingleStep(2)
        self.window_points_spin.setValue(9)

        self.threshold_mm_spin = QDoubleSpinBox()
        self.threshold_mm_spin.setRange(2.0, 99.0)
        self.threshold_mm_spin.setDecimals(1)
        self.threshold_mm_spin.setSingleStep(0.5)
        self.threshold_mm_spin.setValue(5.0)

        self.cb_median_live = QCheckBox("Пересчёт median на лету")
        self.cb_median_live.setChecked(True)
        self.window_points_spin.valueChanged.connect(self._median_live_recalc)
        self.threshold_mm_spin.valueChanged.connect(self._median_live_recalc)

        median_form.addRow("Окно, точек:", self.window_points_spin)
        median_form.addRow("Порог, мм:", self.threshold_mm_spin)
        median_form.addRow("", self.cb_median_live)

        left_layout.addWidget(import_group)
        left_layout.addWidget(clean_group)
        left_layout.addWidget(butter_group)
        left_layout.addWidget(median_group)
        left_layout.addStretch(1)

        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setSpacing(10)

        actions_group = QGroupBox("Действия")
        actions_layout = QHBoxLayout(actions_group)
        actions_layout.setSpacing(8)

        btn_load = QPushButton("Загрузить")
        btn_load.clicked.connect(self.load_file)

        btn_validate = QPushButton("Проверить время")
        btn_validate.clicked.connect(self.validate_time)

        btn_outlier = QPushButton("Очистить выбросы")
        btn_outlier.clicked.connect(self.run_outlier)

        btn_bw = QPushButton("Фильтр Баттерворта")
        btn_bw.clicked.connect(self.run_butterworth)

        btn_med = QPushButton("Медианный фильтр")
        btn_med.clicked.connect(self.run_median)

        btn_plot = QPushButton("Обновить график")
        btn_plot.clicked.connect(self.plot_layers)

        btn_save_csv = QPushButton("Сохранить CSV")
        btn_save_csv.clicked.connect(self.save_current_csv)

        btn_save_jpg = QPushButton("Сохранить JPG")
        btn_save_jpg.clicked.connect(self.save_current_jpg)

        btn_save_bundle = QPushButton("Сохранить комплект")
        btn_save_bundle.clicked.connect(self.save_bundle)

        for btn in [
            btn_load, btn_validate, btn_outlier, btn_bw, btn_med,
            btn_plot, btn_save_csv, btn_save_jpg, btn_save_bundle
        ]:
            actions_layout.addWidget(btn)
        actions_layout.addStretch(1)

        layers_group = QGroupBox("Слои и режим графика")
        layers_layout = QHBoxLayout(layers_group)
        layers_layout.setSpacing(12)

        self.cb_raw = QCheckBox("Исходный")
        self.cb_valid = QCheckBox("После проверки времени")
        self.cb_clean = QCheckBox("После очистки")
        self.cb_bw = QCheckBox("Баттерворт")
        self.cb_med = QCheckBox("Медианный")

        self.cb_raw.setChecked(True)

        for cb in [self.cb_raw, self.cb_valid, self.cb_clean, self.cb_bw, self.cb_med]:
            cb.stateChanged.connect(self.plot_layers)
            layers_layout.addWidget(cb)

        layers_layout.addSpacing(24)
        layers_layout.addWidget(QLabel("Y:"))

        self.y_mode_combo = QComboBox()
        self.y_mode_combo.addItems(["Абсолютная высота, м", "Отклонение от среднего, мм"])
        self.y_mode_combo.setCurrentIndex(1)
        self.y_mode_combo.currentIndexChanged.connect(self._on_y_mode_changed)
        layers_layout.addWidget(self.y_mode_combo)

        layers_layout.addSpacing(16)
        layers_layout.addWidget(QLabel("X:"))

        self.x_scale_combo = QComboBox()
        self.x_scale_combo.addItems(["Весь график", "1 день", "1 неделя", "Диапазон"])
        self.x_scale_combo.setCurrentText("Весь график")
        self.x_scale_combo.currentIndexChanged.connect(self._on_x_scale_changed)
        layers_layout.addWidget(self.x_scale_combo)

        layers_layout.addSpacing(12)
        layers_layout.addWidget(QLabel("С:"))

        self.range_from_edit = QDateTimeEdit()
        self.range_from_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.range_from_edit.setCalendarPopup(True)
        self.range_from_edit.setEnabled(False)
        self.range_from_edit.dateTimeChanged.connect(self._apply_manual_range_live)
        layers_layout.addWidget(self.range_from_edit)

        layers_layout.addWidget(QLabel("По:"))

        self.range_to_edit = QDateTimeEdit()
        self.range_to_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.range_to_edit.setCalendarPopup(True)
        self.range_to_edit.setEnabled(False)
        self.range_to_edit.dateTimeChanged.connect(self._apply_manual_range_live)
        layers_layout.addWidget(self.range_to_edit)

        layers_layout.addStretch(1)

        self.canvas = MplCanvas(self)
        self.toolbar = NavigationToolbar(self.canvas, self)

        center_layout.addWidget(actions_group)
        center_layout.addWidget(layers_group)
        center_layout.addWidget(self.toolbar)
        center_layout.addWidget(self.canvas)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.addWidget(QLabel("Подробный журнал"))

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        right_layout.addWidget(self.log_text)

        splitter.addWidget(left_widget)
        splitter.addWidget(center_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([390, 980, 380])

    def log(self, message: str):
        self.log_text.append(str(message))

    def log_step(self, module: str, summary: str, params=None, level: str = "INFO"):
        params = params or {}
        self.log_model.add(module=module, summary=summary, params=params, level=level)
        self.log(f"[{level}] {module}: {summary}")
        if params:
            self.log("    " + ", ".join(f"{k}={v}" for k, v in params.items()))

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _input_data_dir(self) -> Path:
        candidate = self._project_root() / "data" / "input"
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    def _base_output_dir(self) -> Path:
        base = self._project_root() / "data" / "output"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _csv_output_dir(self) -> Path:
        p = self._base_output_dir() / "csv"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _jpg_output_dir(self) -> Path:
        p = self._base_output_dir() / "jpg"
        p.mkdir(parents=True, exist_ok=True)
        return p
		
    def _final_export_dir(self) -> Path:
        p = self._base_output_dir() / "final export"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _log_output_dir(self) -> Path:
        p = self._base_output_dir() / "logs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def choose_file(self):
        start_dir = str(self.current_dir) if self.current_dir else str(self._input_data_dir())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать GNSS файл",
            start_dir,
            "Data files (*.csv *.txt *.tsv *.xls *.xlsx *.pos);;All files (*.*)"
        )
        if not file_path:
            return

        self.current_file = Path(file_path)
        self.current_dir = self.current_file.parent
        self.file_edit.setText(str(self.current_file))

        self.time_col_edit.clear()
        self.height_col_edit.clear()
        self.time_col = None
        self.height_col = None

        self.df_raw = None
        self.df_validated = None
        self.df_clean = None
        self.df_removed = None
        self.df_flagged = None
        self.df_bw = None
        self.df_med = None

        self.log_model.clear()
        self.log_model.version = "0.3.5.2"
        self.log_text.clear()
        self.log_step("session", "Начата новая сессия обработки", {"file": str(self.current_file)})

    def _auto_guess_columns(self, df: pd.DataFrame):
        cols = list(df.columns)
        self.log(f"Автоопределение колонок. Колонки: {cols}")

        def norm(s: str) -> str:
            s = str(s).strip().lower()
            for ch in [" ", "-", "/", "\\", ".", ":", ";", "(", ")", "[", "]"]:
                s = s.replace(ch, "")
            s = s.replace("ё", "е")
            return s

        normalized = {norm(c): c for c in cols}

        time_candidates = [
            "utc_time_utc", "utc_time", "datetime_utc", "datetime",
            "датаивремя", "датавремя", "дата_и_время",
            "time_utc", "gpst", "utc", "date", "datetimeutc"
        ]

        height_candidates = [
            "height_m", "height", "высотам", "высота", "h"
        ]

        def find_col(cands):
            for cand in cands:
                key = norm(cand)
                if key in normalized:
                    return normalized[key]
            return None

        time_col = find_col(time_candidates)
        height_col = find_col(height_candidates)

        return time_col, height_col

    def load_file(self):
        try:
            if not self.current_file:
                QMessageBox.warning(self, "Нет файла", "Сначала выберите файл.")
                return

            self.log("=== Импорт ===")
            raw_table = self.importer.load(str(self.current_file))
            self.df_raw = raw_table.df
            df_raw = self.df_raw

            if "utc_time" in df_raw.columns:
                t_all = pd.to_datetime(df_raw["utc_time"], errors="coerce", utc=True).dt.tz_localize(None)
                t_all = t_all.dropna()
                if len(t_all) > 0:
                    self.log(f"Импортирован диапазон utc_time: {t_all.min()} .. {t_all.max()} (N={len(t_all)})")
			
            manual_time = self.time_col_edit.text().strip()
            manual_height = self.height_col_edit.text().strip()

            if manual_time and manual_height:
                self.importer.set_columns(manual_time, manual_height)
                self.time_col = self.importer.schema.time_col
                self.height_col = self.importer.schema.height_col
            else:
                time_col, height_col = self._auto_guess_columns(df_raw)
                if not time_col:
                    raise ValueError(f"Не найдена временная колонка. Столбцы: {list(df_raw.columns)}")
                if not height_col:
                    raise ValueError(f"Не найдена колонка высоты. Столбцы: {list(df_raw.columns)}")
                self.importer.set_columns(time_col, height_col)
                self.time_col = time_col
                self.height_col = height_col
                self.time_col_edit.setText(self.time_col)
                self.height_col_edit.setText(self.height_col)

            self.log_step(
            "import",
            "Импорт завершён успешно",
            {"rows": len(df_raw), "time_col": self.time_col, "height_col": self.height_col}
            )

            self._sync_range_editors()
            self.plot_layers()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", str(e))
            self.log_model.add_error(str(e), module="import")
            self.log(f"Ошибка импорта: {e}")

    def validate_time(self):
        try:
            if self.df_raw is None:
                QMessageBox.warning(self, "Нет данных", "Сначала загрузите файл.")
                return

            normalized = self.time_validator.validate(
                raw_table=self.importer._raw_table,
                time_col=self.time_col,
                height_col=self.height_col,
                date_col=None
            )
            self.df_validated = normalized.df

            self.log("=== Проверка времени ===")
            self.log(normalized.report.to_text())
            self.log_step("time_validator", "Проверка времени завершена", {"rows_out": len(self.df_validated)})
            self.plot_layers()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка валидации", str(e))
            self.log_model.add_error(str(e), module="time_validator")
            self.log(f"Ошибка валидации: {e}")

    def run_outlier(self):
        try:
            if self.df_validated is None:
                QMessageBox.warning(self, "Нет данных", "Сначала выполните проверку времени.")
                return

            self.log("=== Очистка выбросов ===")
            time_col = "utc_time" if "utc_time" in self.df_validated.columns else self.time_col
            height_col = "height" if "height" in self.df_validated.columns else self.height_col

            otl = OutlierDetector(
                time_col=time_col,
                height_col=height_col,
                k_sigma=self.k_sigma_spin.value(),
                window_sec=self.window_sec_spin.value(),
                min_group=self.min_group_spin.value(),
                max_group_epochs=self.max_group_spin.value()
            )

            clean, removed, flagged, report = otl.run(self.df_validated)
            self.df_clean = clean
            self.df_removed = removed
            self.df_flagged = flagged

            self.log(str(report))
            self.log_step(
                "outlier_detector",
                "Очистка выбросов завершена",
                {
                    "rows_clean": len(clean) if clean is not None else 0,
                    "rows_removed": len(removed) if removed is not None else 0,
                    "k_sigma": self.k_sigma_spin.value(),
                    "window_sec": self.window_sec_spin.value()
                }
            )
            self.plot_layers()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка очистки выбросов", str(e))
            self.log_model.add_error(str(e), module="outlier_detector")
            self.log(f"Ошибка очистки выбросов: {e}")

    def _resolve_time_height_cols(self, df: pd.DataFrame):
        time_col = "utc_time" if "utc_time" in df.columns else self.time_col
        height_col = "height" if "height" in df.columns else self.height_col
        return time_col, height_col

    def _get_processing_input(self):
        if self.df_bw is not None:
            return "bw", self.df_bw
        if self.df_clean is not None:
            return "clean", self.df_clean
        if self.df_validated is not None:
            return "validated", self.df_validated
        if self.df_raw is not None:
            return "raw", self.df_raw
        return None, None

    def _get_display_table(self):
        if self.cb_med.isChecked() and self.df_med is not None:
            return "med", self.df_med
        if self.cb_bw.isChecked() and self.df_bw is not None:
            return "bw", self.df_bw
        if self.cb_clean.isChecked() and self.df_clean is not None:
            return "clean", self.df_clean
        if self.cb_valid.isChecked() and self.df_validated is not None:
            return "validated", self.df_validated
        if self.cb_raw.isChecked() and self.df_raw is not None:
            return "raw", self.df_raw
        return self._get_processing_input()

def _get_plot_time_bounds(self):
    candidates = [self.df_med, self.df_bw, self.df_clean, self.df_validated, self.df_raw]
    for df in candidates:
        if df is None or df.empty:
            continue
        time_col = "utc_time" if "utc_time" in df.columns else self.time_col
        if not time_col or time_col not in df.columns:
            continue
        t = pd.to_datetime(df[time_col], errors="coerce", utc=True).dt.tz_localize(None)
        t = t.dropna()
        if len(t) > 0:
            return t.min(), t.max()
    return None, None


def _sync_range_editors(self):
    if not hasattr(self, "range_from_edit") or not hasattr(self, "range_to_edit"):
        return

    t_min, t_max = self._get_plot_time_bounds()
    if t_min is None or t_max is None:
        return

    self.range_from_edit.blockSignals(True)
    self.range_to_edit.blockSignals(True)

    self.range_from_edit.setDateTime(
        QDateTime(t_min.year, t_min.month, t_min.day, t_min.hour, t_min.minute, t_min.second)
    )
    self.range_to_edit.setDateTime(
        QDateTime(t_max.year, t_max.month, t_max.day, t_max.hour, t_max.minute, t_max.second)
    )

    self.range_from_edit.blockSignals(False)
    self.range_to_edit.blockSignals(False)


def _on_x_scale_changed(self, idx=None):
    text = self.x_scale_combo.currentText()

    if text == "Весь график":
        self.x_scale_mode = "all"
    elif text == "1 день":
        self.x_scale_mode = "1d"
    elif text == "1 неделя":
        self.x_scale_mode = "7d"
    else:
        self.x_scale_mode = "range"

    manual = self.x_scale_mode == "range"
    self.range_from_edit.setEnabled(manual)
    self.range_to_edit.setEnabled(manual)

    if manual:
        self._sync_range_editors()

    self.plot_layers()


def _apply_manual_range_live(self, *args):
    if getattr(self, "x_scale_mode", "all") == "range":
        self.plot_layers()


def _apply_x_scale(self, ax):
    t_min, t_max = self._get_plot_time_bounds()
    if t_min is None or t_max is None:
        return

    mode = getattr(self, "x_scale_mode", "all")

    if mode == "all":
        ax.set_xlim(t_min, t_max)
        return

    if mode == "1d":
        right = t_max
        left = max(t_min, t_max - pd.Timedelta(days=1))
        ax.set_xlim(left, right)
        return

    if mode == "7d":
        right = t_max
        left = max(t_min, t_max - pd.Timedelta(days=7))
        ax.set_xlim(left, right)
        return

    if mode == "range":
        left = self.range_from_edit.dateTime().toPython()
        right = self.range_to_edit.dateTime().toPython()
        if left >= right:
            return

        if hasattr(t_min, "to_pydatetime"):
            t_min = t_min.to_pydatetime()
        if hasattr(t_max, "to_pydatetime"):
            t_max = t_max.to_pydatetime()

        left = max(left, t_min)
        right = min(right, t_max)

        if left < right:
            ax.set_xlim(left, right)
		
    def run_butterworth(self):
        try:
            stage, df = self._get_processing_input()
            if df is None:
                raise ValueError("Нет данных для фильтра Баттерворта.")

            self.log("=== Фильтр Баттерворта ===")
            order = self.order_spin.value()
            period_min = self.period_spin.value()
            time_col, height_col = self._resolve_time_height_cols(df)

            tmp_in = self._csv_output_dir() / "_tmp_input_bw.csv"
            tmp_out = self._csv_output_dir() / f"{self.current_file.stem if self.current_file else 'dataset'}_tmp_bw.csv"

            df.copy().to_csv(tmp_in, index=False, encoding="utf-8-sig")

            butterworth_on_csv(
                input_csv=str(tmp_in),
                output_csv=str(tmp_out),
                time_col=time_col,
                height_col=height_col,
                period_minutes=period_min,
                order=order
            )

            self.df_bw = pd.read_csv(tmp_out)
            if "height_bw" not in self.df_bw.columns:
                raise ValueError("После Баттерворта не появился столбец 'height_bw'.")

            self.log_step(
                "butterworth",
                "Баттерворт применён",
                {
                    "stage": stage,
                    "order": order,
                    "period_min": period_min,
                    "rows_out": len(self.df_bw),
                    "tmp_out": str(tmp_out)
                }
            )

            if self.cb_median_live.isChecked():
                self.run_median()
            else:
                self.plot_layers()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка фильтра Баттерворта", str(e))
            self.log_model.add_error(str(e), module="butterworth")
            self.log(f"Ошибка фильтра Баттерворта: {e}")

    def run_median(self):
        try:
            base_stage, base_df = ("bw", self.df_bw) if self.df_bw is not None else self._get_processing_input()
            if base_df is None:
                raise ValueError("Нет данных для медианного фильтра.")
            if "height_bw" not in base_df.columns:
                raise ValueError("Для медианного фильтра нужен столбец 'height_bw'. Сначала выполните Баттерворт.")

            self.log("=== Медианный фильтр ===")
            cfg = MedianFilterConfig(
                window_points=int(self.window_points_spin.value()),
                threshold_mm=float(self.threshold_mm_spin.value())
            )
            self.df_med = MedianResidualFilter(cfg).apply(base_df)
            s = MedianResidualFilter.summary(self.df_med)

            self.log_step(
                "median_filter",
                "Медианный фильтр применён",
                {
                    "stage": base_stage,
                    "window_points": cfg.window_points,
                    "threshold_mm": cfg.threshold_mm,
                    **s
                }
            )
            self.plot_layers()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка медианного фильтра", str(e))
            self.log_model.add_error(str(e), module="median_filter")
            self.log(f"Ошибка медианного фильтра: {e}")

    def _median_live_recalc(self):
        if not self.cb_median_live.isChecked():
            return
        if self.df_bw is None:
            return
        try:
            self.run_median()
        except Exception:
            pass

    def _on_y_mode_changed(self, idx: int):
        self.y_mode = "absolute_m" if "Абсолютная" in self.y_mode_combo.currentText() else "mean_mm"
        self.plot_layers()

    @staticmethod
    def _to_mm_relative(series: pd.Series) -> pd.Series:
        s = pd.to_numeric(series, errors="coerce")
        return (s - s.mean()) * 1000.0

    @staticmethod
    def _stats_text_from_df(df: pd.DataFrame) -> str:
        lines = []

        def add_stats(label: str, col: str, unit_mode: str):
            if col not in df.columns:
                return
            s = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(s) == 0:
                return
            if unit_mode == "m":
                std_mm = s.std(ddof=1) * 1000.0 if len(s) > 1 else 0.0
                lines.append(f"{label}: N={len(s)} ср={s.mean():.4f} м СКО={std_mm:.2f} мм")
            else:
                std_mm = s.std(ddof=1) if len(s) > 1 else 0.0
                lines.append(f"{label}: N={len(s)} ср={s.mean():.2f} мм СКО={std_mm:.2f} мм")

        add_stats("Исходный", "height", "m")
        add_stats("Баттерворт", "height_bw", "m")
        add_stats("Медианный", "height_med", "m")
        add_stats("Остатки BW", "residual_bw_mm", "mm")
        add_stats("Остатки MED", "residual_med_mm", "mm")
        return "\n".join(lines)

    def plot_layers(self):
        try:
            ax = self.canvas.ax
            ax.clear()
            plotted = False
            stats_source = None

            for candidate in (self.df_med, self.df_bw, self.df_clean, self.df_validated, self.df_raw):
                if candidate is not None and not candidate.empty:
                    stats_source = candidate
                    break

            def plot_df(df, label, color, y_col=None, linewidth=1.0, alpha=1.0):
                nonlocal plotted
                if df is None or df.empty:
                    return

                time_col = "utc_time" if "utc_time" in df.columns else self.time_col
                if time_col not in df.columns:
                    return

                col = y_col or ("height" if "height" in df.columns else self.height_col)
                if col not in df.columns:
                    return

                t = pd.to_datetime(df[time_col], errors="coerce", utc=True).dt.tz_localize(None)
                y = pd.to_numeric(df[col], errors="coerce")
                mask = t.notna() & y.notna()
                t = t[mask]
                y = y[mask]

                if len(t) == 0:
                    return

                if self.y_mode == "mean_mm":
                    y = self._to_mm_relative(y)
				
                self.log(f"Рисуем {label}: {t.min()} .. {t.max()} (N={len(t)})")	

                ax.plot(t, y, label=label, color=color, linewidth=linewidth, alpha=alpha)
                plotted = True

            if self.cb_raw.isChecked():
                plot_df(
                    self.df_raw,
                    "Исходный",
                    "#FFD700",
                    "height" if self.df_raw is not None and "height" in self.df_raw.columns else self.height_col,
                    linewidth=2.0,
                    alpha=0.45,
                )

            if self.cb_valid.isChecked():
                plot_df(
                    self.df_validated,
                    "После проверки времени",
                    "#FF8C00",
                    "height" if self.df_validated is not None and "height" in self.df_validated.columns else self.height_col,
                    linewidth=1.0,
                    alpha=0.55,
                )

            if self.cb_clean.isChecked():
                plot_df(
                    self.df_clean,
                    "После очистки",
                    "#D62728",
                    "height",
                    linewidth=1.0,
                    alpha=0.55,
                )

            if self.cb_bw.isChecked():
                plot_df(
                    self.df_bw,
                    "Баттерворт",
                    "#88E788",
                    "height_bw",
                    linewidth=1.2,
                    alpha=0.95,
                )

            if self.cb_med.isChecked():
                plot_df(
                    self.df_med,
                    "Медианный",
                    "#8A2BE2",
                    "height_med",
                    linewidth=1.2,
                    alpha=0.95,
                )

            if self.y_mode == "mean_mm":
                ax.axhline(0.0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)

            ax.set_title(self.current_file.name if self.current_file else "GNSS график")
            ax.set_xlabel("Время")
            ax.set_ylabel("Высота, м" if self.y_mode == "absolute_m" else "Отклонение от среднего, мм")
            ax.grid(True, alpha=0.3)

            locator = mdates.AutoDateLocator(minticks=12, maxticks=24)
            formatter = mdates.ConciseDateFormatter(locator)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(formatter)
            ax.tick_params(axis="x", rotation=30)

            if plotted:
                ax.legend(loc="upper left")

            if stats_source is not None:
                txt = self._stats_text_from_df(stats_source)
                if txt:
                    ax.text(
                        0.995,
                        0.995,
                        txt,
                        transform=ax.transAxes,
                        ha="right",
                        va="top",
                        fontsize=9,
                        bbox={
                            "boxstyle": "round",
                            "facecolor": "white",
                            "alpha": 0.85,
                            "edgecolor": "gray"
                        }
                    )

            self.canvas.fig.tight_layout()
            self.canvas.draw()
        except Exception as e:
            self.log_model.add_error(str(e), module="plot")
            self.log(f"Ошибка графика: {e}")

    def save_current_csv(self):
        try:
            stage, df = self._get_display_table()
            if df is None:
                raise ValueError("Нет таблицы для сохранения.")

            default_name = "plot.csv" if not self.current_file else f"{self.current_file.stem}_{stage}.csv"
            default_path = self._csv_output_dir() / default_name

            out_path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить CSV",
                str(default_path),
                "CSV files (*.csv)"
            )
            if not out_path:
                return

            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            self.log_step("export_csv", "Сохранена таблица", {"stage": stage, "path": out_path})
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения CSV", str(e))
            self.log_model.add_error(str(e), module="export_csv")
            self.log(f"Ошибка сохранения CSV: {e}")

    def save_current_jpg(self):
        try:
            default_name = "plot.jpg" if not self.current_file else f"{self.current_file.stem}_plot.jpg"
            default_path = self._jpg_output_dir() / default_name

            out_path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить график JPG",
                str(default_path),
                "JPG files (*.jpg)"
            )
            if not out_path:
                return

            if not out_path.lower().endswith(".jpg"):
                out_path += ".jpg"

            self.canvas.fig.set_size_inches(12, 6)
            self.canvas.fig.tight_layout()
            self.canvas.fig.savefig(out_path, dpi=300, bbox_inches="tight")
            self.log_step("export_jpg", "График сохранён", {"path": out_path})
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения JPG", str(e))
            self.log_model.add_error(str(e), module="export_jpg")
            self.log(f"Ошибка сохранения JPG: {e}")

    def save_log(self):
        try:
            default_name = "processing_log.txt" if not self.current_file else f"{self.current_file.stem}_processing_log.txt"
            default_path = self._log_output_dir() / default_name

            out_path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить лог",
                str(default_path),
                "Text files (*.txt);;JSON files (*.json)"
            )
            if not out_path:
                return

            fmt = "json" if Path(out_path).suffix.lower() == ".json" else "txt"
            saved_path = self.log_model.save(out_path, fmt=fmt)
            self.log(f"Лог сохранён: {saved_path}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения лога", str(e))
            self.log_model.add_error(str(e), module="export_log")
            self.log(f"Ошибка сохранения лога: {e}")

    def save_bundle(self):
        try:
            stage, df = self._get_display_table()
            if df is None:
                raise ValueError("Нет данных для финального сохранения.")

            stem = self.current_file.stem if self.current_file else "dataset"
            final_dir = self._final_export_dir()

            csv_path = final_dir / f"{stem}_{stage}_final.csv"
            jpg_path = final_dir / f"{stem}_{stage}_final.jpg"
            log_path = final_dir / f"{stem}_{stage}_processing_log.txt"

            df.to_csv(csv_path, index=False, encoding="utf-8-sig")

            self.canvas.fig.set_size_inches(12, 6)
            self.canvas.fig.tight_layout()
            self.canvas.fig.savefig(jpg_path, dpi=300, bbox_inches="tight")

            self.log_model.add(
                module="final_export",
                summary="Сформирован финальный комплект",
                params={
                    "stage": stage,
                    "final_dir": str(final_dir),
                    "csv_path": str(csv_path),
                    "jpg_path": str(jpg_path),
                    "log_path": str(log_path),
                    "k_sigma": self.k_sigma_spin.value(),
                    "window_sec": self.window_sec_spin.value(),
                    "min_group": self.min_group_spin.value(),
                    "max_group_epochs": self.max_group_spin.value(),
                    "bw_order": self.order_spin.value(),
                    "bw_period_min": self.period_spin.value(),
                    "median_window_points": self.window_points_spin.value(),
                    "median_threshold_mm": self.threshold_mm_spin.value(),
                    "y_mode": self.y_mode,
                },
                level="INFO",
            )

            self.log_model.save(str(log_path), fmt="txt")

            self.log_step(
                "final_export",
                "Финальный комплект сохранён",
                {
                    "stage": stage,
                    "folder": str(final_dir),
                    "csv": str(csv_path),
                    "jpg": str(jpg_path),
                    "log": str(log_path),
                },
            )

            QMessageBox.information(
                self,
                "Готово",
                f"Финальный комплект сохранён в папку:\n\n{final_dir}\n\n"
                f"CSV: {csv_path.name}\n"
                f"JPG: {jpg_path.name}\n"
                f"LOG: {log_path.name}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Ошибка финального сохранения", str(e))
            self.log_model.add_error(str(e), module="final_export")
            self.log(f"Ошибка финального сохранения: {e}")


def main():
    app = QApplication(sys.argv)
    w = GNSSMainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()