@echo off
chcp 65001 >nul
title Chenmo - Git Push Auto
setlocal

REM ==========================================================================
REM  Chenmo - commit + push to GitHub, which triggers the
REM  GitHub Actions workflow: test -> deploy to Cloud Run.
REM
REM  Usage:
REM    git_push_auto.bat                 auto message  "fix: YYYYMMDD-NNN"
REM    git_push_auto.bat "your message"  custom commit message
REM    git_push_auto.bat --skip-tests    skip the local pytest gate
REM
REM  Put this file in the chenmo project root (next to requirements.txt).
REM ==========================================================================

set SKIP_TESTS=
set CUSTOM_MSG=
if /i "%~1"=="--skip-tests" (set SKIP_TESTS=1) else if /i "%~1"=="-s" (set SKIP_TESTS=1) else if not "%~1"=="" set CUSTOM_MSG=%~1

REM -- go to the folder this .bat lives in (avoids typing the Chinese path)
cd /d "%~dp0"

echo.
echo ==========================================
echo  Directory:
cd
echo ==========================================
echo.

if not exist .git (
    echo [ERROR] This folder is not a git repository.
    pause
    exit /b 1
)

REM -- clear stale index.lock (OneDrive sometimes leaves one behind)
if exist .git\index.lock (
    echo [WARN] Removing stale .git\index.lock...
    del /f .git\index.lock
    echo [OK] index.lock removed
    echo.
)

REM -- commit message
if defined CUSTOM_MSG (
    set "COMMIT_MSG=%CUSTOM_MSG%"
    goto :msg_done
)
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%i
for /f %%i in ('powershell -NoProfile -Command "$today='%TODAY%'; $msgs = git log --pretty=format:\"%%s\" --since='midnight' 2>$null; $nums = $msgs | ForEach-Object { if ($_ -match ('^fix: '+$today+'-(\d+)$')) { [int]$Matches[1] } }; if ($nums) { ($nums | Measure-Object -Maximum).Maximum + 1 } else { 1 }"') do set SEQ=%%i
set SEQ=00%SEQ%
set SEQ=%SEQ:~-3%
set "COMMIT_MSG=fix: %TODAY%-%SEQ%"
:msg_done
echo Commit Message: %COMMIT_MSG%
echo.

REM -- force re-read all file contents (fixes OneDrive mtime issue)
git update-index --really-refresh >nul 2>&1

echo ==========================================
echo Changed files:
echo ==========================================
git status --short
echo.

for /f %%i in ('git status --porcelain ^| find /c /v ""') do set CHANGED=%%i
if "%CHANGED%"=="0" (
    echo No changes detected. Nothing to commit.
    echo.
    echo Checking for unpushed commits...
    git push origin main
    if errorlevel 1 (
        echo [ERROR] Push failed! Check GitHub credentials or network.
        pause
        exit /b 1
    )
    goto :done
)

REM -- local test gate (same tests GitHub Actions runs; fails fast before pushing)
if "%SKIP_TESTS%"=="1" (
    echo [WARN] --skip-tests: local tests were NOT run.
    echo.
    goto :tests_done
)
set PY=
if exist .venv\Scripts\python.exe set PY=.venv\Scripts\python.exe
if not defined PY if exist C:\venvs\chenmo\Scripts\python.exe set PY=C:\venvs\chenmo\Scripts\python.exe
if not defined PY (
    echo [WARN] No virtualenv found ^(.venv or C:\venvs\chenmo^). Skipping local tests.
    echo        GitHub Actions will still run them before deploying.
    echo.
    goto :tests_done
)
echo ==========================================
echo Running tests: %PY% -m pytest -q
echo ==========================================
"%PY%" -m pytest -q -p no:cacheprovider
if errorlevel 1 (
    echo.
    echo ==========================================
    echo  [ERROR] Tests FAILED -- nothing was committed.
    echo  Fix the code, or run:  git_push_auto.bat --skip-tests
    echo ==========================================
    pause
    exit /b 1
)
echo [OK] Tests passed.
echo.
:tests_done

REM -- git add (double-add for OneDrive reliability)
git add -A
git update-index --really-refresh >nul 2>&1
git add -A
if errorlevel 1 (
    echo [ERROR] git add failed!
    pause
    exit /b 1
)

REM -- safety: never commit secrets / local env
for /f %%i in ('git diff --cached --name-only ^| findstr /i /r "^\.env$ ^\.venv/ \.db$"') do (
    echo [ERROR] Refusing to commit secret/local file: %%i
    echo         Check .gitignore, then run:  git reset
    pause
    exit /b 1
)

echo.
echo ==========================================
echo Files to be committed:
echo ==========================================
git diff --cached --name-status
echo.
git diff --cached --stat
echo.

for /f %%i in ('git diff --cached --name-only ^| find /c /v ""') do set STAGED=%%i
if "%STAGED%"=="0" (
    echo [WARN] Nothing staged. Aborting.
    pause
    exit /b 0
)

git commit -m "%COMMIT_MSG%"
if errorlevel 1 (
    echo [ERROR] Commit failed!
    pause
    exit /b 1
)

echo.
git push origin main
if errorlevel 1 (
    echo [ERROR] Push failed! Check GitHub credentials or network.
    pause
    exit /b 1
)

:done
echo.
echo ==========================================
echo Done! Pushed to GitHub.
echo ==========================================
echo.
echo Latest 5 commits:
git log --oneline -5
echo.
echo GitHub Actions (test + deploy, about 5 min):
echo   https://github.com/Samuelhuang-com/chenmo/actions
echo Website:
echo   https://chenmo-99237960339.asia-east1.run.app
echo.
choice /c YN /n /t 10 /d N /m "Open GitHub Actions in browser? [Y/N] (auto N in 10s) "
if errorlevel 2 goto :end
start "" https://github.com/Samuelhuang-com/chenmo/actions
:end
echo ==========================================
pause
