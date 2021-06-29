import os
import platform
import sublime
import subprocess
from imp import reload
from json import loads, dumps
import stat
from .settings import get_settings_eager, is_native_auto_complete, get_version

SETTINGS_PATH = "TabNine.sublime-settings"
MAX_RESTARTS = 10


def add_execute_permission(path):
    st = os.stat(path)
    new_mode = st.st_mode | stat.S_IEXEC
    if new_mode != st.st_mode:
        os.chmod(path, new_mode)


def get_startup_info(platform):
    if platform == "windows":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    else:
        return None


def parse_semver(s):
    try:
        return [int(x) for x in s.split(".")]
    except ValueError:
        return []


def get_arch():
    try:
        # handle a case of m1 running under roseeta
        if sublime.platform() == "osx":
            if "ARM64" in platform.version().upper():
                return "arm64"
    except Exception as e:
        print("Error checking if apple m1:", e)
        pass

    return sublime.arch()


def get_tabnine_path(binary_dir):
    def join_path(*args):
        return os.path.join(binary_dir, *args)

    translation = {
        ("linux", "x32"): "i686-unknown-linux-musl/TabNine",
        ("linux", "x64"): "x86_64-unknown-linux-musl/TabNine",
        ("osx", "x32"): "i686-apple-darwin/TabNine",
        ("osx", "x64"): "x86_64-apple-darwin/TabNine",
        ("osx", "arm64"): "aarch64-apple-darwin/TabNine",
        ("windows", "x32"): "i686-pc-windows-gnu/TabNine.exe",
        ("windows", "x64"): "x86_64-pc-windows-gnu/TabNine.exe",
    }

    platform_key = sublime.platform(), get_arch()
    platform = translation[platform_key]

    versions = []

    # if a .active file exists and points to an existing binary than use it
    active_path = join_path(binary_dir, ".active")
    if os.path.exists(active_path):
        version = open(active_path).read().strip()
        version_path = join_path(binary_dir, version)
        active_tabnine_path = join_path(version_path, platform)
        if os.path.exists(active_tabnine_path):
            versions = [version_path]

    # if no .active file then fallback to taking the latest
    if len(versions) == 0:
        versions = os.listdir(binary_dir)
        versions.sort(key=parse_semver, reverse=True)

    for version in versions:
        path = join_path(version, platform)
        if os.path.isfile(path):
            add_execute_permission(path)
            print("Tabnine: starting version", version)
            return path


class TabNineProcess:
    install_directory = os.path.dirname(os.path.realpath(__file__))

    def __init__(self):
        self.tabnine_proc = None
        self.num_restarts = 0

    def run_tabnine(self, inheritStdio=False, additionalArgs=[]):
        binary_dir = os.path.join(TabNineProcess.install_directory, "..", "binaries")
        settings = get_settings_eager()
        tabnine_path = settings.get("custom_binary_path", None)
        if tabnine_path is None:
            tabnine_path = get_tabnine_path(binary_dir)
        args = [tabnine_path, "--client", "sublime"] + additionalArgs
        log_file_path = settings.get("log_file_path", None)
        if log_file_path is not None:
            args += ["--log-file-path", log_file_path]
        extra_args = settings.get("extra_args", None)
        if extra_args is not None:
            args += extra_args
        plugin_version = get_version()
        if not plugin_version:
            plugin_version = "Unknown"
        sublime_version = sublime.version()
        args += [
            "--client-metadata",
            "clientVersion=" + sublime_version,
            "pluginVersion=" + plugin_version,
            "nativeAutoComplete=" + str(is_native_auto_complete()),
            "ide-restart-counter=" + str(self.num_restarts),
        ]
        return subprocess.Popen(
            args,
            stdin=None if inheritStdio else subprocess.PIPE,
            stdout=None if inheritStdio else subprocess.PIPE,
            stderr=subprocess.STDOUT,
            startupinfo=get_startup_info(sublime.platform()),
        )

    def restart_tabnine_proc(self):
        if self.tabnine_proc is not None:
            try:
                self.tabnine_proc.terminate()
            except Exception:  # pylint: disable=W0703
                pass
        self.tabnine_proc = self.run_tabnine()

    def request(self, req):
        if self.tabnine_proc is None:
            self.restart_tabnine_proc()
        if self.tabnine_proc.poll():
            print("Tabnine subprocess is dead")
            if self.num_restarts < MAX_RESTARTS:
                print("Restarting it...")
                self.num_restarts += 1
                self.restart_tabnine_proc()
            else:
                return None
        req = {"version": "2.0.2", "request": req}
        req = dumps(req)
        req += "\n"
        try:
            self.tabnine_proc.stdin.write(bytes(req, "UTF-8"))
            self.tabnine_proc.stdin.flush()
            result = self.tabnine_proc.stdout.readline()
            result = str(result, "UTF-8")
            result = loads(result)
            return result
        except (IOError, OSError, UnicodeDecodeError, ValueError) as e:
            print("Exception while interacting with Tabnine subprocess:", e)
            if self.num_restarts < MAX_RESTARTS:
                self.num_restarts += 1
                self.restart_tabnine_proc()


global tabnine_proc
tabnine_proc = TabNineProcess()
