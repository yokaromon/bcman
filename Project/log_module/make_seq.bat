@echo off
setlocal

set "DIR=Y:\Projects\job\int\aoyagi\source\shop\log_module"
set "PLANTUML=c:\tool\plantuml\plantuml.bat"

echo [1/2] logs.db -^> logs.pu
python "%DIR%\make_pu.py"
if %errorlevel% neq 0 exit /b 1

echo [2/2] logs.pu -^> logs.svg
call "%PLANTUML%" "%DIR%\logs.pu"
if %errorlevel% neq 0 exit /b 1

echo 完了: %DIR%\logs.svg
