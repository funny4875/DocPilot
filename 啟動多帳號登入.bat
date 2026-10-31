@echo off
setlocal
set "PYTHON=%~dp0.venv\Scripts\pythonw.exe"
if exist "%PYTHON%" goto run
set "PYTHON=C:\Users\CCSH\AppData\Local\Programs\Thonny\pythonw.exe"
if exist "%PYTHON%" goto run
set "PYTHON=pythonw"
:run
"%PYTHON%" "%~dp0account_gui.py"
exit /b %ERRORLEVEL%
