@echo off
REM build_exe.bat -- builds dist\mbd2mes.exe (MBD2MES). Local use only; do not distribute.
REM Copied from RCZ2MES dist_build\build_exe.bat (commit 5b31da8, originally LD2MES) and adapted: names, icon check, output folder.
REM Writes the version info (commit, dirty flag, build date) into dist_build\_gen before building,
REM stops if Pic\ICON\MBD2MES.ico is missing, and checks afterwards that the built exe really contains the version and the icon.
REM Usage: dist_build\build_exe.bat [output folder]   (default: dist). Use another folder while dist\mbd2mes.exe is running.
REM ASCII + CRLF on purpose (cmd.exe cannot parse UTF-8 comments).
setlocal
set "DIST=%~1"
if "%DIST%"=="" set "DIST=dist"

cd /d "%~dp0\.."
echo [build_exe] cwd=%CD% output=%DIST%

if not exist Pic\ICON\MBD2MES.ico (
    echo [build_exe] icon not found: Pic\ICON\MBD2MES.ico ^(build stopped^)
    exit /b 1
)

python tools\write_build_info.py
if errorlevel 1 (
    echo [build_exe] write_build_info failed
    exit /b 1
)

python -m PyInstaller --noconfirm --clean --distpath %DIST% dist_build\mbd2mes.spec
if errorlevel 1 (
    echo [build_exe] pyinstaller failed
    exit /b 1
)

python tools\check_exe_version.py %DIST%\mbd2mes.exe
if errorlevel 1 (
    echo [build_exe] exe version check failed
    exit /b 1
)

python -I tools\exe_icon.py %DIST%\mbd2mes.exe Pic\ICON\MBD2MES.ico
if errorlevel 1 (
    echo [build_exe] exe icon check failed
    exit /b 1
)

echo [build_exe] done: %DIST%\mbd2mes.exe
endlocal
