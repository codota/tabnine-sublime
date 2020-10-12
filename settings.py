import json
import os

_install_directory = os.path.dirname(__file__)
_settings_dir = os.path.abspath(os.path.join(_install_directory, os.pardir, "User", "TabNine.sublime-settings"))

_SETTINGS = None
def get_settings_eager():
	global _SETTINGS
	if _SETTINGS is None:
		try:
			with open(_settings_dir) as json_file:
				_SETTINGS = json.load(json_file)
				return _SETTINGS
		except:
			_SETTINGS = {}
			return _SETTINGS
	else: 
		return _SETTINGS