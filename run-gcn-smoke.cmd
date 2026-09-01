@echo off
rem Double-click entry point for the fast three-seed integration check.
title ReproAgent-Lite - GCN Cora Smoke Run
rem %~dp0 anchors the PowerShell script path to this file's directory.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0case-studies\gcn-cora\run-task.ps1" -Mode smoke
echo.
rem Keep the window open so a double-click user can read the report path/error.
pause
