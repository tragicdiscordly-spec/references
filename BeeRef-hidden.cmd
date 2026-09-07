@echo off
setlocal
cd /d "%~dp0"

rem Find an installed Python without depending on the removed Python 3.10 path.
rem Some installations provide python.exe but not pythonw.exe; the VBS
rem launcher already hides this process, so python.exe is a safe fallback.
set "PYTHON_EXE="
set "PYTHON_ARGS="
for %%V in (312 311 310) do (
    if not defined PYTHON_EXE if exist "%LocalAppData%\Programs\Python\Python%%V\pythonw.exe" (
        set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python%%V\pythonw.exe"
    )
    if not defined PYTHON_EXE if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" (
        set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python%%V\python.exe"
    )
)

rem Fall back to the Python launcher or PATH when Python was installed
rem somewhere other than the standard per-user directory. Check the
rem interpreter before selecting it so a missing 3.12 does not produce a
rem false-success launch with an invalid version flag.
for %%L in (pyw.exe py.exe) do (
    if not defined PYTHON_EXE (
        where %%L >nul 2>&1
        if not errorlevel 1 (
            %%L -3.12 -c "import sys" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_EXE=%%L"
                set "PYTHON_ARGS=-3.12"
            )
        )
        if not defined PYTHON_EXE (
            %%L -3.11 -c "import sys" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_EXE=%%L"
                set "PYTHON_ARGS=-3.11"
            )
        )
        if not defined PYTHON_EXE (
            %%L -3.10 -c "import sys" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_EXE=%%L"
                set "PYTHON_ARGS=-3.10"
            )
        )
    )
)
if not defined PYTHON_EXE (
    where python.exe >nul 2>&1
    if not errorlevel 1 (
        python.exe -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 12), (3, 11), (3, 10)) else 1)" >nul 2>&1
        if not errorlevel 1 set "PYTHON_EXE=python.exe"
    )
)

if defined PYTHON_EXE (
    start "" /b "%PYTHON_EXE%" %PYTHON_ARGS% -m beeref %*
    exit /b 0
)

echo BeeRef could not find a supported Python 3.10, 3.11, or 3.12 installation. 1>&2
echo Install Python 3.12 from python.org and try again. 1>&2
exit /b 1
