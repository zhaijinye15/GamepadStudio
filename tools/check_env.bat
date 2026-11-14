@echo off
chcp 65001 >nul
setlocal
echo ==========================================
echo  Gamepad Studio 运行组件自检
echo ==========================================
echo.
"%~dp0..\runtime\python.exe" "%~dp0bootstrap.py"
set RESULT=%ERRORLEVEL%
echo.
if "%RESULT%"=="0" (
  echo 全部组件正常。
) else (
  echo 有组件缺失，已尝试自动补装；若仍失败请检查网络或重新安装程序。
)
echo.
pause
endlocal
