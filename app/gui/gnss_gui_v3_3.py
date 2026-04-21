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

from data_importer import DataImporter
from time_validator import TimeValidator
from outlier_detector import OutlierDetector
from butterworth_filter import butterworth_on_csv
from median_filter import MedianResidualFilter, MedianFilterConfig
from processing_log import ProcessingLog
from data_exporter import DataExporter


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None, width=9, height=6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)


class GNSSMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GNSS Processing GUI v0.4")
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

        self.log_model = ProcessingLog(version="0.4.0")
        self.exporter = DataExporter(units="m")
        self.importer = DataImporter()
        self.time_validator = TimeValidator()

        self._build_ui()

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
        self.window_points_spin.setRange(3, 29)
        self.window_points_spin.setSingleStep(2)
        self.window_points_spin.setValue(9)

        self.threshold_mm_spin = QDoubleSpinBox()
        self.threshold_mm_spin.setRange(2.0, 40.0)
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
        btn_bw = QPushButton("Баттерворт")
        btn_bw.clicked.connect(self.run_butterworth)
        btn_med = QPushButton("Median")
        btn_med.clicked.connect(self.run_median)
        btn_plot = QPushButton("Обновить график")
        btn_plot.clicked.connect(self.plot_layers)
        btn_save_csv = QPushButton("Сохранить CSV")
        btn_save_csv.clicked.connect(self.save_current_csv)
        btn_save_jpg = QPushButton("Сохранить JPG")
        btn_save_jpg.clicked.connect(self.save_current_jpg)
        btn_save_log = QPushButton("Сохранить лог")
        btn_save_log.clicked.connect(self.save_log)

        for btn in [btn_load, btn_validate, btn_outlier, btn_bw, btn_med, btn_plot, btn_save_csv, btn_save_jpg, btn_save_log]:
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
        self.log_text.append(message)

    def choose_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать GNSS файл",
            "",
            "Data files (*.csv *.txt *.tsv *.xls *.xlsx *.pos);;All files (*.*)"
        )
        if not file_path:
            return

        self.current_file = Path(file_path)
        self.current_dir = self.current_file.parent
        self.file_edit.setText(str(self.current_file))
        self.log(f"Выбран файл: {self.current_file}")

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

    def _auto_guess_columns(self, df: pd.DataFrame):
        cols = list(df.columns)
        self.log(f"Автоопределение колонок. Колонки: {cols}")
        time_candidates = ["utc_time_utc", "utc_time", "datetime_utc", "datetime", "Дата-Время", "Time_UTC", "GPST", "UTC", "Date"]
        height_candidates = ["height_m", "Height_m", "height", "Height", "Высота (м)", "h"]

        def find_col(cands):
            lower = {c.lower(): c for c in cols}
            for cand in cands:
                if cand.lower() in lower:
                    return lower[cand.lower()]
            return None

        return find_col(time_candidates), find_col(height_candidates)

    def load_file(self):
        try:
            if not self.current_file:
                QMessageBox.warning(self, "Нет файла", "Сначала выберите файл.")
                return

            self.log("=== Импорт ===")
            self.log(f"Файл: {self.current_file.name}")
            raw_table = self.importer.load(str(self.current_file))
            self.df_raw = raw_table.df.copy()

            self.log(f"Размер таблицы: {len(self.df_raw)} строк, {len(self.df_raw.columns)} столбцов")
            self.log(f"Колонки: {list(self.df_raw.columns)}")

            manual_time = self.time_col_edit.text().strip()
            manual_height = self.height_col_edit.text().strip()

            if manual_time and manual_height:
                self.importer.set_columns(manual_time, manual_height)
                self.time_col = self.importer.schema.time_col
                self.height_col = self.importer.schema.height_col
                self.log(f"Использованы ручные поля: время={self.time_col}, высота={self.height_col}")
            else:
                time_col, height_col = self._auto_guess_columns(self.df_raw)
                if not time_col:
                    raise ValueError(f"Не найдена временная колонка. Столбцы: {list(self.df_raw.columns)}")
                if not height_col:
                    raise ValueError(f"Не найдена колонка высоты. Столбцы: {list(self.df_raw.columns)}")
                self.importer.set_columns(time_col, height_col)
                self.time_col = self.importer.schema.time_col
                self.height_col = self.importer.schema.height_col
                self.time_col_edit.setText(self.time_col)
                self.height_col_edit.setText(self.height_col)
                self.log(f"Автоопределены поля: время={self.time_col}, высота={self.height_col}")

            self.plot_layers()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", str(e))
            self.log(f"Ошибка импорта: {e}")

    def validate_time(self):
        try:
            if self.df_raw is None:
                QMessageBox.warning(self, "Нет данных", "Сначала загрузите файл.")
                return
            if not self.time_col or self.time_col not in self.df_raw.columns:
                raise ValueError("Не указана колонка времени.")
            if not self.height_col or self.height_col not in self.df_raw.columns:
                raise ValueError("Не указана колонка высоты.")

            self.log("=== Проверка времени ===")
            self.log(f"Использованы поля: время={self.time_col}, высота={self.height_col}")

            normalized = self.time_validator.validate(
                raw_table=self.importer._raw_table,
                time_col=self.time_col,
                height_col=self.height_col,
                date_col=self.importer.schema.date_col or None,
            )
            self.df_validated = normalized.df.copy()
            self.log(normalized.report.to_text())
            self.plot_layers()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка валидации", str(e))
            self.log(f"Ошибка валидации: {e}")

    def run_outlier(self):
        try:
            if self.df_validated is None:
                QMessageBox.warning(self, "Нет данных", "Сначала выполните проверку времени.")
                return

            self.log("=== Очистка выбросов ===")
            otl = OutlierDetector(
                time_col="utc_time",
                height_col="height",
                k_sigma=self.k_sigma_spin.value(),
                window_sec=self.window_sec_spin.value(),
                min_group=self.min_group_spin.value(),
                max_group_epochs=self.max_group_spin.value(),
            )
            clean, removed, flagged, report = otl.run(self.df_validated.copy())
            self.df_clean = clean
            self.df_removed = removed
            self.df_flagged = flagged
            self.log(report)
            self.plot_layers()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка очистки выбросов", str(e))
            self.log(f"Ошибка очистки выбросов: {e}")

    def run_butterworth(self):
        try:
            stage, df = self._get_current_table()
            if df is None:
                raise ValueError("Нет данных для фильтра Баттерворта.")
            if "utc_time" not in df.columns or "height" not in df.columns:
                raise ValueError("Для Баттерворта нужны колонки utc_time и height.")

            self.log("=== Фильтр Баттерворта ===")
            order = self.order_spin.value()
            period_min = self.period_spin.value()
            out_df = butterworth_on_csv(
                df=df.copy(),
                time_col="utc_time",
                height_col="height",
                period_minutes=period_min,
                order=order,
            )
            self.df_bw = out_df
            self.log(f"Баттерворт применён к слою {stage}, порядок={order}, период={period_min} мин")
            self.plot_layers()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка фильтра Баттерворта", str(e))
            self.log(f"Ошибка фильтра Баттерворта: {e}")

    def run_median(self):
        try:
            stage, df = self._get_current_table()
            if df is None:
                raise ValueError("Нет данных для медианного фильтра.")
            if "height_bw" not in df.columns:
                raise ValueError("Сначала выполните Баттерворт: отсутствует колонка height_bw.")

            self.log("=== Медианный фильтр ===")
            cfg = MedianFilterConfig(
                value_column="height_bw",
                output_column="height_med",
                residual_column="residual_med_mm",
                window_points=self.window_points_spin.value(),
                threshold_mm=self.threshold_mm_spin.value(),
            )
            filt = MedianResidualFilter(cfg)
            out_df = filt.apply(df.copy())
            self.df_med = out_df
            self.log(f"Медианный фильтр применён к слою {stage}: окно={cfg.window_points}, порог={cfg.threshold_mm} мм")
            self.plot_layers()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка медианного фильтра", str(e))
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

    def _get_current_table(self):
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
        for name, df in [("med", self.df_med), ("bw", self.df_bw), ("clean", self.df_clean), ("validated", self.df_validated), ("raw", self.df_raw)]:
            if df is not None:
                return name, df
        return "raw", None

    def _pick_plot_column(self, df: pd.DataFrame, stage_name: str):
        if stage_name == "med" and "height_med" in df.columns:
            return "height_med"
        if stage_name == "bw" and "height_bw" in df.columns:
            return "height_bw"
        if "height" in df.columns:
            return "height"
        return None

    def plot_layers(self):
        try:
            self.canvas.ax.clear()
            plotted = False

            def plot_df(df, label, color, stage_name):
                nonlocal plotted
                if df is None or df.empty:
                    return
                if "utc_time" not in df.columns:
                    return
                y_col = self._pick_plot_column(df, stage_name)
                if not y_col:
                    return
                t = pd.to_datetime(df["utc_time"], errors="coerce")
                y = pd.to_numeric(df[y_col], errors="coerce")
                mask = t.notna() & y.notna()
                if not mask.any():
                    return
                t = t[mask]
                y = y[mask]
                if self.y_mode == "mean_mm":
                    y = (y - y.mean()) * 1000.0
                self.canvas.ax.plot(t, y, label=label, color=color, linewidth=0.8)
                plotted = True

            if self.cb_raw.isChecked():
                plot_df(self.df_raw, "Исходный", "C0", "raw")
            if self.cb_valid.isChecked():
                plot_df(self.df_validated, "После проверки времени", "C1", "validated")
            if self.cb_clean.isChecked():
                plot_df(self.df_clean, "После очистки", "C2", "clean")
            if self.cb_bw.isChecked():
                plot_df(self.df_bw, "Баттерворт", "C3", "bw")
            if self.cb_med.isChecked():
                plot_df(self.df_med, "Медианный", "C4", "med")

            self.canvas.ax.set_title(self.current_file.name if self.current_file else "GNSS график")
            self.canvas.ax.set_xlabel("Время UTC")
            self.canvas.ax.set_ylabel("Высота, м" if self.y_mode == "absolute_m" else "Отклонение от среднего, мм")
            self.canvas.ax.grid(True, alpha=0.3)

            locator = mdates.AutoDateLocator(minticks=12, maxticks=24)
            formatter = mdates.ConciseDateFormatter(locator)
            self.canvas.ax.xaxis.set_major_locator(locator)
            self.canvas.ax.xaxis.set_major_formatter(formatter)

            if plotted:
                self.canvas.ax.legend(loc="upper left")
            self.canvas.fig.tight_layout()
            self.canvas.draw()
        except Exception as e:
            self.log(f"Ошибка графика: {e}")

    def save_current_csv(self):
        try:
            stage, df = self._get_current_table()
            if df is None:
                raise ValueError("Нет таблицы для сохранения.")
            default_name = f"{stage}.csv" if not self.current_file else f"{self.current_file.stem}_{stage}.csv"
            out_path, _ = QFileDialog.getSaveFileName(self, "Сохранить CSV", str(default_name), "CSV files (*.csv)")
            if not out_path:
                return
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            self.log(f"Сохранена таблица {stage}: {out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения CSV", str(e))
            self.log(f"Ошибка сохранения CSV: {e}")

    def save_current_jpg(self):
        try:
            default_name = "plot.jpg" if not self.current_file else f"{self.current_file.stem}_plot.jpg"
            out_path, _ = QFileDialog.getSaveFileName(self, "Сохранить график JPG", str(default_name), "JPG files (*.jpg)")
            if not out_path:
                return
            if not out_path.lower().endswith(".jpg"):
                out_path += ".jpg"
            self.canvas.fig.set_size_inches(12, 6)
            self.canvas.fig.tight_layout()
            self.canvas.fig.savefig(out_path, dpi=300, bbox_inches="tight")
            self.log(f"График сохранён в JPG: {out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения JPG", str(e))
            self.log(f"Ошибка сохранения JPG: {e}")

    def save_log(self):
        try:
            default_name = "processing_log.txt" if not self.current_file else f"{self.current_file.stem}_processing_log.txt"
            out_path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить лог",
                str(default_name),
                "Text files (*.txt);;JSON files (*.json)",
            )
            if not out_path:
                return
            suffix = Path(out_path).suffix.lower()
            if suffix == ".json":
                Path(out_path).write_text(self.log_model.to_json(), encoding="utf-8")
            else:
                Path(out_path).write_text(self.log_model.to_text(), encoding="utf-8")
            self.log(f"Лог сохранён: {out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения лога", str(e))
            self.log(f"Ошибка сохранения лога: {e}")


def main():
    app = QApplication(sys.argv)
    w = GNSSMainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
