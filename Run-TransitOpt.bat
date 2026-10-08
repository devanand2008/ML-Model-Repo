@echo off
setlocal
title TransitOpt AI
call "%~dp0Run-VisionX.bat" %*
exit /b %errorlevel%
