@echo off
setlocal enabledelayedexpansion
rem backend/frontendをポート上の既存プロセスをkillしてからバックグラウンドで再起動する。
rem docs/architecture.md「バックエンド運用上の注意（Windows: uvicorn --reload の多重プロセス）」
rem が説明する「netstat -ano | findstr :8000 で全PIDを確認しtaskkillで終了してから再起動」
rem という手動手順を1コマンド化したもの（改善計画T47・複雑度平衡レビュー第4回R-10で整理）。
rem 停止のみ行いたい場合はstop-dev.batを使う。ログは.\logs\（.gitignore対象）へ出力される。

set "ROOT=%~dp0"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=3000"

if not exist "%ROOT%logs" mkdir "%ROOT%logs"

echo ===============================================
echo  RideCompass local restart (background, no window)
echo ===============================================
echo.

call :kill_port %BACKEND_PORT% backend
call :kill_port %FRONTEND_PORT% frontend

echo.
echo Starting backend in background...
powershell -NoProfile -Command "Start-Process -FilePath '%ROOT%backend\.venv\Scripts\python.exe' -ArgumentList '-u -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%' -WorkingDirectory '%ROOT%backend' -WindowStyle Hidden -RedirectStandardOutput '%ROOT%logs\backend.log' -RedirectStandardError '%ROOT%logs\backend.err.log'"

echo Starting frontend in background...
powershell -NoProfile -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c npm run dev' -WorkingDirectory '%ROOT%frontend' -WindowStyle Hidden -RedirectStandardOutput '%ROOT%logs\frontend.log' -RedirectStandardError '%ROOT%logs\frontend.err.log'"

echo.
echo Checking backend health...
set "BACKEND_UP=0"
for /l %%i in (1,1,20) do (
    if "!BACKEND_UP!"=="0" (
        curl -s -o nul "http://127.0.0.1:%BACKEND_PORT%/health" >nul 2>nul
        if not errorlevel 1 (set "BACKEND_UP=1") else (timeout /t 1 >nul)
    )
)

echo Checking frontend health...
set "FRONTEND_UP=0"
for /l %%i in (1,1,30) do (
    if "!FRONTEND_UP!"=="0" (
        curl -s -o nul "http://127.0.0.1:%FRONTEND_PORT%/" >nul 2>nul
        if not errorlevel 1 (set "FRONTEND_UP=1") else (timeout /t 1 >nul)
    )
)

echo.
if "%BACKEND_UP%"=="1" (
    echo   backend : http://127.0.0.1:%BACKEND_PORT% - OK
) else (
    echo   backend : http://127.0.0.1:%BACKEND_PORT% - not responding yet, check logs\backend.log / backend.err.log
)
if "%FRONTEND_UP%"=="1" (
    echo   frontend: http://127.0.0.1:%FRONTEND_PORT% - OK
) else (
    echo   frontend: http://127.0.0.1:%FRONTEND_PORT% - not responding yet, check logs\frontend.log / frontend.err.log
)
echo.
echo Both run hidden in the background (no console window). Logs are in .\logs\
echo Run stop-dev.bat to stop them.
echo.
pause
goto :eof

:kill_port
set "PORT=%~1"
set "LABEL=%~2"
set "FOUND=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    echo Stopping existing %LABEL% process on port %PORT% (PID=%%P^)
    taskkill /F /PID %%P >nul 2>nul
    set "FOUND=1"
)
if "!FOUND!"=="0" echo No existing %LABEL% process found on port %PORT%
goto :eof
