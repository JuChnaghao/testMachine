@echo off
setlocal enabledelayedexpansion
pushd %~dp0

:: 错误日志文件
set "errorLog=error_log.txt"

:: 清空日志（如不希望清空请注释下一行）
if exist %errorLog% del %errorLog%

:: 循环轮数
set loopCount=100
:: 超时时间（秒）和目标 .exe 名称
set "timeoutSeconds=120"
set "exeName=datainput_student_win64.exe"

for /l %%i in (1, 1, %loopCount%) do (
    echo -------------------------
    echo [Round %%i] Start...

    rem 1. 运行第一个 Python 脚本（生成 stdin.txt）
    python generator7.py > temp_generator.txt 2>&1
    if errorlevel 1 (
         echo [Round %%i] generator error! >> %errorLog%
         type temp_generator.txt >> %errorLog%
         call :recordError "Generator Error" %%i
         goto :exit_loop
    )

    rem 2. 执行管道命令：.\datainput_student_win64.exe | java -jar hw7.jar > stdout.txt 2>&1
    echo [Round %%i] Running pipeline command...
    start "" /B cmd /c ".\%exeName% | java -jar hw7.jar > stdout.txt 2>&1"

    rem 等待指定超时时间
    timeout /t %timeoutSeconds% >nul

    rem 检查 datainput_student_win64.exe 是否还在运行
    tasklist /FI "IMAGENAME eq %exeName%" | find /I "%exeName%" >nul
    if !ERRORLEVEL! == 0 (
         echo [Round %%i] Timeout: %exeName% still running, terminating... >> %errorLog%
         taskkill /IM %exeName% /F >nul
         call :recordError "Pipeline Timeout" %%i
         goto :exit_loop
    )

    rem 4. 运行第四个 Python 脚本（比对 stdout.txt）
    python checker7.py > temp_checker.txt 2>&1
    if errorlevel 1 (
         echo [Round %%i] checker error! >> %errorLog%
         type temp_checker.txt >> %errorLog%
         call :recordError "Checker Error" %%i
         goto :exit_loop
    )

    echo [Round %%i] Completed successfully.
    timeout /t 1 >nul
)

:exit_loop
echo -------------------------
echo Task finished.
pause
goto :eof

:recordError
rem %1 错误类型，%2 当前轮次号
set "errorType=%~1"
set "roundNo=%~2"
echo [%date% %time%] [Round %roundNo%] %errorType% occurred. >> %errorLog%
goto :eof
