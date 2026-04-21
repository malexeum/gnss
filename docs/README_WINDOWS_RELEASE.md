# Windows onedir package with GitHub auto-update

Этот комплект делает релиз без инсталлятора:
- собирает `dist/GNSS_GUI/`;
- делает ZIP для GitHub Releases;
- поддерживает папку `docs/` как обязательную часть поставки;
- готовит задел под автообновление через `latest.json`.

## Обязательная структура проекта

```text
project/
├─ app/
│  ├─ version.py
│  ├─ core/
│  └─ gui/
│     └─ gnss_gui_v3_5_6.py
├─ assets/
│  └─ app.ico
├─ docs/
│  └─ README.md
├─ data/
│  ├─ input/
│  └─ output/
├─ packaging/
│  ├─ run_gnss_gui.py
│  ├─ gnss_gui.spec
│  ├─ build_release.py
│  ├─ build_windows_release.bat
│  ├─ updater.bat
│  └─ version_info.txt   # генерируется автоматически
└─ requirements.txt
```

## Шаги

1. Скопируй файлы из этого комплекта в `packaging/` и `app/`.
2. Создай папку `docs/`, даже если документация пока черновая.
3. Проверь, что `assets/app.ico` существует.
4. Обнови `app/version.py` — имя, версию и GitHub ссылки.
5. Создай среду:

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -U pip setuptools wheel
pip install -r requirements.txt
pip install pyinstaller
```

6. Собери релиз:

```bat
packaging\build_windows_release.bat
```

## Результат

- Рабочая папка приложения: `dist/GNSS_GUI/`
- Архив для GitHub Releases: `releases/GNSS_GUI_<version>_win64.zip`

## Публикация на GitHub Releases

1. Создай тег `v3.5.6`
2. Открой Releases
3. Прикрепи ZIP из `releases/`
4. Опубликуй `latest.json` по постоянной ссылке, например через raw GitHub

## Подключение обновления в GUI

Добавь кнопку `Проверить обновления` и вызов:

```python
from app.github_updater import run_zip_update

btn_update = QPushButton('Проверить обновления')
btn_update.clicked.connect(lambda: run_zip_update(self))
```

## Важно

- Приложение обновляет папку, а не один запущенный exe.
- Это надёжнее для onedir-сборки.
- Если нужен отдельный EXE для скачивания, его можно брать из `dist/GNSS_GUI/GNSS_GUI.exe`, но для автообновления лучше использовать ZIP.
