import json
import os

_install_directory = os.path.dirname(__file__)
_settings_dir = os.path.abspath(
    os.path.join(
        _install_directory, os.pardir, os.pardir, "User", "TabNine.sublime-settings"
    )
)
_package_dir = os.path.abspath(
    os.path.join(_install_directory, os.pardir, os.pardir, "TabNine", "package.json")
)

_SETTINGS = None
_DEVELOPMENT = None
_IS_NATIVE_AUTO_IMPORT = None
_VERSION = None


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
                data = remove_trailing_comma(json_file)
                _SETTINGS = json.loads(data)
        except:  # noqa E722
            _SETTINGS = {}


def get_version():
    global _VERSION
    if _VERSION is None:
        try:
            with open(_package_dir) as json_file:
                _VERSION = json.load(json_file)["version"]
        except Exception as e:  # noqa E722
            _VERSION = None
    return _VERSION


def remove_trailing_comma(json_file):
    data = json_file.read().replace(",\n}", "\n}")
    return data


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
