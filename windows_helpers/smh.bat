:: Drag a .smh file containing command line arguments onto this file
@echo off
for /F "tokens=* usebackq" %%i in (%1) do (call :execute_line %%i || exit /b)
goto :eof

:execute_line
	set line=%*
	if "%line:~0,1%" == "#" exit /b 0 :: skip comments
	echo Executing %line%
	python -m synth_mapping_helper.cli %line% || (
		echo.
		echo A script error occured executing %line%
		echo Aborting...
		echo.
		pause
		exit /b 1
	)
	exit /b 0
