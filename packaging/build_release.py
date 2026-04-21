from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / 'packaging'
DIST = PACKAGING / 'dist'
BUILD = PACKAGING / 'build'
RELEASES = ROOT / 'releases'

sys.path.insert(0, str(ROOT / 'app'))
from version import APP_NAME, APP_EXE_NAME, APP_VERSION, COMPANY_NAME


def version_tuple(v: str):
    parts = [int(x) for x in v.split('.')]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def make_version_file():
    v = version_tuple(APP_VERSION)
    txt = textwrap.dedent(f"""
    VSVersionInfo(
      ffi=FixedFileInfo(
        filevers={v},
        prodvers={v},
        mask=0x3f,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0)
      ),
      kids=[
        StringFileInfo([
          StringTable(
            '040904B0',
            [
              StringStruct('CompanyName', '{COMPANY_NAME}'),
              StringStruct('FileDescription', '{APP_NAME}'),
              StringStruct('FileVersion', '{APP_VERSION}'),
              StringStruct('InternalName', '{APP_EXE_NAME}'),
              StringStruct('OriginalFilename', '{APP_EXE_NAME}.exe'),
              StringStruct('ProductName', '{APP_NAME}'),
              StringStruct('ProductVersion', '{APP_VERSION}')
            ]
          )
        ]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])
      ]
    )
    """).strip()
    (PACKAGING / 'version_info.txt').write_text(txt, encoding='utf-8')


def clean_dirs():
    for p in (BUILD, DIST):
        if p.exists():
            shutil.rmtree(p)


def build():
    subprocess.run(
        ['pyinstaller', '--noconfirm', '--clean', 'gnss_gui.spec'],
        check=True,
        cwd=PACKAGING
    )


def copytree_if_exists(src: Path, dst: Path):
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def movetree_if_exists(src: Path, dst: Path):
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.move(str(src), str(dst))


def stage_runtime_folders():
    app_dir = DIST / APP_EXE_NAME

    runtime_data_dir = app_dir / 'data'
    runtime_docs_dir = app_dir / 'docs'

    runtime_input_dir = runtime_data_dir / 'input'
    runtime_output_dir = runtime_data_dir / 'output'

    runtime_input_dir.mkdir(parents=True, exist_ok=True)
    runtime_output_dir.mkdir(parents=True, exist_ok=True)

    # 1) Перемещаем data/docs из _internal, если PyInstaller их туда положил
    internal_data_dir = app_dir / '_internal' / 'data'
    internal_docs_dir = app_dir / '_internal' / 'docs'

    movetree_if_exists(internal_data_dir, runtime_data_dir)
    movetree_if_exists(internal_docs_dir, runtime_docs_dir)

    # 2) Накладываем поверх (при необходимости) исходные data/docs из проекта
    source_input_dir = ROOT / 'data' / 'input'
    source_output_dir = ROOT / 'data' / 'output'
    source_docs_dir = ROOT / 'docs'

    copytree_if_exists(source_input_dir, runtime_input_dir)
    copytree_if_exists(source_output_dir, runtime_output_dir)
    copytree_if_exists(source_docs_dir, runtime_docs_dir)


def zip_release():
    RELEASES.mkdir(parents=True, exist_ok=True)
    src_dir = DIST / APP_EXE_NAME
    zip_path = RELEASES / f'{APP_EXE_NAME}_{APP_VERSION}_win64.zip'

    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for p in src_dir.rglob('*'):
            zf.write(p, p.relative_to(DIST))

    return zip_path


def main():
    make_version_file()
    clean_dirs()
    build()
    stage_runtime_folders()
    zip_path = zip_release()
    print(f'Build done: {DIST / APP_EXE_NAME}')
    print(f'ZIP done: {zip_path}')


if __name__ == '__main__':
    main()