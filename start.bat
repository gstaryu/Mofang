@echo off

chcp 65001 >nul

title Mofang Web



rem ---- locate python in conda env "mofang" ----

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



echo [Mofang] conda env "mofang" not found, creating...

conda create -n mofang python=3.11 -y || goto err

for /f "delims=" %%B in ('conda info --base') do set "PYTHON=%%B\envs\mofang\python.exe"

if not exist "%PYTHON%" goto err



:found

"%PYTHON%" -c "import fastapi, PIL, fontTools, img2pdf, numpy" >nul 2>nul || (

    echo [Mofang] installing dependencies...

    "%PYTHON%" -m pip install -r "%~dp0requirements.txt" || goto err

)



echo [Mofang] starting server: http://127.0.0.1:8642/

rem ---- service runs windowless via pythonw ----
set "PYTHONW=%PYTHON%"
call :dirname PYTHONW
set "PYTHONW=%PYTHONW%\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=%PYTHON%"
start "" /b "%PYTHONW%" -m uvicorn server.app:app --port 8642
goto wait

:dirname
set "%~1=%~dp1"
exit /b 0

:wait



set /a tries=0

:wait

powershell -NoProfile -Command "try{ iwr 'http://127.0.0.1:8642/' -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 }catch{ exit 1 }" >nul 2>nul

if not errorlevel 1 (

    start "" http://127.0.0.1:8642/

    echo [Mofang] ready. browser opened. stop service: taskkill /im pythonw.exe /f

    timeout /t 2 >nul

    exit /b 0

)

set /a tries+=1

if %tries% lss 30 (

    timeout /t 1 >nul

    goto wait

)

echo [Mofang] timeout. run data\mofang-run.log check or retry.

pause

goto eof



:err

echo [Mofang] failed. check conda / network.

pause

