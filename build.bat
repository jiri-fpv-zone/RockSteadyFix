@echo off
rem Builds dist\RockSteadyFix.exe (single file). Requires 64-bit Python 3.13 (py launcher or python on PATH).
setlocal
cd /d "%~dp0"
set "R=%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3.13"
if not exist .venv (
    %PY% -m venv .venv || goto :err
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements-build.txt || goto :err
python -m PyInstaller --noconfirm --clean --windowed --onefile --name RockSteadyFix ^
  --icon "%R%assets\icon.ico" --splash "%R%assets\splash.png" --version-file "%R%assets\version_info.txt" ^
  --add-data "%R%assets\icon.ico;assets" --add-data "%R%assets\icon.png;assets" --add-data "%R%assets\ig.png;assets" ^
  --collect-all tkinterdnd2 --collect-data customtkinter ^
  --exclude-module scipy --exclude-module matplotlib ^
  --workpath build --specpath build --distpath dist "%R%app.py" || goto :err
echo.
echo Done: dist\RockSteadyFix.exe
exit /b 0
:err
echo Build failed.
exit /b 1
