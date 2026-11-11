@echo off
rem PowerShell shortcut: GNU make is not installed on this host, only
rem mingw32-make. `.\make arm` (or `.\make host-tests`) therefore forwards here.
mingw32-make %*
