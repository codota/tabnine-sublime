import sublime
import sublime_plugin
import html
import subprocess
import json
import os

CHAR_LIMIT = 2000
MAX_RESTARTS = 10

class TabNineCommand(sublime_plugin.TextCommand):
    def run(*args, **kwargs):
        print("TabNine commands are supposed to be intercepted by TabNineListener")
        pass

class TabNineLeaderKeyCommand(TabNineCommand):
    pass

class TabNineSubstituteCommand(sublime_plugin.TextCommand):
    def run(self, edit, *, region_begin, region_end, substitution, prefix):
        region_end += len(prefix)
        region = sublime.Region(region_begin, region_end)
        self.view.erase(edit, region)
        self.view.insert(edit, region_begin, substitution)

class TabNineListener(sublime_plugin.EventListener):
    def __init__(self):
        self.before = ""
        self.after = ""
        self.region_includes_beginning = False
        self.region_includes_end = False
        self.before_begin_location = 0
        self.autocompleting = False
        self.choices = []
        self.substitute_interval = 0, 0
        self.actions_since_completion = 1
        self.install_directory = os.path.dirname(os.path.realpath(__file__))
        self.tabnine_proc = None
        self.settings = sublime.load_settings("TabNine.sublime-settings")
        self.num_restarts = 0
        self.restart_tabnine_proc()

    def restart_tabnine_proc(self):
        if self.tabnine_proc is not None:
            try:
                self.tabnine_proc.terminate()
            except Exception:
                pass
        binary_dir = os.path.join(self.install_directory, "binaries")
        tabnine_path = self.settings.get("custom_binary_path")
        if tabnine_path is None:
            tabnine_path = get_tabnine_path(binary_dir)
        args = [tabnine_path, "--client", "sublime"]
        log_file_path = self.settings.get("log_file_path")
        if log_file_path is not None:
            args += ["--log-file-path", log_file_path]
        extra_args = self.settings.get("extra_args")
        if extra_args is not None:
            args += extra_args
        self.tabnine_proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            startupinfo=get_startup_info(sublime.platform()))

    def request(self, req):
        if self.tabnine_proc.poll():
            print("TabNine subprocess is dead")
            if self.num_restarts < MAX_RESTARTS:
                print("Restarting it...")
                self.num_restarts += 1
                self.restart_tabnine_proc()
            else:
                return None
        req = {
            "version": "0.4.0",
            "request": req
        }
        req = json.dumps(req)
        req += '\n'
        try:
            self.tabnine_proc.stdin.write(bytes(req, "UTF-8"))
            self.tabnine_proc.stdin.flush()
            result = self.tabnine_proc.stdout.readline()
            result = str(result, "UTF-8")
            return json.loads(result)
        except (IOError, OSError, UnicodeDecodeError, ValueError) as e:
            print("Exception while interacting with TabNine subprocess:", e) 
            if self.num_restarts < MAX_RESTARTS:
                self.num_restarts += 1
                self.restart_tabnine_proc()

    def get_before(self, view):
        loc = view.sel()[0].begin()
        begin = max(0, loc - CHAR_LIMIT)
        return view.substr(sublime.Region(begin, loc)), begin == 0, loc
    def get_after(self, view):
        loc = view.sel()[0].end()
        end = min(view.size(), loc + CHAR_LIMIT)
        return view.substr(sublime.Region(loc, end)), end == view.size()

    def on_selection_modified(self, view):
        self.on_any_event(view)
    def on_activated(self, view):
        self.on_any_event(view)

    def on_activated_async(self, view):
        file_name = view.file_name()
        if file_name is not None:
            request = {
                "Prefetch": {
                    "filename": file_name
                }
            }
            self.request(request)

    def on_any_event(self, view):
        (new_before,
            self.region_includes_beginning,
            self.before_begin_location) = self.get_before(view)
        new_after, self.region_includes_end = self.get_after(view)
        self.autocompleting = self.should_autocomplete(
            view,
            old_before=self.before,
            old_after=self.after,
            new_before=new_before,
            new_after=new_after)
        self.before = new_before
        self.after = new_after
        self.actions_since_completion += 1
        if self.autocompleting:
            pass # on_selection_modified_async will show the popup
        else:
            view.hide_popup()
            if self.actions_since_completion >= 2:
                self.choices = []

    def should_autocomplete(self, view, *, old_before, old_after, new_before, new_after):
        return (self.actions_since_completion >= 1
            and view.sel()[0].begin() == view.sel()[0].end()
            and new_before != ""
            and len(view.sel()) == 1
            and (new_after[:100] != old_after[1:101] or new_after == "")
            and old_before[-100:] == new_before[-101:-1])

    def max_num_results(self):
        return self.settings.get("max_num_results")

    def on_selection_modified_async(self, view):
        if not self.autocompleting:
            return
        request = {
            "Autocomplete": {
                "before": self.before,
                "after": self.after,
                "filename": view.file_name(),
                "region_includes_beginning": self.region_includes_beginning,
                "region_includes_end": self.region_includes_end,
                "max_num_results": self.max_num_results()
            }
        }
        response = self.request(request)
        if response is None or not self.autocompleting:
            return
        self.tab_index = 0
        self.suffix_to_substitute = response["suffix_to_substitute"]
        self.choices = response["results"]
        self.choices = self.choices[:9]
        substitute_begin = self.before_begin_location - len(self.suffix_to_substitute)
        self.substitute_interval = (substitute_begin, self.before_begin_location)
        to_show = [choice["result"] for choice in self.choices]
        max_len = max([len(x) for x in to_show] or [0])
        for i in range(len(to_show)):
            padding = max_len - len(to_show[i]) + 2
            if i == 0:
                annotation = "&nbsp;" * 2 + "Tab"
            else:
                annotation = "Tab+" + str(i + 1)
            annotation = "<i>" + annotation + "</i>"
            with_padding = escape(to_show[i] + " " * padding)
            to_show[i] = with_padding + annotation
        active = "is_active" in response and response["is_active"]
        if "promotional_message" in response:
            print(response["promotional_message"])
            for line in response["promotional_message"]:
                to_show.append("""<span style="font-size: 10;">""" + escape(line) + "</span>")
        elif not active and not self.settings.get("hide_promotional_message"):
            to_show.append("""<span style="font-size: 10;">Upgrade to get additional features at <a href="https://tabnine.com">tabnine.com</a></span>""")
        to_show = "<br>".join(to_show)
        if self.choices == []:
            view.hide_popup()
        else:
            view.show_popup(
                to_show,
                sublime.COOPERATE_WITH_AUTO_COMPLETE,
                location=substitute_begin,
                max_width=1000,
                max_height=1000)

    def insert_completion(self, choice_index):
        self.tab_index = (choice_index + 1) % len(self.choices)
        a, b = self.substitute_interval
        choice = self.choices[choice_index]
        substitution = choice["result"]
        prefix = choice["prefix_to_substitute"]
        self.actions_since_completion = 0
        self.substitute_interval = a, a+len(substitution)
        if len(self.choices) == 1:
            self.choices = []
        new_args = {
            "region_begin": a,
            "region_end": b,
            "substitution": substitution,
            "prefix": prefix,
        }
        return "tab_nine_substitute", new_args

    def on_text_command(self, view, command_name, args):
        if command_name == "tab_nine" and "num" in args:
            num = args["num"]
            choice_index = num - 1
            if choice_index < 0 or choice_index >= len(self.choices):
                return None
            result = self.insert_completion(choice_index)
            self.choices = []
            return result
        if command_name in ["insert_best_completion", "tab_nine_leader_key"] and len(self.choices) >= 1:
            return self.insert_completion(self.tab_index)

    def on_query_context(self, view, key, operator, operand, match_all):
        if key == "tab_nine_choice_available":
            assert operator == sublime.OP_EQUAL
            return (not view.is_popup_visible()) and operand - 1 < len(self.choices)
        if key == "tab_nine_leader_key_available":
            assert operator == sublime.OP_EQUAL
            return (self.choices != [] and view.is_popup_visible()) == operand

def get_startup_info(platform):
    if platform == "windows":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    else:
        return None

def escape(s):
    s = html.escape(s, quote=False)
    s = s.replace(" ", "&nbsp;")
    return s

def parse_semver(s):
    try:
        return [int(x) for x in s.split('.')]
    except ValueError:
        return []

assert parse_semver("0.01.10") == [0, 1, 10]
assert parse_semver("hello") == []
assert parse_semver("hello") < parse_semver("0.9.0") < parse_semver("1.0.0")

def get_tabnine_path(binary_dir):
    def join_path(*args):
        return os.path.join(binary_dir, *args)
    translation = {
        ("linux",   "x32"): "i686-unknown-linux-gnu/TabNine",
        ("linux",   "x64"): "x86_64-unknown-linux-gnu/TabNine",
        ("osx",     "x32"): "i686-apple-darwin/TabNine",
        ("osx",     "x64"): "x86_64-apple-darwin/TabNine",
        ("windows", "x32"): "i686-pc-windows-gnu/TabNine.exe",
        ("windows", "x64"): "x86_64-pc-windows-gnu/TabNine.exe",
    }
    versions = os.listdir(binary_dir)
    versions.sort(key=parse_semver, reverse=True)
    for version in versions:
        key = sublime.platform(), sublime.arch()
        path = join_path(version, translation[key])
        if os.path.isfile(path) and os.access(path, os.X_OK):
            print("TabNine: starting version", version)
            return path
