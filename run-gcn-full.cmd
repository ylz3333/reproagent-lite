@echo off
rem Double-click entry point for the paper-aligned 100-seed reproduction.
title ReproAgent-Lite - GCN Cora 100-Seed Run
rem %~dp0 anchors the PowerShell script path to this file's directory.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0case-studies\gcn-cora\run-task.ps1" -Mode full
echo.
rem Keep the window open so a double-click user can read the report path/error.
pause
