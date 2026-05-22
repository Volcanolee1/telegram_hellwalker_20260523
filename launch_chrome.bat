@echo off
setlocal enabledelayedexpansion

REM ======================================================================
REM  launch_chrome.bat -- start a real Chrome with CDP port 9222
REM  ASCII only + CRLF + delayed-expansion to avoid the "(x86)" paren bug
REM ======================================================================

set "CHROME_EXE=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "USER_DATA=C:\Users\36121\Desktop\news_commander_project\automation_chrome"

echo ======================================================================
echo  launch_chrome.bat - diagnostic mode
echo ======================================================================
echo.

REM ---- 1. locate chrome.exe ----
if not exist "!CHROME_EXE!" (
    echo [X] chrome.exe not found at: !CHROME_EXE!
    echo     Edit CHROME_EXE in this script if your Chrome lives elsewhere.
    pause
    exit /b 1
)
echo [1/5] chrome.exe OK: !CHROME_EXE!

REM ---- 2. profile dir ----
if not exist "!USER_DATA!" (
    echo [X] profile dir not found: !USER_DATA!
    pause
    exit /b 1
)
echo [2/5] profile dir OK: !USER_DATA!

REM ---- 3. is 9222 already alive? ----
netstat -ano | findstr ":9222" | findstr "LISTENING" >nul
if !errorlevel!==0 (
    echo [3/5] port 9222 already LISTENING -- a debug Chrome is already running.
    echo       Just go run: python patrol.py
    echo.
    pause
    exit /b 0
)
echo [3/5] port 9222 is free.

REM ---- 4. kill stale automation_chrome instances only ----
echo [4/5] cleaning stale automation_chrome instances (your other Chrome stays alive)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*automation_chrome*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
timeout /t 1 /nobreak >nul

REM ---- 5. launch ----
echo [5/5] launching Chrome...
echo.
echo command line:
echo   "!CHROME_EXE!" --remote-debugging-port=9222 --user-data-dir="!USER_DATA!" --profile-directory=Default --no-first-run --no-default-browser-check
echo.

start "" "!CHROME_EXE!" --remote-debugging-port=9222 --user-data-dir="!USER_DATA!" --profile-directory=Default --no-first-run --no-default-browser-check

echo waiting 4 seconds for port to come up...
timeout /t 4 /nobreak >nul

netstat -ano | findstr ":9222" | findstr "LISTENING" >nul
if !errorlevel!==0 (
    echo.
    echo [OK] port 9222 is now LISTENING. Chrome is ready to be taken over.
    echo      Next step: python patrol.py
) else (
    echo.
    echo [WARN] Chrome started but port 9222 is NOT listening. Likely causes:
    echo.
    echo   A) Your normal Chrome is running and merged the new launch.
    echo      Fix: close ALL Chrome windows (incl. tray icon), run this again.
    echo.
    echo   B) Antivirus / firewall blocked the port.
    echo      Fix: check Windows Defender / 360 / Huorong intercept logs.
    echo.
    echo   C) Chrome failed to start.
    echo      Fix: paste the command line above into Win+R and see the error.
)

echo.
pause
