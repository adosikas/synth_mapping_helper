echo "You can combine any of the options and write them to a .txt file."
echo "Dragging that text file onto smh.bat will execute each line one after the other."
echo
echo "Note: When the *value* of an option starts with a '-' (ie because the number is negative)"
echo "      You must have a '=' between option and value, ie '--rotate=-45' instead of '--rotate -45'"
echo

python3 -m synth_mapping_helper.cli --help
pause