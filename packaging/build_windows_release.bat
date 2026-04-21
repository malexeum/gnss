@echo off
setlocal
cd /d %~dp0\..

where python >nul 2>nul
if errorlevel 1 (
  echo Python not found in PATH.
  exit /b 1
)

python packaging\build_release.py
if errorlevel 1 exit /b 1

echo.
echo Release is ready in dist\GNSS_GUI and releases\
endlocal