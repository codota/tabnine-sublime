import sublime
import sublime_plugin
import html
import os
import stat
import webbrowser
import time
import json
import subprocess

SETTINGS_PATH = 'TabNine.sublime-settings'
MAX_RESTARTS = 10
AUTOCOMPLETE_CHAR_LIMIT = 100000
PREFERENCES_PATH = 'Preferences.sublime-settings'
GLOBAL_HIGHLIGHT_COUNTER = 0

GLOBAL_IGNORE_EVENTS = False


def get_startup_info(platform):
    if platform == "windows":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    else:
        return None


def get_tabnine_path(binary_dir):
    def join_path(*args):
        return os.path.join(binary_dir, *args)
    translation = {
        ("linux", "x32"): "i686-unknown-linux-musl/TabNine",
        ("linux", "x64"): "x86_64-unknown-linux-musl/TabNine",
        ("osx", "x32"): "i686-apple-darwin/TabNine",
        ("osx", "x64"): "x86_64-apple-darwin/TabNine",
        ("windows", "x32"): "i686-pc-windows-gnu/TabNine.exe",
        ("windows", "x64"): "x86_64-pc-windows-gnu/TabNine.exe",
    }
    versions = os.listdir(binary_dir)
    versions.sort(key=parse_semver, reverse=True)
    for version in versions:
        key = sublime.platform(), sublime.arch()
        path = join_path(version, translation[key])
        if os.path.isfile(path):
            add_execute_permission(path)
            print("TabNine: starting version", version)
            return path


class TabNineProcess:
    def __init__(self):
        self.tabnine_proc = None
        self.num_restarts = 0
        self.install_directory = os.path.dirname(os.path.realpath(__file__))

        def on_change():
            self.num_restarts = 0
            self.restart_tabnine_proc()
        sublime.load_settings(SETTINGS_PATH).add_on_change('TabNine', on_change)

    def restart_tabnine_proc(self):
        if self.tabnine_proc is not None:
            try:
                self.tabnine_proc.terminate()
            except Exception: #pylint: disable=W0703
                pass
        binary_dir = os.path.join(self.install_directory, "binaries")
        settings = sublime.load_settings(SETTINGS_PATH)
        tabnine_path = settings.get("custom_binary_path")
        if tabnine_path is None:
            tabnine_path = get_tabnine_path(binary_dir)
        args = [tabnine_path, "--client", "sublime"]
        log_file_path = settings.get("log_file_path")
        if log_file_path is not None:
            args += ["--log-file-path", log_file_path]
        extra_args = settings.get("extra_args")
        if extra_args is not None:
            args += extra_args
        self.tabnine_proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            startupinfo=get_startup_info(sublime.platform()))

    def request(self, req):
        if self.tabnine_proc is None:
            self.restart_tabnine_proc()
        if self.tabnine_proc.poll():
            print("TabNine subprocess is dead")
            if self.num_restarts < MAX_RESTARTS:
                print("Restarting it...")
                self.num_restarts += 1
                self.restart_tabnine_proc()
            else:
                return None
        req = {
            "version": "2.0.0",
            "request": req
        }
        req = json.dumps(req)
        req += '\n'
        try:
            self.tabnine_proc.stdin.write(bytes(req, "UTF-8"))
            self.tabnine_proc.stdin.flush()
            result = self.tabnine_proc.stdout.readline()
            result = str(result, "UTF-8")
            result = json.loads(result)
            return result
        except (IOError, OSError, UnicodeDecodeError, ValueError) as e:
            print("Exception while interacting with TabNine subprocess:", e)
            if self.num_restarts < MAX_RESTARTS:
                self.num_restarts += 1
                self.restart_tabnine_proc()


class TabNineCommand(sublime_plugin.TextCommand):
    def run(*args, **kwargs): #pylint: disable=W0613,E0211
        print("TabNine commands are supposed to be intercepted by TabNineListener")

class TabNineLeaderKeyCommand(TabNineCommand):
    pass
class TabNineReverseLeaderKeyCommand(TabNineCommand):
    pass

class TabNineSubstituteCommand(sublime_plugin.TextCommand):
    def run(
        self, edit, *,
        region_begin, region_end, substitution, new_cursor_pos,
        prefix, old_prefix, expected_prefix, highlight
    ):
        normalize_offset = -self.view.sel()[0].begin()
        def normalize(x, sel):
            if isinstance(x, sublime.Region):
                return sublime.Region(normalize(x.begin(), sel), normalize(x.end(), sel))
            else:
                return normalize_offset + x + sel.begin() 
        observed_prefixes = [
            self.view.substr(sublime.Region(normalize(region_begin, sel), sel.begin()))
            for sel in self.view.sel()
        ]
        if old_prefix is not None:
            for i in range(len(self.view.sel())):
                sel = self.view.sel()[i]
                t_region_end = normalize(region_end, sel)
                self.view.sel().subtract(sel)
                self.view.insert(edit, t_region_end, old_prefix)
                self.view.sel().add(t_region_end)
        normalize_offset = -self.view.sel()[0].begin()
        region_end += len(prefix)
        region = sublime.Region(region_begin, region_end)
        modified_regions = []
        for i in range(len(self.view.sel())):
            sel = self.view.sel()[i]
            t_region = normalize(region, sel)
            observed_prefix = observed_prefixes[i]
            if observed_prefix != expected_prefix:
                new_begin = self.view.word(sel).begin()
                print(
                    'TabNine expected prefix "{}" but found prefix "{}", falling back to substituting from word beginning: "{}"'
                        .format(expected_prefix, observed_prefix, self.view.substr(sublime.Region(new_begin, sel.begin())))
                )
                t_region = sublime.Region(new_begin, t_region.end())
            self.view.sel().subtract(sel)
            self.view.erase(edit, t_region)
            self.view.insert(edit, t_region.begin(), substitution)
            self.view.sel().add(t_region.begin() + new_cursor_pos)
            modified_regions.append(sublime.Region(t_region.begin(), t_region.begin() + new_cursor_pos))
        if highlight:
            global GLOBAL_HIGHLIGHT_COUNTER
            GLOBAL_HIGHLIGHT_COUNTER += 1
            expected_counter = GLOBAL_HIGHLIGHT_COUNTER
            self.view.add_regions(
                'tabnine_highlight', modified_regions, 'string',
                flags=sublime.DRAW_NO_OUTLINE,
            )
            def erase():
                if GLOBAL_HIGHLIGHT_COUNTER == expected_counter:
                    self.view.erase_regions('tabnine_highlight')
            sublime.set_timeout(erase, 250)


tabnine_proc = TabNineProcess()

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
        self.old_prefix = None
        self.popup_is_ours = False
        self.seen_changes = False
        self.no_hide_until = time.time()
        self.just_pressed_tab = False
        self.tab_only = False

        self.tab_index = 0
        self.old_prefix = None
        self.expected_prefix = ""
        self.user_message = []

        sublime.load_settings(PREFERENCES_PATH).set('auto_complete', False)
        sublime.save_settings(PREFERENCES_PATH)

    def get_before(self, view, char_limit):
        loc = view.sel()[0].begin()
        begin = max(0, loc - char_limit)
        return view.substr(sublime.Region(begin, loc)), begin == 0, loc
    def get_after(self, view, char_limit):
        loc = view.sel()[0].end()
        end = min(view.size(), loc + char_limit)
        return view.substr(sublime.Region(loc, end)), end == view.size()

    def on_modified(self, view):
        self.seen_changes = True
        self.on_any_event(view)
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
            tabnine_proc.request(request)

    def on_any_event(self, view):
        if view.window() is None:
            return
        view = view.window().active_view()
        if view.is_scratch() or GLOBAL_IGNORE_EVENTS:
            return
        (
            new_before,
            self.region_includes_beginning,
            self.before_begin_location,
        ) = self.get_before(view, AUTOCOMPLETE_CHAR_LIMIT)
        new_after, self.region_includes_end = self.get_after(view, AUTOCOMPLETE_CHAR_LIMIT)
        if new_before == self.before and new_after == self.after:
            return
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
            if self.popup_is_ours and time.time() > self.no_hide_until:
                view.hide_popup()
                self.popup_is_ours = False
                self.just_pressed_tab = False
            if not self.popup_is_ours:
                self.just_pressed_tab = False
            if self.actions_since_completion >= 2:
                self.choices = []

    def should_autocomplete(self, view, *, old_before, old_after, new_before, new_after):
        return (self.actions_since_completion >= 1
            and len(view.sel()) <= 100
            and all(sel.begin() == sel.end() for sel in view.sel())
            and self.all_same_prefix(view, [sel.begin() for sel in view.sel()])
            and self.all_same_suffix(view, [sel.begin() for sel in view.sel()])
            and new_before != ""
            and (new_after[:100] != old_after[1:101] or new_after == "" or (len(view.sel()) >= 2 and self.seen_changes))
            and old_before[-100:] == new_before[-101:-1])

    def all_same_prefix(self, view, positions):
        return self.all_same(view, positions, -1, -1)
    def all_same_suffix(self, view, positions):
        return self.all_same(view, positions, 0, 1)

    def all_same(self, view, positions, start, step):
        if len(positions) <= 1:
            return True
        # We should ask TabNine for the identifier regex but this is simpler for now
        def alnum_char_at(i):
            if i >= 0:
                s = view.substr(sublime.Region(i, i+1))
                if s.isalnum() or s == '_':
                    return s
            return None
        offset = start
        while True:
            next_chars = {alnum_char_at(pos + offset) for pos in positions}
            if len(next_chars) != 1:
                return False
            if next(iter(next_chars)) is None:
                return True
            if offset <= -30:
                return True
            offset += step

    def get_settings(self):
        return sublime.load_settings(SETTINGS_PATH)

    def max_num_results(self):
        return self.get_settings().get("max_num_results")

    def on_selection_modified_async(self, view):
        if view.window() is None:
            return
        view = view.window().active_view()
        if not self.autocompleting:
            return
        self.just_pressed_tab = False
        max_num_results = self.max_num_results()
        request = {
            "Autocomplete": {
                "before": self.before,
                "after": self.after,
                "filename": view.file_name(),
                "region_includes_beginning": self.region_includes_beginning,
                "region_includes_end": self.region_includes_end,
                "max_num_results": max_num_results,
            }
        }
        response = tabnine_proc.request(request)
        if response is None or not self.autocompleting:
            return
        self.tab_index = 0
        self.old_prefix = None
        self.expected_prefix = response["old_prefix"]
        self.choices = response["results"]
        max_choices = 9
        if max_num_results is not None:
            max_choices = min(max_choices, max_num_results)
        self.choices = self.choices[:max_choices]
        substitute_begin = self.before_begin_location - len(self.expected_prefix)
        self.substitute_interval = (substitute_begin, self.before_begin_location)
        self.user_message = response["user_message"]
        self.tab_only = False
        to_show = self.make_popup_content(None)

        if self.choices == []:
            view.hide_popup()
        else:
            my_show_popup(view, to_show, substitute_begin)
            self.popup_is_ours = True
            self.seen_changes = False

    def make_popup_content(self, index):
        to_show = [choice["new_prefix"] for choice in self.choices]
        max_len = max([len(x) for x in to_show] or [0])
        show_detail = self.get_settings().get("detail")
        for i in range(len(to_show)):
            padding = max_len - len(to_show[i]) + 2
            if index is None:
                if i == 0:
                    annotation = "&nbsp;" * 4 + "Tab"
                elif i == 1:
                    annotation = "Tab+Tab"
                elif i < 9:
                    annotation = "&nbsp;" * 2 + "Tab+" + str(i + 1)
                else:
                    annotation = ""
            else:
                if i == index:
                    annotation = "&nbsp;" * 3
                elif i == (index + 1) % len(self.choices):
                    annotation = "Tab"
                elif self.tab_only:
                    annotation = "&nbsp;" * 3
                else:
                    annotation = "&nbsp;" * 2 + str(i + 1)
                annotation = "&nbsp;" * 4 + annotation
            annotation = "<i>" + annotation + "</i>"
            choice = self.choices[i]
            if show_detail and 'detail' in choice and isinstance(choice['detail'], str):
                annotation += escape("  " + choice['detail'].replace('\n', ' '))
            with_padding = escape(to_show[i] + " " * padding)
            to_show[i] = with_padding + annotation
        for line in self.user_message:
            to_show.append("""<span style="font-size: 10;">""" + escape(line) + "</span>")
        to_show = "<br>".join(to_show)
        return to_show

    def insert_completion(self, view, choice_index, popup): #pylint: disable=W0613
        self.tab_index = (choice_index + 1) % len(self.choices)
        if choice_index != 0:
            self.tab_only = True
        a, b = self.substitute_interval
        choice = self.choices[choice_index]
        new_prefix = choice["new_prefix"]
        prefix = choice["old_suffix"] # The naming here is very bad
        new_suffix = choice["new_suffix"]
        substitution = new_prefix + new_suffix
        self.substitute_interval = a, (a + len(substitution))
        self.actions_since_completion = 0
        if len(self.choices) == 1:
            self.choices = []
        if self.get_settings().get("documentation"):
            documentation = get_additional_detail(choice)
        else:
            documentation = None
        new_args = {
            "region_begin": a,
            "region_end": b,
            "substitution": substitution,
            "new_cursor_pos": len(new_prefix),
            "prefix": prefix,
            "old_prefix": self.old_prefix,
            "expected_prefix": self.expected_prefix,
            "highlight": self.get_settings().get("highlight"),
        }
        self.expected_prefix = new_prefix
        self.old_prefix = prefix
        if popup:
            popup_content = [self.make_popup_content(choice_index)]
        else:
            popup_content = []
        if documentation is not None:
            popup_content.append(format_documentation(documentation))
        if popup_content == []:
            view.hide_popup()
            self.popup_is_ours = False
        else:
            my_show_popup(view, '<br> <br>'.join(popup_content), a)
            self.no_hide_until = time.time() + 0.01
            self.popup_is_ours = True
        return "tab_nine_substitute", new_args

    def on_text_command(self, view, command_name, args):
        if command_name == "tab_nine" and "num" in args:
            num = args["num"]
            choice_index = num - 1
            if choice_index < 0 or choice_index >= len(self.choices):
                return None
            result = self.insert_completion(view, choice_index, popup=False)
            self.choices = []
            return result
        if command_name in ["insert_best_completion", "tab_nine_leader_key"] and len(self.choices) >= 1:
            self.just_pressed_tab = True
            return self.insert_completion(view, self.tab_index, popup=True)
        if command_name == "tab_nine_reverse_leader_key" and len(self.choices) >= 1:
            self.just_pressed_tab = True
            index = (self.tab_index - 2 + len(self.choices)) % len(self.choices)
            return self.insert_completion(view, index, popup=True)

    def on_query_context(self, view, key, operator, operand, match_all): #pylint: disable=W0613
        if key == "tab_nine_choice_available":
            assert operator == sublime.OP_EQUAL
            return self.just_pressed_tab and operand <= len(self.choices) and not self.tab_only and operand != 1
        if key == "tab_nine_leader_key_available":
            assert operator == sublime.OP_EQUAL
            return (self.choices != [] and view.is_popup_visible()) == operand
        if key == "tab_nine_reverse_leader_key_available":
            assert operator == sublime.OP_EQUAL
            return (self.choices != []) == operand

def escape(s):
    s = html.escape(s, quote=False)
    s = s.replace(" ", "&nbsp;")
    urls = [
        ('https://tabnine.com/semantic', None, 'tabnine.com/semantic'),
        ('tabnine.com/semantic', 'https://tabnine.com/semantic', 'tabnine.com/semantic'),
        ('tabnine.com', 'https://tabnine.com', 'tabnine.com'),
    ]
    for url, navigate_to, display in urls:
        if url in s:
            if navigate_to is None:
                navigate_to = url
            s = s.replace(html.escape(url), '<a href="{}">{}</a>'.format(url, display))
            break
    return s

def get_additional_detail(choice):
    s = None
    if 'documentation' in choice:
        s = choice['documentation']
    return s

def format_documentation(documentation):
    if isinstance(documentation, str):
        return escape(documentation)
    elif isinstance(documentation, dict) and 'kind' in documentation and documentation['kind'] == 'markdown' and 'value' in documentation:
        return escape(documentation['value'])
    else:
        return escape(str(documentation))

def parse_semver(s):
    try:
        return [int(x) for x in s.split('.')]
    except ValueError:
        return []

assert parse_semver("0.01.10") == [0, 1, 10]
assert parse_semver("hello") == []
assert parse_semver("hello") < parse_semver("0.9.0") < parse_semver("1.0.0")

def my_show_popup(view, content, location, markdown=None):
    global GLOBAL_IGNORE_EVENTS
    GLOBAL_IGNORE_EVENTS = True
    if markdown is None:
        view.show_popup(
            content,
            sublime.COOPERATE_WITH_AUTO_COMPLETE,
            location=location,
            max_width=1500,
            max_height=1200,
            on_navigate=webbrowser.open,
        )
    else:
        content = escape(content)
        view.show_popup(
            content,
            sublime.COOPERATE_WITH_AUTO_COMPLETE,
            location=location,
            max_width=1500,
            max_height=1200,
            on_navigate=webbrowser.open,
        )
    GLOBAL_IGNORE_EVENTS = False

def add_execute_permission(path):
    st = os.stat(path)
    new_mode = st.st_mode | stat.S_IEXEC
    if new_mode != st.st_mode:
        os.chmod(path, new_mode)


class OpenconfigCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        request = {
            "Configuration": {
            }
        }

        response = tabnine_proc.request(request)
