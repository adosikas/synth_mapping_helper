:: Drag a .txt file containing command line arguments onto this file
@echo off
for /F "tokens=*" %%i in (%1) do (
	echo %%i
	python3 -m synth_mapping_helper.cli %%i
	:: pause so error is visible
	if NOT ["%errorlevel%"]==["0"] pause
)
