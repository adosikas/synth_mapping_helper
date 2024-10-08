:: To open, drag a .synth file onto this file
@echo off
:: Run "python3 -m synth_mapping_helper.companion -h" to get a list of options to change various defaults (eg. velocity and acceleration scale)

:: '%0\..' is the directory this file is in, even when called via a shortcut
:: So the 'output.synth' and 'smh_backup' directory will be created beside this file, whereever you put it
python -m synth_mapping_helper.companion %1 --output-file %0\..\output.synth --backup-dir %0\..\smh_backup || (
	echo.
	echo A script error occured
	echo Aborting...
	echo.
	pause
	exit /b 1
)
exit /b 0
