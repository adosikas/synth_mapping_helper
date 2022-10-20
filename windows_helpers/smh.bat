:: Drag a .txt file containing command line arguments onto this file
@echo off
for /F "tokens=* usebackq" %%i in (%1) do (
	echo Executing %%i
	python3 -m synth_mapping_helper.cli %%i || (
		echo.
		echo An script error occured executing %%i
		echo Aborting...
		echo.
		pause
		exit
	)
)