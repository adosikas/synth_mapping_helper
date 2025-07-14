# https://github.com/pyinstaller/pyinstaller-hooks-contrib/commit/c61421f026ef9f339c3d0f73cb655a6d8dc67b80
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = collect_data_files('plotly', includes=['package_data/**/*.*', 'validators/**/*.*'])
hiddenimports = collect_submodules('plotly.validators') + ['pandas', 'cmath']