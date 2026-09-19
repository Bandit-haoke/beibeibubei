@echo off
chcp 65001 >nul
title 背备不悲 · 启动器
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0一键启动.ps1"
pause
