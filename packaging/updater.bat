@echo off
setlocal enabledelayedexpansion
set APP_DIR=%~1
set ZIP_FILE=%~2
set EXTRACT_DIR=%TEMP%\gnss_gui_update_%RANDOM%

if "%APP_DIR%"=="" exit /b 1
if "%ZIP_FILE%"=="" exit /b 1

mkdir "%EXTRACT_DIR%"
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%ZIP_FILE%' -DestinationPath '%EXTRACT_DIR%' -Force"
if errorlevel 1 exit /b 1

timeout /t 2 >nul
xcopy /E /Y /I "%EXTRACT_DIR%\GNSS_GUI\*" "%APP_DIR%\" >nul
start "" "%APP_DIR%\GNSS_GUI.exe"
exit /b 0
