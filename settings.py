import json
import os

install_directory = os.path.dirname(__file__)
settings_dir = os.path.abspath(os.path.join(install_directory, os.pardir, "User", "TabNine.sublime-settings"))

raw_settings = None
def get_settings_eager():
	global raw_settings
	if raw_settings is None:
		try:
			with open(settings_dir) as json_file:
				raw_settings = json.load(json_file)
				return raw_settings
		except:
			raw_settings = {}
			return raw_settings
	else: 
		return raw_settings