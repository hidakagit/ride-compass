@echo off
setlocal enabledelayedexpansion
rem restart-dev.batが使うkill_portロジックだけを単独実行する（再起動はせず停止のみ）。
rem 用途はrestart-dev.batの冒頭コメント参照。

set "BACKEND_PORT=8000"
set "FRONTEND_PORT=3000"

echo Stopping RideCompass local dev servers...
echo.

call :kill_port %BACKEND_PORT% backend
call :kill_port %FRONTEND_PORT% frontend

echo.
echo Done.
pause
goto :eof

:kill_port
set "PORT=%~1"
set "LABEL=%~2"
set "FOUND=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    echo Stopping %LABEL% process on port %PORT% (PID=%%P^)
    taskkill /F /PID %%P >nul 2>nul
    set "FOUND=1"
)
if "!FOUND!"=="0" echo No %LABEL% process found on port %PORT%
goto :eof
