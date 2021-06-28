import sublime
import sublime_plugin
import html
import os
import stat
import webbrowser
import time
import subprocess
from package_control import package_manager
from threading import Timer
from ..lib.requests import uninstalling, open_config, prefetch, autocomplete

SETTINGS_PATH = "TabNine.sublime-settings"
MAX_RESTARTS = 10
AUTOCOMPLETE_CHAR_LIMIT = 100000
PREFERENCES_PATH = "Preferences.sublime-settings"
GLOBAL_HIGHLIGHT_COUNTER = 0


def plugin_loaded():
    sublime.load_settings(PREFERENCES_PATH).set("auto_complete", False)
    sublime.save_settings(PREFERENCES_PATH)


GLOBAL_IGNORE_EVENTS = False

PACK_MANAGER = package_manager.PackageManager()


class TabNineCommand(sublime_plugin.TextCommand):
    def run(*args, **kwargs):  # pylint: disable=W0613,E0211
        print("Tabnine commands are supposed to be intercepted by TabNineListener")


class TabNineLeaderKeyCommand(TabNineCommand):
    pass


class TabNineReverseLeaderKeyCommand(TabNineCommand):
    pass


class TabNineSubstituteCommand(sublime_plugin.TextCommand):
    def run(
        self,
        edit,
        *,
        region_begin,
        region_end,
        substitution,
        new_cursor_pos,
        prefix,
        old_prefix,
        expected_prefix,
        highlight
    ):
        normalize_offset = -self.view.sel()[0].begin()

        def normalize(x, sel):
            if isinstance(x, sublime.Region):
                return sublime.Region(
                    normalize(x.begin(), sel), normalize(x.end(), sel)
                )
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
                    'Tabnine expected prefix "{}" but found prefix "{}", falling back to substituting from word beginning: "{}"'.format(
                        expected_prefix,
                        observed_prefix,
                        self.view.substr(sublime.Region(new_begin, sel.begin())),
                    )
                )
                t_region = sublime.Region(new_begin, t_region.end())
            self.view.sel().subtract(sel)
            self.view.erase(edit, t_region)
            self.view.insert(edit, t_region.begin(), substitution)
            self.view.sel().add(t_region.begin() + new_cursor_pos)
            modified_regions.append(
                sublime.Region(t_region.begin(), t_region.begin() + new_cursor_pos)
            )
        if highlight:
            global GLOBAL_HIGHLIGHT_COUNTER
            GLOBAL_HIGHLIGHT_COUNTER += 1
            expected_counter = GLOBAL_HIGHLIGHT_COUNTER
            self.view.add_regions(
                "tabnine_highlight",
                modified_regions,
                "string",
                flags=sublime.DRAW_NO_OUTLINE,
            )

            def erase():
                if GLOBAL_HIGHLIGHT_COUNTER == expected_counter:
                    self.view.erase_regions("tabnine_highlight")

            sublime.set_timeout(erase, 250)


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
        self.timer = None
        self.tab_index = 0
        self.old_prefix = None
        self.expected_prefix = ""
        self.user_message = []

        def update_settings():
            sublime.load_settings(PREFERENCES_PATH).set("auto_complete", False)
            sublime.save_settings(PREFERENCES_PATH)

        sublime.set_timeout(update_settings, 250)

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
            prefetch(file_name)

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
        new_after, self.region_includes_end = self.get_after(
            view, AUTOCOMPLETE_CHAR_LIMIT
        )
        if new_before == self.before and new_after == self.after:
            return
        self.autocompleting = self.should_autocomplete(
            view,
            old_before=self.before,
            old_after=self.after,
            new_before=new_before,
            new_after=new_after,
        )
        self.before = new_before
        self.after = new_after
        self.actions_since_completion += 1
        if self.autocompleting:
            pass  # on_selection_modified_async will show the popup
        else:
            if self.popup_is_ours and time.time() > self.no_hide_until:
                view.hide_popup()
                self.popup_is_ours = False
                self.just_pressed_tab = False
            if not self.popup_is_ours:
                self.just_pressed_tab = False
            if self.actions_since_completion >= 2:
                self.choices = []

    def should_autocomplete(
        self, view, *, old_before, old_after, new_before, new_after
    ):
        return (
            self.actions_since_completion >= 1
            and len(view.sel()) <= 100
            and all(sel.begin() == sel.end() for sel in view.sel())
            and self.all_same_prefix(view, [sel.begin() for sel in view.sel()])
            and self.all_same_suffix(view, [sel.begin() for sel in view.sel()])
            and new_before != ""
            and (
                new_after[:100] != old_after[1:101]
                or new_after == ""
                or (len(view.sel()) >= 2 and self.seen_changes)
            )
            and old_before[-100:] == new_before[-101:-1]
        )

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
                s = view.substr(sublime.Region(i, i + 1))
                if s.isalnum() or s == "_":
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

    def get_preferences(self):
        return sublime.load_settings(PREFERENCES_PATH)

    def max_num_results(self):
        return self.get_settings().get("max_num_results")

    def on_selection_modified_async(self, view):
        if view.window() is None:
            self.clear_delay_timer()
            return
        view = view.window().active_view()
        if not self.autocompleting:
            self.clear_delay_timer()
            return
        self.just_pressed_tab = False
        max_num_results = self.max_num_results()
        response = autocomplete(
            self.before,
            self.after,
            view.file_name(),
            self.region_includes_beginning,
            self.region_includes_end,
            max_num_results,
        )
        if response is None or not self.autocompleting:
            self.clear_delay_timer()
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
            self.clear_delay_timer()
        else:
            if view.is_popup_visible():
                self.show_competion_dialog(view, to_show, substitute_begin)
            else:
                self.clear_delay_timer()

                auto_complete_delay = self.get_auto_complete_delay()

                if auto_complete_delay >= 1:
                    self.delay_competion_dialog(
                        auto_complete_delay, view, to_show, substitute_begin
                    )
                else:
                    self.show_competion_dialog(view, to_show, substitute_begin)

    def show_competion_dialog(self, view, to_show, substitute_begin):
        my_show_popup(view, to_show, substitute_begin)
        self.popup_is_ours = True
        self.seen_changes = False

    def delay_competion_dialog(
        self, auto_complete_delay, view, to_show, substitute_begin
    ):
        self.timer = Timer(
            auto_complete_delay,
            self.show_competion_dialog,
            [view, to_show, substitute_begin],
        )
        self.timer.start()

    def clear_delay_timer(self):
        if self.timer is not None:
            self.timer.cancel()

    def get_auto_complete_delay(self):
        auto_complete_delay_millis = self.get_preferences().get("auto_complete_delay")
        auto_complete_delay_sec = 0
        if auto_complete_delay_millis is not None:
            auto_complete_delay_sec = (auto_complete_delay_millis / 1000) % 60
        return auto_complete_delay_sec

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
            if show_detail and "detail" in choice and isinstance(choice["detail"], str):
                annotation += escape("  " + choice["detail"].replace("\n", " "))
            with_padding = escape(to_show[i] + " " * padding)
            to_show[i] = with_padding + annotation
        for line in self.user_message:
            to_show.append(
                """<span style="font-size: 10;">""" + escape(line) + "</span>"
            )
        to_show = "<br>".join(to_show)
        return to_show

    def insert_completion(self, view, choice_index, popup):  # pylint: disable=W0613
        self.tab_index = (choice_index + 1) % len(self.choices)
        if choice_index != 0:
            self.tab_only = True
        a, b = self.substitute_interval
        choice = self.choices[choice_index]
        new_prefix = choice["new_prefix"]
        prefix = choice["old_suffix"]  # The naming here is very bad
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
            my_show_popup(view, "<br> <br>".join(popup_content), a)
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
        if (
            command_name in ["insert_best_completion", "tab_nine_leader_key"]
            and len(self.choices) >= 1
        ):
            self.just_pressed_tab = True
            return self.insert_completion(view, self.tab_index, popup=True)
        if command_name == "tab_nine_reverse_leader_key" and len(self.choices) >= 1:
            self.just_pressed_tab = True
            index = (self.tab_index - 2 + len(self.choices)) % len(self.choices)
            return self.insert_completion(view, index, popup=True)

    def on_query_context(
        self, view, key, operator, operand, match_all
    ):  # pylint: disable=W0613
        if key == "tab_nine_choice_available":
            assert operator == sublime.OP_EQUAL
            return (
                self.just_pressed_tab
                and operand <= len(self.choices)
                and not self.tab_only
                and operand != 1
            )
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
        ("https://tabnine.com/semantic", None, "tabnine.com/semantic"),
        (
            "tabnine.com/semantic",
            "https://tabnine.com/semantic",
            "tabnine.com/semantic",
        ),
        ("www.tabnine.com/buy", "https://tabnine.com/buy", "tabnine.com/buy"),
        ("tabnine.com", "https://tabnine.com", "tabnine.com"),
    ]
    for url, navigate_to, display in urls:
        if url in s:
            if navigate_to is None:
                navigate_to = url
            s = s.replace(
                html.escape(url), '<a href="{}">{}</a>'.format(navigate_to, display)
            )
            break
    return s


def get_additional_detail(choice):
    s = None
    if "documentation" in choice:
        s = choice["documentation"]
    return s


def format_documentation(documentation):
    if isinstance(documentation, str):
        return escape(documentation)
    elif (
        isinstance(documentation, dict)
        and "kind" in documentation
        and documentation["kind"] == "markdown"
        and "value" in documentation
    ):
        return escape(documentation["value"])
    else:
        return escape(str(documentation))


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


def plugin_unloaded():
    from package_control import events

    if events.remove("Tabnine"):
        uninstalling()
