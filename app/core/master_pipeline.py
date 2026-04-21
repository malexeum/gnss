from __future__ import annotations

from pathlib import Path
import traceback

import pandas as pd

from butterworth_filter import butterworth_on_csv
from data_exporter import DataExporter
from data_importer import DataImporter
from median_filter import MedianFilterConfig, MedianResidualFilter
from outlier_detector import OutlierDetector
from processing_log import ProcessingLog
from time_validator import TimeValidator

ROOT = Path(r"f:\IFZ\GNSS\Proga\test")


def run_outlier_stage(
    label: str,
    src_path: Path,
    time_col: str,
    height_col: str,
    log: ProcessingLog,
    k_sigma: float = 4.0,
    window_sec: float = 3600.0,
    min_group: int = 3,
    max_group_epochs: int = 120,
    tz_rule: str = "UTC",
    date_col: str | None = None,
) -> tuple[Path, Path]:
    print("\n" + "=" * 80)
    print(f"OUTLIER: {label}")
    print(f"FILE: {src_path}")
    print("=" * 80)

    importer = DataImporter()
    validator = TimeValidator()
    validator.set_tz_rule(tz_rule)

    rt = importer.load(str(src_path))
    importer.set_columns(time_col=time_col, height_col=height_col)

    nt = validator.validate(
        raw_table=rt,
        time_col=time_col,
        height_col=height_col,
        date_col=date_col,
    )
    print(nt.report.to_text())

    detector = OutlierDetector(
        time_col="utc_time",
        height_col="height",
        k_sigma=k_sigma,
        window_sec=window_sec,
        min_group=min_group,
        max_group_epochs=max_group_epochs,
    )
    clean_df, removed_df, flagged_df, report = detector.run(nt.df)
    print(report)

    stem = src_path.stem.replace(" ", "_")
    clean_path = src_path.with_name(f"{stem}_clean.csv")
    removed_path = src_path.with_name(f"{stem}_removed.csv")
    flagged_path = src_path.with_name(f"{stem}_flagged.csv")

    clean_df.to_csv(clean_path, index=False, encoding="utf-8-sig")
    removed_df.to_csv(removed_path, index=False, encoding="utf-8-sig")
    if flagged_df is not None and not flagged_df.empty:
        flagged_df.to_csv(flagged_path, index=False, encoding="utf-8-sig")

    print(f"Очищенный ряд: {clean_path}")
    print(f"Удалённые точки: {removed_path}")
    if flagged_df is not None and not flagged_df.empty:
        print(f"Помеченные точки: {flagged_path}")

    log.add(
        module="OutlierDetector",
        params={
            "label": label,
            "file_src": str(src_path),
            "file_clean": str(clean_path),
            "file_removed": str(removed_path),
            "file_flagged": str(flagged_path) if flagged_df is not None and not flagged_df.empty else None,
            "source_time_col": time_col,
            "source_height_col": height_col,
            "pipeline_time_col": "utc_time",
            "pipeline_height_col": "height",
            "k_sigma": k_sigma,
            "window_sec": window_sec,
            "min_group": min_group,
            "max_group_epochs": max_group_epochs,
            "n_input": len(nt.df),
            "n_output": len(clean_df),
            "n_removed": len(removed_df),
            "n_flagged": len(flagged_df) if flagged_df is not None else 0,
        },
        summary="Очистка выбросов и дублей",
    )
    return clean_path, removed_path


def run_butter_stage(
    label: str,
    clean_path: Path,
    log: ProcessingLog,
    period_minutes: float = 30.0,
    order: int = 4,
) -> Path:
    print("\n" + "=" * 80)
    print(f"BUTTERWORTH: {label}")
    print(f"CLEAN FILE: {clean_path}")
    print("=" * 80)

    if not clean_path.exists():
        raise FileNotFoundError(f"Нет clean-файла: {clean_path}")

    stem = clean_path.stem.replace(" ", "_")
    bw_path = clean_path.with_name(f"{stem}_bw_{int(period_minutes)}min.csv")

    out_df = butterworth_on_csv(
        input_csv=str(clean_path),
        output_csv=str(bw_path),
        time_col="utc_time",
        height_col="height",
        order=order,
        period_minutes=period_minutes,
    )

    print(f"Файл после Баттерворта: {bw_path}")
    print(f"Колонки BW: {list(out_df.columns)}")

    log.add(
        module="ButterworthFilter",
        params={
            "label": label,
            "file_in": str(clean_path),
            "file_out": str(bw_path),
            "time_col": "utc_time",
            "height_col": "height",
            "order": order,
            "period_minutes": period_minutes,
            "n_rows": len(out_df),
        },
        summary="НЧ фильтр Баттерворта",
    )
    return bw_path


def run_median_stage(
    label: str,
    bw_path: Path,
    log: ProcessingLog,
    window_points: int = 9,
    threshold_mm: float = 5.0,
) -> Path:
    print("\n" + "=" * 80)
    print(f"MEDIAN: {label}")
    print(f"BW FILE: {bw_path}")
    print("=" * 80)

    if not bw_path.exists():
        raise FileNotFoundError(f"Нет BW-файла: {bw_path}")

    df = pd.read_csv(bw_path)
    cfg = MedianFilterConfig(
        value_column="height_bw",
        output_column="height_med",
        residual_column="residual_med_mm",
        window_points=window_points,
        threshold_mm=threshold_mm,
    )
    filt = MedianResidualFilter(cfg)
    out = filt.apply(df)
    stats = filt.summary(out, output_column="height_med")

    stem = bw_path.stem.replace(" ", "_")
    med_path = bw_path.with_name(f"{stem}_med_w{window_points}_t{int(threshold_mm)}mm.csv")
    out.to_csv(med_path, index=False, encoding="utf-8-sig")

    print(f"Финальный ряд после медианного: {med_path}")
    print(f"Всего точек: {stats['n_total']}")
    print(f"Заменено: {stats['n_replaced']}")
    print(f"Доля замен: {stats['share_replaced_percent']:.4f} %")
    print(f"Среднее: {stats['output_mean_m']:.6f} м")
    print(f"СКО: {stats['output_std_m']:.6f} м")

    log.add(
        module="MedianFilter",
        params={
            "label": label,
            "file_in": str(bw_path),
            "file_out": str(med_path),
            "value_column": "height_bw",
            "output_column": "height_med",
            "residual_column": "residual_med_mm",
            "window_points": window_points,
            "threshold_mm": threshold_mm,
            "n_total": stats["n_total"],
            "n_replaced": stats["n_replaced"],
            "share_replaced_percent": stats["share_replaced_percent"],
        },
        summary="Медианный фильтр остаточных выбросов",
    )
    return med_path


def run_pipeline_for_file(
    label: str,
    src_path: Path,
    time_col: str,
    height_col: str,
    log: ProcessingLog,
    exporter: DataExporter,
    tz_rule: str = "UTC",
    date_col: str | None = None,
):
    clean_path, removed_path = run_outlier_stage(
        label=label,
        src_path=src_path,
        time_col=time_col,
        height_col=height_col,
        log=log,
        tz_rule=tz_rule,
        date_col=date_col,
    )

    bw_path = run_butter_stage(
        label=label,
        clean_path=clean_path,
        log=log,
        period_minutes=30.0,
        order=4,
    )

    final_path = run_median_stage(
        label=label,
        bw_path=bw_path,
        log=log,
        window_points=9,
        threshold_mm=5.0,
    )

    final_df = pd.read_csv(final_path)
    removed_df = pd.read_csv(removed_path) if removed_path.exists() else pd.DataFrame()
    safe_label = label.replace(" ", "_")

    exporter.set_units("m")
    exporter.export_table(final_df, path=ROOT / f"{safe_label}_final_m.csv", fmt="csv")

    exporter.set_units("mm")
    exporter.export_table(final_df, path=ROOT / f"{safe_label}_final_mm.csv", fmt="csv")

    if not removed_df.empty:
        exporter.export_flags(removed_df, path=ROOT / f"{safe_label}_flags_removed.csv")

    print(f"Экспорт финальных таблиц для {label} завершён.")


def main():
    log = ProcessingLog(version="0.2.0")
    exporter = DataExporter(units="m")

    cases = [
        {"label": "BazaA1014a 1s", "fname": "BazaA1014a_height test 1s.csv", "time_col": "datetime_utc", "height_col": "height_m", "tz_rule": "UTC"},
        {"label": "nya2 merged North", "fname": "nya2_merged North.txt", "time_col": "utc_time", "height_col": "height", "tz_rule": "UTC"},
        {"label": "dav1 merged raw", "fname": "dav1_merged.txt", "time_col": "utc_time", "height_col": "height", "tz_rule": "UTC"},
        {"label": "dav1 merged groops anom", "fname": "dav1_merged groops anom.txt", "time_col": "utc_time", "height_col": "height", "tz_rule": "UTC"},
        {"label": "mad2 merged BEST 30s", "fname": "mad2_merged BEST 30s.txt", "time_col": "utc_time", "height_col": "height", "tz_rule": "UTC"},
        {"label": "GPS half-year", "fname": "GPS.xlsx", "time_col": "Дата-Время", "height_col": "Высота (м)", "tz_rule": "UTC"},
        {"label": "GLO half-year", "fname": "GLO.xlsx", "time_col": "Дата-Время", "height_col": "Высота (м)", "tz_rule": "UTC"},
        {"label": "GPS_GLO half-year", "fname": "GPS_GLO.xlsx", "time_col": "Дата-Время", "height_col": "Высота (м)", "tz_rule": "UTC"},
        {"label": "Ledovo local", "fname": "Ledovo.xlsx", "time_col": "Дата и время", "height_col": "Высота (м)", "tz_rule": "UTC"},
    ]

    for case in cases:
        src = ROOT / case["fname"]
        if not src.exists():
            print(f"\n!!! Исходный файл не найден, пропуск: {src}")
            log.add_warning(f"Нет исходного файла: {src}", module="pipeline")
            continue

        try:
            run_pipeline_for_file(
                label=case["label"],
                src_path=src,
                time_col=case["time_col"],
                height_col=case["height_col"],
                log=log,
                exporter=exporter,
                tz_rule=case.get("tz_rule", "UTC"),
                date_col=case.get("date_col"),
            )
        except Exception as e:
            print(f"\n!!! Ошибка при обработке {case['label']}: {e}")
            traceback.print_exc()
            log.add_error(f"{case['label']}: {e}", module="pipeline")
            continue

    exporter.export_log(log, ROOT / "processing_log_full.txt", fmt="txt")
    exporter.export_log(log, ROOT / "processing_log_full.json", fmt="json")
    print(f"\nОбщий журнал обработки сохранён в: {ROOT / 'processing_log_full.txt'}")
    print(f"JSON-журнал обработки сохранён в: {ROOT / 'processing_log_full.json'}")


if __name__ == "__main__":
    main()
