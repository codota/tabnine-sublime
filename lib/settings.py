import json
import os

_install_directory = os.path.dirname(__file__)
_settings_dir = os.path.abspath(
    os.path.join(
        _install_directory, os.pardir, os.pardir, "User", "TabNine.sublime-settings"
    )
)

_SETTINGS = None
_DEVELOPMENT = None
_IS_NATIVE_AUTO_IMPORT = None


def get_settings_eager():
    global _SETTINGS
    if _SETTINGS is None:
        _setup()
    return _SETTINGS


def _setup():
    global _SETTINGS
    if _SETTINGS is None:
        try:
            with open(_settings_dir) as json_file:
                _SETTINGS = json.load(json_file)
        except:  # noqa E722
            _SETTINGS = {}


def is_development():
    global _DEVELOPMENT
    if _DEVELOPMENT is None:
        _setup()
        _DEVELOPMENT = _SETTINGS.get("development_mode", False)

    return _DEVELOPMENT


def is_native_auto_complete():
    global _IS_NATIVE_AUTO_IMPORT
    if _IS_NATIVE_AUTO_IMPORT is None:
        _setup()
        _IS_NATIVE_AUTO_IMPORT = _SETTINGS.get("native_auto_complete", False)

    return _IS_NATIVE_AUTO_IMPORT


def is_tabnine_disabled(view):
    return view.settings().get("tabnine-disabled", False)
