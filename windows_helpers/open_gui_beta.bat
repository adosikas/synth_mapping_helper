@echo off
python3 -m synth_mapping_helper.gui || (
	echo.
	echo A script error occured
	echo Aborting...
	echo.
	pause
	exit /b 1
)
exit /b 0
