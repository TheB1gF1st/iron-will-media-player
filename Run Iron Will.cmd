@echo off
cd /d "%~dp0"
rem Uses E:\PythonMedia on the author's PC, otherwise whatever pythonw is on the PATH.
if exist "E:\PythonMedia\pythonw.exe" (
    start "" "E:\PythonMedia\pythonw.exe" IronWill.pyw %*
) else (
    start "" pythonw IronWill.pyw %*
)
