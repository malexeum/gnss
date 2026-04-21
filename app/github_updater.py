import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

try:
    from app.version import APP_VERSION, GITHUB_LATEST_JSON_URL, APP_EXE_NAME
except Exception:
    APP_VERSION = '0.0.0'
    GITHUB_LATEST_JSON_URL = ''
    APP_EXE_NAME = 'GNSS_GUI'


def parse_version(v: str):
    return tuple(int(x) for x in v.strip().split('.'))


def app_base_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def check_update_info(timeout=10):
    if not GITHUB_LATEST_JSON_URL:
        return None
    with urllib.request.urlopen(GITHUB_LATEST_JSON_URL, timeout=timeout) as r:
        data = json.loads(r.read().decode('utf-8'))
    if parse_version(data['version']) > parse_version(APP_VERSION):
        return data
    return None


def download_file(url: str, dst: Path):
    with urllib.request.urlopen(url, timeout=60) as r, open(dst, 'wb') as f:
        shutil.copyfileobj(r, f)


def run_zip_update(parent=None):
    info = check_update_info()
    if not info:
        QMessageBox.information(parent, 'Обновление', 'Новая версия не найдена.')
        return

    answer = QMessageBox.question(
        parent,
        'Обновление доступно',
        f"Доступна версия {info['version']}. Скачать и установить?"
    )
    if answer != QMessageBox.Yes:
        return

    tmp = Path(tempfile.gettempdir())
    zip_path = tmp / f"{APP_EXE_NAME}_{info['version']}_win64.zip"
    bat_path = tmp / 'gnss_gui_updater.bat'

    download_file(info['zip_url'], zip_path)

    source_bat = Path(__file__).resolve().parents[1] / 'packaging' / 'updater.bat'
    shutil.copy2(source_bat, bat_path)

    app_dir = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]

    subprocess.Popen(['cmd', '/c', str(bat_path), str(app_dir), str(zip_path)])
    if parent is not None:
        parent.close()
