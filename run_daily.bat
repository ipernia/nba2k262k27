@echo off
setlocal

cd /d "%~dp0"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Error: no se encontro el entorno virtual .venv.
    echo Sigue las instrucciones de instalacion del README.md.
    exit /b 1
)

"%PYTHON_EXE%" -m nba_stats %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo La actualizacion de NBA fallo. Consulta logs\nba_stats.log.
    exit /b %EXIT_CODE%
)

exit /b 0
