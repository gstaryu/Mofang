@echo off

chcp 65001 >nul

title Mofang Desktop



set "PYTHON=%MOFANG_PYTHON%"

if defined PYTHON if exist "%PYTHON%" goto found



for %%P in ("%USERPROFILE%\miniconda3\envs\mofang\python.exe" "%USERPROFILE%naconda3\envs\mofang\python.exe" "C:\Miniconda3\envs\mofang\python.exe" "C:\ProgramData\miniconda3\envs\mofang\python.exe") do (

    if exist %%P (

        set "PYTHON=%%~P"

        goto found

    )

)



where conda >nul 2>nul

if not errorlevel 1 (

    for /f "delims=" %%B in ('conda info --base') do (

        if exist "%%B\envs\mofang\python.exe" (

            set "PYTHON=%%B\envs\mofang\python.exe"

            goto found

        )

    )

)



echo [Mofang] conda env "mofang" not found. run start.bat first.

pause

goto eof



:found

cd /d "%~dp0"

rem ---- run via pythonw: no console window ----
set "PYTHONW=%PYTHON%"
call :dirname PYTHONW
set "PYTHONW=%PYTHONW%\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=%PYTHON%"
start "" "%PYTHONW%" "%~dp0desktop\main.py"
exit /b 0

:dirname
set "%~1=%~dp1"
exit /b 0

if errorlevel 1 (

    echo.

    echo [Mofang] crashed. see data\mofang-error.log

    pause

)

