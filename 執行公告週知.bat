@echo off
setlocal
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%PYTHON%" goto run
set "PYTHON=C:\Users\CCSH\AppData\Local\Programs\Thonny\python.exe"
if exist "%PYTHON%" goto run
set "PYTHON=python"
:run
"%PYTHON%" "%~dp0run.py" %*
exit /b %ERRORLEVEL%
