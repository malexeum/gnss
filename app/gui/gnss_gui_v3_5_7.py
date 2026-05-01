import sys
from pathlib import Path
import json

import pandas as pd
from PySide6.QtCore import Qt, QDateTime
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QDoubleSpinBox, QSpinBox, QSplitter,
    QGroupBox, QCheckBox, QComboBox, QDateTimeEdit, QSizePolicy,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.dates as mdates

# Пути к модулям ядра (для dev-режима)
ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = ROOT / "app" / "core"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from data_importer import DataImporter
from time_validator import TimeValidator
from outlier_detector import OutlierDetector
from butterworth_filter import butterworth_on_csv
from median_filter import MedianResidualFilter, MedianFilterConfig
from processing_log import ProcessingLog
from data_exporter import DataExporter


def _app_base_dir() -> Path:
    """
    Базовая директория приложения:
    - в EXE-режиме: папка рядом с GNSS_GUI.exe
    - в dev-режиме: корень проекта (на два уровня выше этого файла)
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None, width=9, height=6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)


class GNSSMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # Иконка окна: ищем app.ico рядом с приложением
        icon_path = _app_base_dir() / "assets" / "app.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setWindowTitle("GNSS Processing GUI v3.5.7")
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

        self.log_model = ProcessingLog(version="0.3.5.7")
        self.exporter = DataExporter(units="m")
        self.importer = DataImporter()
        self.time_validator = TimeValidator()

        self._build_ui()
        self._set_status("Готово.", "info")

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

        settings_row = QHBoxLayout()
        settings_row.setSpacing(8)

        btn_import_settings = QPushButton("Импорт настроек")
        btn_import_settings.clicked.connect(self.import_filter_params)

        btn_export_settings = QPushButton("Экспорт настроек")
        btn_export_settings.clicked.connect(self.export_filter_params)

        settings_row.addWidget(btn_import_settings)
        settings_row.addWidget(btn_export_settings)
        import_layout.addLayout(settings_row)

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

        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

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

        for btn in [btn_load, btn_validate, btn_outlier, btn_bw, btn_med]:
            actions_layout.addWidget(btn)
        actions_layout.addStretch(1)

        save_group = QGroupBox("Сохранение")
        save_layout = QVBoxLayout(save_group)
        save_layout.setSpacing(8)

        btn_save_csv = QPushButton("Сохранить CSV")
        btn_save_csv.clicked.connect(self.save_current_csv)

        btn_save_jpg = QPushButton("Сохранить JPG")
        btn_save_jpg.clicked.connect(self.save_current_jpg)

        btn_save_bundle = QPushButton("Сохранить комплект")
        btn_save_bundle.clicked.connect(self.save_bundle)

        for btn in [btn_save_csv, btn_save_jpg, btn_save_bundle]:
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            save_layout.addWidget(btn)
        save_layout.addStretch(1)

        actions_row.addWidget(actions_group, 4)
        actions_row.addWidget(save_group, 1)

        self.process_status_label = QLabel("Статус: Готово")
        self.process_status_label.setStyleSheet("""
            QLabel {
                background-color: #f2f4f7;
                border: 1px solid #cfcfcf;
                border-radius: 6px;
                padding: 6px 10px;
                color: #333;
                font-weight: 600;
            }
        """)

        layers_group = QGroupBox("Слои и режим графика")
        layers_layout = QVBoxLayout(layers_group)
        layers_layout.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(12)

        self.cb_raw = QCheckBox("Исходный")
        self.cb_valid = QCheckBox("После проверки времени")
        self.cb_clean = QCheckBox("После очистки")
        self.cb_bw = QCheckBox("Баттерворт")
        self.cb_med = QCheckBox("Медианный")

        self.cb_raw.setChecked(True)

        for cb in [self.cb_raw, self.cb_valid, self.cb_clean, self.cb_bw, self.cb_med]:
            cb.stateChanged.connect(self.plot_layers)
            row1.addWidget(cb)

        row1.addSpacing(24)
        row1.addWidget(QLabel("Y:"))

        self.y_mode_combo = QComboBox()
        self.y_mode_combo.addItems(["Абсолютная высота, м", "Отклонение от среднего, мм"])
        self.y_mode_combo.setCurrentIndex(1)
        self.y_mode_combo.currentIndexChanged.connect(self._on_y_mode_changed)
        row1.addWidget(self.y_mode_combo)

        row1.addStretch(1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)

        row2.addWidget(QLabel("Период просмотра:"))

        self.x_scale_combo = QComboBox()
        self.x_scale_combo.addItems(["Весь график", "1 день", "1 неделя", "Диапазон"])
        self.x_scale_combo.setCurrentText("Весь график")
        self.x_scale_combo.currentIndexChanged.connect(self._on_x_scale_changed)
        row2.addWidget(self.x_scale_combo)

        row2.addSpacing(12)
        row2.addWidget(QLabel("С:"))

        self.range_from_edit = QDateTimeEdit()
        self.range_from_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.range_from_edit.setCalendarPopup(True)
        self.range_from_edit.setEnabled(False)
        self.range_from_edit.dateTimeChanged.connect(self._apply_manual_range_live)
        row2.addWidget(self.range_from_edit)

        row2.addWidget(QLabel("По:"))

        self.range_to_edit = QDateTimeEdit()
        self.range_to_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.range_to_edit.setCalendarPopup(True)
        self.range_to_edit.setEnabled(False)
        self.range_to_edit.dateTimeChanged.connect(self._apply_manual_range_live)
        row2.addWidget(self.range_to_edit)

        row2.addStretch(1)

        layers_layout.addLayout(row1)
        layers_layout.addLayout(row2)

        self.current_stage_label = QLabel("Источник для графика: нет данных")
        self.current_stage_label.setStyleSheet("""
            QLabel {
                background-color: #eef3f8;
                border: 1px solid #cfd8e3;
                border-radius: 6px;
                padding: 6px 10px;
                color: #2f4f6f;
                font-style: italic;
                font-weight: 600;
            }
        """)

        self.canvas = MplCanvas(self)
        self.toolbar = NavigationToolbar(self.canvas, self)

        center_layout.addLayout(actions_row)
        center_layout.addWidget(self.process_status_label)
        center_layout.addWidget(layers_group)
        center_layout.addWidget(self.current_stage_label)
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

    def _set_status(self, text: str, level: str = "info"):
        if hasattr(self, "process_status_label") and self.process_status_label is not None:
            self.process_status_label.setText(f"Статус: {text}")

            if level == "error":
                style = """
                    QLabel {
                        background-color: #fdecec;
                        border: 1px solid #d66;
                        border-radius: 6px;
                        padding: 6px 10px;
                        color: #8b1e1e;
                        font-weight: 700;
                    }
                """
            elif level == "work":
                style = """
                    QLabel {
                        background-color: #fff7db;
                        border: 1px solid #d8b24c;
                        border-radius: 6px;
                        padding: 6px 10px;
                        color: #6f5600;
                        font-weight: 700;
                    }
                """
            elif level == "done":
                style = """
                    QLabel {
                        background-color: #eaf7ea;
                        border: 1px solid #7dbb7d;
                        border-radius: 6px;
                        padding: 6px 10px;
                        color: #1f5f1f;
                        font-weight: 700;
                    }
                """
            else:
                style = """
                    QLabel {
                        background-color: #f2f4f7;
                        border: 1px solid #cfcfcf;
                        border-radius: 6px;
                        padding: 6px 10px;
                        color: #333;
                        font-weight: 600;
                    }
                """

            self.process_status_label.setStyleSheet(style)

    def log_step(self, module: str, summary: str, params=None, level: str = "INFO"):
        params = params or {}
        self.log_model.add(module=module, summary=summary, params=params, level=level)
        self.log(f"[{level}] {module}: {summary}")
        if params:
            self.log(" " + ", ".join(f"{k}={v}" for k, v in params.items()))

    def _project_root(self) -> Path:
        # Для совместимости: базой считаем директорию приложения
        return _app_base_dir()

    def _input_data_dir(self) -> Path:
        # Всегда data/input рядом с приложением
        base = _app_base_dir() / "data" / "input"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _base_output_dir(self) -> Path:
        base = _app_base_dir() / "data" / "output"
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
        self.log_model.version = "0.3.5.6"
        self.log_text.clear()
        self.log_step("session", "Начата новая сессия обработки", {"file": str(self.current_file)})
        self._set_status("Выбран файл. Готово к импорту.", "info")
        if self.current_stage_label:
            self.current_stage_label.setText("Источник для графика: нет данных")

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
            "utc_time_utc", "utc_time", "datetime_utc", "datetime", "datetime utc", "utc time",
            "датаивремя", "датавремя", "дата_и_время", "date_time",
            "time_utc", "gpst", "utc", "date", "datetimeutc", "Дата-Время"
        ]

        height_candidates = [
            "height_m", "height", "высотам", "высота", "Высота (м)", "h", "h_ellips_m", "hellipsm", "ellipsoidal_height", "ellips_height"
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

    def _collect_filter_params(self) -> dict:
        return {
            "version": "3.5.6",
            "outlier": {
                "k_sigma": float(self.k_sigma_spin.value()),
                "window_sec": int(self.window_sec_spin.value()),
                "min_group": int(self.min_group_spin.value()),
                "max_group_epochs": int(self.max_group_spin.value()),
            },
            "butterworth": {
                "order": int(self.order_spin.value()),
                "period_min": int(self.period_spin.value()),
            },
            "median": {
                "window_points": int(self.window_points_spin.value()),
                "threshold_mm": float(self.threshold_mm_spin.value()),
                "live_recalc": bool(self.cb_median_live.isChecked()),
            },
            "plot": {
                "y_mode_text": self.y_mode_combo.currentText(),
                "x_scale_text": self.x_scale_combo.currentText(),
            }
        }

    def _apply_filter_params(self, params: dict):
        outlier = params.get("outlier", {})
        butter = params.get("butterworth", {})
        median = params.get("median", {})
        plot = params.get("plot", {})

        if "k_sigma" in outlier:
            self.k_sigma_spin.setValue(float(outlier["k_sigma"]))
        if "window_sec" in outlier:
            self.window_sec_spin.setValue(int(outlier["window_sec"]))
        if "min_group" in outlier:
            self.min_group_spin.setValue(int(outlier["min_group"]))
        if "max_group_epochs" in outlier:
            self.max_group_spin.setValue(int(outlier["max_group_epochs"]))

        if "order" in butter:
            self.order_spin.setValue(int(butter["order"]))
        if "period_min" in butter:
            self.period_spin.setValue(int(butter["period_min"]))

        if "window_points" in median:
            self.window_points_spin.setValue(int(median["window_points"]))
        if "threshold_mm" in median:
            self.threshold_mm_spin.setValue(float(median["threshold_mm"]))
        if "live_recalc" in median:
            self.cb_median_live.setChecked(bool(median["live_recalc"]))

        y_mode_text = plot.get("y_mode_text")
        if y_mode_text:
            idx = self.y_mode_combo.findText(y_mode_text)
            if idx >= 0:
                self.y_mode_combo.setCurrentIndex(idx)

        x_scale_text = plot.get("x_scale_text")
        if x_scale_text:
            idx = self.x_scale_combo.findText(x_scale_text)
            if idx >= 0:
                self.x_scale_combo.setCurrentIndex(idx)

    def export_filter_params(self):
        try:
            default_name = "filter_params.json"
            if self.current_file:
                default_name = f"{self.current_file.stem}_filter_params.json"

            default_path = self._base_output_dir() / default_name

            out_path, _ = QFileDialog.getSaveFileName(
                self,
                "Экспорт параметров фильтров",
                str(default_path),
                "JSON files (*.json)"
            )
            if not out_path:
                return

            if not out_path.lower().endswith(".json"):
                out_path += ".json"

            payload = self._collect_filter_params()

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            self.log_step("params_export", "Параметры фильтров сохранены", {"path": out_path})
            self._set_status("Параметры фильтров экспортированы.", "done")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта параметров", str(e))
            self.log_model.add_error(str(e), module="params_export")
            self.log(f"Ошибка экспорта параметров: {e}")
            self._set_status("Ошибка экспорта параметров.", "error")

    def import_filter_params(self):
        try:
            in_path, _ = QFileDialog.getOpenFileName(
                self,
                "Импорт параметров фильтров",
                str(self._base_output_dir()),
                "JSON files (*.json)"
            )
            if not in_path:
                return

            with open(in_path, "r", encoding="utf-8") as f:
                params = json.load(f)

            if not isinstance(params, dict):
                raise ValueError("JSON должен содержать объект с параметрами.")

            self._apply_filter_params(params)

            self.log_step("params_import", "Параметры фильтров загружены", {"path": in_path})
            self._set_status("Параметры фильтров импортированы.", "done")

            if self.df_raw is not None:
                self.plot_layers()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта параметров", str(e))
            self.log_model.add_error(str(e), module="params_import")
            self.log(f"Ошибка импорта параметров: {e}")
            self._set_status("Ошибка импорта параметров.", "error")

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

    def plot_layers(self):
        try:
            ax = self.canvas.ax
            ax.clear()
            plotted = False
            stats_items = []

            stage, _ = self._get_display_table()
            stage_human = {
                "raw": "Исходный",
                "validated": "После проверки времени",
                "clean": "После очистки выбросов",
                "bw": "После фильтра Баттерворта",
                "med": "После медианного фильтра",
                None: "Нет данных",
            }.get(stage, "Нет данных")

            if self.current_stage_label:
                self.current_stage_label.setText(f"Источник для графика: {stage_human}")

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

            # Исходный
            if self.cb_raw.isChecked():
                raw_col = (
                    "height"
                    if self.df_raw is not None and "height" in (self.df_raw.columns if self.df_raw is not None else [])
                    else self.height_col
                )
                plot_df(
                    self.df_raw,
                    "Исходный",
                    "#FFD700",
                    raw_col,
                    linewidth=2.0,
                    alpha=0.45,
                )
                stats_items.append(
                    ("Исходный", self._windowed_df_for_stats(self.df_raw), raw_col, "m")
                )

            # После проверки времени
            if self.cb_valid.isChecked():
                valid_col = (
                    "height"
                    if self.df_validated is not None and "height" in (self.df_validated.columns if self.df_validated is not None else [])
                    else self.height_col
                )
                plot_df(
                    self.df_validated,
                    "После проверки времени",
                    "#FF8C00",
                    valid_col,
                    linewidth=1.0,
                    alpha=0.55,
                )
                stats_items.append(
                    ("После проверки", self._windowed_df_for_stats(self.df_validated), valid_col, "m")
                )

            # После очистки
            if self.cb_clean.isChecked():
                plot_df(
                    self.df_clean,
                    "После очистки",
                    "#D62728",
                    "height",
                    linewidth=1.0,
                    alpha=0.55,
                )
                stats_items.append(
                    ("После очистки", self._windowed_df_for_stats(self.df_clean), "height", "m")
                )

            # Баттерворт
            if self.cb_bw.isChecked():
                plot_df(
                    self.df_bw,
                    "Баттерворт",
                    "#88E788",
                    "height_bw",
                    linewidth=1.2,
                    alpha=0.95,
                )
                stats_items.append(
                    ("Баттерворт", self._windowed_df_for_stats(self.df_bw), "height_bw", "m")
                )

            # Медианный
            if self.cb_med.isChecked():
                plot_df(
                    self.df_med,
                    "Медианный",
                    "#8A2BE2",
                    "height_med",
                    linewidth=1.2,
                    alpha=0.95,
                )
                stats_items.append(
                    ("Медианный", self._windowed_df_for_stats(self.df_med), "height_med", "m")
                )

            if self.y_mode == "mean_mm":
                ax.axhline(0.0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)

            ax.set_title(self.current_file.name if self.current_file else "GNSS график")
            ax.set_xlabel("Время")
            ax.set_ylabel("Высота, м" if self.y_mode == "absolute_m" else "Отклонение от среднего, мм")
            ax.grid(True, alpha=0.3)

            locator = mdates.AutoDateLocator(minticks=5, maxticks=10)
            formatter = mdates.ConciseDateFormatter(locator)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(formatter)

            self._apply_x_scale(ax)
            ax.tick_params(axis="x", rotation=30)

            if plotted:
                ax.legend(loc="upper left")

            txt = self._stats_text_from_df(stats_items)
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
                        "edgecolor": "gray",
                    },
                )

            self.canvas.fig.tight_layout()
            self.canvas.draw()

        except Exception as e:
            self.log_model.add_error(str(e), module="plot")
            self.log(f"Ошибка графика: {e}")
            self._set_status("Ошибка построения графика.", "error")
			
    def _windowed_df_for_stats(self, df: pd.DataFrame):
        if df is None or df.empty:
            return None

        time_col = "utc_time" if "utc_time" in df.columns else self.time_col
        if not time_col or time_col not in df.columns:
            return None

        t_all = pd.to_datetime(df[time_col], errors="coerce", utc=True).dt.tz_localize(None)
        valid_mask = t_all.notna()
        if not valid_mask.any():
            return None

        df_valid = df.loc[valid_mask].copy()
        t_valid = t_all.loc[valid_mask]

        if getattr(self, "x_scale_mode", "all") == "all":
            return df_valid

        if self.x_scale_mode == "1d":
            right = t_valid.max()
            left = max(t_valid.min(), right - pd.Timedelta(days=1))
        elif self.x_scale_mode == "7d":
            right = t_valid.max()
            left = max(t_valid.min(), right - pd.Timedelta(days=7))
        elif self.x_scale_mode == "range":
            left = self.range_from_edit.dateTime().toPython()
            right = self.range_to_edit.dateTime().toPython()
            if left >= right:
                return df_valid.iloc[0:0].copy()

            t_min = t_valid.min()
            t_max = t_valid.max()
            if hasattr(t_min, "to_pydatetime"):
                t_min = t_min.to_pydatetime()
            if hasattr(t_max, "to_pydatetime"):
                t_max = t_max.to_pydatetime()

            left = max(left, t_min)
            right = min(right, t_max)
            if left >= right:
                return df_valid.iloc[0:0].copy()
        else:
            return df_valid

        mask = (t_valid >= left) & (t_valid <= right)
        return df_valid.loc[mask].copy()

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
            self._set_status("CSV сохранён.", "done")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения CSV", str(e))
            self.log_model.add_error(str(e), module="export_csv")
            self.log(f"Ошибка сохранения CSV: {e}")
            self._set_status("Ошибка сохранения CSV.", "error")

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
            self._set_status("JPG сохранён.", "done")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения JPG", str(e))
            self.log_model.add_error(str(e), module="export_jpg")
            self.log(f"Ошибка сохранения JPG: {e}")
            self._set_status("Ошибка сохранения JPG.", "error")

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
            self._set_status("Лог сохранён.", "done")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения лога", str(e))
            self.log_model.add_error(str(e), module="export_log")
            self.log(f"Ошибка сохранения лога: {e}")
            self._set_status("Ошибка сохранения лога.", "error")

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
            self._set_status("Финальный комплект сохранён.", "done")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка финального сохранения", str(e))
            self.log_model.add_error(str(e), module="final_export")
            self.log(f"Ошибка финального сохранения: {e}")
            self._set_status("Ошибка финального сохранения.", "error")


def main():
    app = QApplication(sys.argv)
    w = GNSSMainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()