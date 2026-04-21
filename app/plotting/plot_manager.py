from pathlib import Path

import pandas as pd
import tkinter as tk
from tkinter import ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def prepare_time_series(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "utc_time" not in out.columns:
        raise ValueError("В таблице должен быть столбец 'utc_time'")
    out["utc_time"] = pd.to_datetime(out["utc_time"], errors="coerce", utc=True)
    out = out.dropna(subset=["utc_time"])
    out["utc_time"] = out["utc_time"].dt.tz_localize(None)
    return out


def to_mm_relative(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    return (s - s.mean()) * 1000.0


def make_stats_text(df: pd.DataFrame) -> str:
    lines = []

    def add_stats(label: str, col: str, unit_mode: str):
        if col not in df.columns:
            return
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(s) == 0:
            return
        if unit_mode == "m":
            lines.append(
                f"{label}: N={len(s)} ср={s.mean():.4f} м "
                f"СКО={s.std(ddof=1) * 1000.0:.2f} мм"
            )
        else:
            lines.append(
                f"{label}: N={len(s)} ср={s.mean():.2f} мм "
                f"СКО={s.std(ddof=1):.2f} мм"
            )

    add_stats("Исходный", "height", "m")
    add_stats("Баттерворд", "height_bw", "m")
    add_stats("Медианный", "height_med", "m")
    add_stats("Остатки BW", "residual_bw_mm", "mm")
    add_stats("Остатки MED", "residual_med_mm", "mm")

    return "\n".join(lines)


def build_plot(
    df,
    show_raw: bool,
    show_bw: bool,
    show_med: bool,
    show_res_bw: bool,
    show_res_med: bool,
    ax,
):
    ax.clear()
    t = df["utc_time"].to_numpy()

    if show_raw and "height" in df.columns:
        ax.plot(
            t,
            to_mm_relative(df["height"]).to_numpy(),
            label="Исходный",
            linewidth=0.8,
        )

    if show_bw and "height_bw" in df.columns:
        ax.plot(
            t,
            to_mm_relative(df["height_bw"]).to_numpy(),
            label="Баттерворд",
            linewidth=1.0,
        )

    if show_med and "height_med" in df.columns:
        ax.plot(
            t,
            to_mm_relative(df["height_med"]).to_numpy(),
            label="Медианный",
            linewidth=1.0,
        )

    if show_res_bw and "residual_bw_mm" in df.columns:
        ax.plot(
            t,
            pd.to_numeric(df["residual_bw_mm"], errors="coerce").to_numpy(),
            label="Остатки BW, мм",
            linewidth=0.8,
        )

    if show_res_med and "residual_med_mm" in df.columns:
        ax.plot(
            t,
            pd.to_numeric(df["residual_med_mm"], errors="coerce").to_numpy(),
            label="Остатки MED, мм",
            linewidth=0.8,
        )

    # нулевая линия
    ax.axhline(0.0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)

    ax.set_xlabel("Дата")
    ax.set_ylabel("Отклонение высоты относительно среднего, мм")
    ax.grid(True, alpha=0.3)

    locator = mdates.AutoDateLocator(minticks=10, maxticks=16)
    formatter = mdates.ConciseDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)
    ax.tick_params(axis="x", rotation=30)

    if ax.lines:
        ax.legend(loc="upper left")

    stats_text = make_stats_text(df)
    if stats_text:
        ax.text(
            0.995,
            0.995,
            stats_text,
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

    ax.figure.tight_layout()


def open_plot_window(csv_path: str):
    df = pd.read_csv(csv_path)
    df = prepare_time_series(df)

    root = tk.Tk()
    root.title(f"Профиль высоты: {csv_path}")

    fig, ax = plt.subplots(figsize=(12, 6))
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

    # toolbar Matplotlib (zoom, pan, save)
    toolbar = NavigationToolbar2Tk(canvas, root)
    toolbar.update()

    frame = ttk.Frame(root)
    frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)

    # по умолчанию: исходный, BW, медианный включены; остатки выключены
    show_raw = tk.BooleanVar(value=("height" in df.columns))
    show_bw = tk.BooleanVar(value=("height_bw" in df.columns))
    show_med = tk.BooleanVar(value=("height_med" in df.columns))
    show_res_bw = tk.BooleanVar(value=False)
    show_res_med = tk.BooleanVar(value=False)

    def redraw(*args):
        build_plot(
            df,
            show_raw.get(),
            show_bw.get(),
            show_med.get(),
            show_res_bw.get(),
            show_res_med.get(),
            ax,
        )
        canvas.draw_idle()

    for var in [show_raw, show_bw, show_med, show_res_bw, show_res_med]:
        var.trace_add("write", redraw)

    ttk.Checkbutton(frame, text="Исходный", variable=show_raw).pack(
        side=tk.LEFT, padx=4
    )
    ttk.Checkbutton(frame, text="Баттерворд", variable=show_bw).pack(
        side=tk.LEFT, padx=4
    )
    ttk.Checkbutton(frame, text="Медианный", variable=show_med).pack(
        side=tk.LEFT, padx=4
    )
    ttk.Checkbutton(frame, text="Остатки BW", variable=show_res_bw).pack(
        side=tk.LEFT, padx=4
    )
    ttk.Checkbutton(frame, text="Остатки MED", variable=show_res_med).pack(
        side=tk.LEFT, padx=4
    )

    def save_jpg():
        fig.set_size_inches(12, 6)
        fig.tight_layout()
        out_name = Path(csv_path).with_suffix("").name + "_plot.jpg"
        fig.savefig(out_name, dpi=300, bbox_inches="tight")

    btn_save = ttk.Button(frame, text="Сохранить JPG", command=save_jpg)
    btn_save.pack(side=tk.RIGHT, padx=4)

    redraw()
    root.mainloop()