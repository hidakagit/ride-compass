@echo off
setlocal enabledelayedexpansion
rem backend/frontendをポート上の既存プロセスをkillしてからバックグラウンドで再起動する。
rem docs/architecture/tech-stack.md「Windows: uvicorn --reloadの多重プロセス」が説明する
rem 「netstat -ano | findstr :8000 で全PIDを確認しtaskkillで終了してから再起動」という
rem 手動手順を1コマンド化したもの。
rem 止める段と番号の決め方はstop-dev.batが持つ（停止のみ行いたい場合もそちらを使う）。
rem frontendはその番号を明示してnext devを起こすので、番号が使用中なら別の番号へ逃げずに起動に失敗する。
rem ログは.\logs\（.gitignore対象）へ出力される。

set "ROOT=%~dp0"

if not exist "%ROOT%logs" mkdir "%ROOT%logs"

echo ===============================================
echo  RideCompass local restart (background, no window)
echo ===============================================
echo.

call "%ROOT%stop-dev.bat" nopause
if not defined FRONTEND_PORT (
    pause
    exit /b 1
)

echo.
echo Starting backend in background...
powershell -NoProfile -Command "Start-Process -FilePath '%ROOT%backend\.venv\Scripts\python.exe' -ArgumentList '-u -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%' -WorkingDirectory '%ROOT%backend' -WindowStyle Hidden -RedirectStandardOutput '%ROOT%logs\backend.log' -RedirectStandardError '%ROOT%logs\backend.err.log'"

echo Starting frontend in background...
powershell -NoProfile -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c npm run dev -- --port %FRONTEND_PORT%' -WorkingDirectory '%ROOT%frontend' -WindowStyle Hidden -RedirectStandardOutput '%ROOT%logs\frontend.log' -RedirectStandardError '%ROOT%logs\frontend.err.log'"

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
