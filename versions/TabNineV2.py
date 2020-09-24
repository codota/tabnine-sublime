import sublime
import sublime_plugin
import html
import webbrowser
import time
import json

from threading import Timer
from ..TabNineProcess import tabnine_proc
SETTINGS_PATH = 'TabNine.sublime-settings'
AUTOCOMPLETE_CHAR_LIMIT = 100000
PREFERENCES_PATH = 'Preferences.sublime-settings'

GLOBAL_HIGHLIGHT_COUNTER = 0

GLOBAL_IGNORE_EVENTS = False


class TabNineCommand(sublime_plugin.TextCommand):
    def run(*args, **kwargs): #pylint: disable=W0613,E0211
        print("TabNine commands are supposed to be intercepted by TabNineListener")

class TabNineLeaderKeyCommand(TabNineCommand):
    pass
class TabNineReverseLeaderKeyCommand(TabNineCommand):
    pass

class SubstituteCommand(sublime_plugin.TextCommand):
    def run(self, edit, begin, end, old_suffix):
        print("in substitution", self.view.substr(sublime.Region(begin, end)))
        if old_suffix in self.view.substr(sublime.Region(begin, end)):
            self.view.erase(edit, sublime.Region(begin, end))


class TabNineListener(sublime_plugin.EventListener):
    def __init__(self):
        self.before = ""
        self.after = ""
        self.region_includes_beginning = False
        self.region_includes_end = False
        self.before_begin_location = 0
        self.autocompleting = False
        self.actions_since_completion = 1
        self.seen_changes = False
        self._current_location = 0
        self._user_message = []
        self._last_location = None
        self._results = []
        self._completion_prefix = ""
        self._expected_prefix = ""

 
        def update_settings():
            print("before update settings")
            sublime.load_settings(PREFERENCES_PATH).set('auto_complete', True)
            sublime.load_settings(PREFERENCES_PATH).set('auto_complete_triggers', [{
                "characters": ".(){}[],\'\"=<>/\\+-|&*%=$#@! qazwsxedcrfvtgbyhnujmikolpQAZWSXEDCRFVTGBYHNUJMIKOLP",
                "selector": "source.python - constant.numeric"
            },
            {
                "characters": ":.(){}[],\'\"=<>/\\+-|&*%=$#@! qazwsxedcrfvtgbyhnujmikolpQAZWSXEDCRFVTGBYHNUJMIKOLP",
                "selector": "source & - source.python - constant.numeric"
            },
            {
                "characters": " qazwsxedcrfvtgbyhnujmikolpQAZWSXEDCRFVTGBYHNUJMIKOLP",
                "selector": "text"
            }])
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
        view.set_status('tabnine', "test")

        
    def on_query_completions(self, view, prefix, locations):
        self._current_location = locations[0]
        self._completion_prefix = prefix
        if self._last_location != locations[0]:
            self._last_location = locations[0]
            def run_complete():
                request = {
                    "Autocomplete": {
                        "before": self.before,
                        "after": self.after,
                        "filename": view.file_name(),
                        "region_includes_beginning": self.region_includes_beginning,
                        "region_includes_end": self.region_includes_end,
                        "max_num_results": 5,
                    }
                }


                response = tabnine_proc.request(request)
                print("================================================================")
                print("request", json.dumps(response))
                self._expected_prefix = response["old_prefix"]
                self._results = response["results"]
                self._user_message = response["user_message"]
                if self._results and self._user_message and not view.is_popup_visible():
                    view.show_popup(
                        "<div>" + "<br>".join(self._user_message) + "</div>",
                        sublime.COOPERATE_WITH_AUTO_COMPLETE | sublime.HIDE_ON_MOUSE_MOVE,
                        location=locations[0],
                        max_width=500,
                        max_height=1200,
                        on_navigate=webbrowser.open,
                    )
                if not self._results and view.is_popup_visible():
                    view.hide_popup()
                view.run_command('hide_auto_complete')
                view.run_command('auto_complete', {
                    'api_completions_only': False,
                    'disable_auto_insert': True,
                    'next_completion_if_showing': True
                })
            sublime.set_timeout_async(run_complete, 0)
            view.hide_popup()
            print("in empty async request", prefix)
            return []
        if self._last_location == locations[0]:
            self._last_location = None
            print("in sync", prefix)
            completions = [(r.get("new_prefix") + "\t" + r.get("detail", "TabNine"), r.get("new_prefix") + "$0" + r.get("new_suffix", "")) for r in self._results]
            print("completions", completions)
            if not completions:
                view.hide_popup()
            return completions

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
    def get_preferences(self):
        return sublime.load_settings(PREFERENCES_PATH)

    def max_num_results(self):
        return self.get_settings().get("max_num_results")
    def on_post_text_command(self, view, command_name, args):
         if command_name in [ "commit_completion", "insert_best_completion"] :
            
            current_position = view.sel()[0].end()
            print("in post text command", view.substr(view.line(current_position)))
            previous_position = self._current_location
            end_of_line = view.line(sublime.Region(current_position, current_position))
            substitution = view.substr(sublime.Region(previous_position, current_position))
            print("substitution", substitution)
            
            existing_choice = next((x for x in self._results if x["new_prefix"] == self._completion_prefix + substitution), None)
            self.actions_since_completion = 0
            if existing_choice is not None:
                current_position += len(existing_choice["new_suffix"])
                if existing_choice["old_suffix"]:
                    new_position = min(current_position + (current_position - previous_position), end_of_line.end())
                    new_args = {
                        "begin": current_position,
                        "end": new_position,
                        "old_suffix": existing_choice["old_suffix"]
                    }
                    view.run_command("substitute", new_args)

    def on_text_command(self, view, command_name, args):
        if command_name in [ "commit_completion", "insert_best_completion"] :
            # self._current_location = view.sel()[0].begin()
            print("in text command", view.substr(view.line(self._current_location)))
            view.hide_popup()
            return

    def on_query_context(self, view, key, operator, operand, match_all): #pylint: disable=W0613
        if key == "tab_nine_choice_available":
            # assert operator == sublime.OP_EQUAL
            # return self.just_pressed_tab and operand <= len(self.choices) and not self.tab_only and operand != 1
            return False
        if key == "tab_nine_leader_key_available":
            return False
            # assert operator == sublime.OP_EQUAL
            # return (self.choices != [] and view.is_popup_visible()) == operand
        if key == "tab_nine_reverse_leader_key_available":
            return False
            # assert operator == sublime.OP_EQUAL
            # return (self.choices != []) == operand

def escape(s):
    s = html.escape(s, quote=False)
    s = s.replace(" ", "&nbsp;")
    urls = [
        ('https://tabnine.com/semantic', None, 'tabnine.com/semantic'),
        ('tabnine.com/semantic', 'https://tabnine.com/semantic', 'tabnine.com/semantic'),
        ('www.tabnine.com/buy', 'https://tabnine.com/buy', 'tabnine.com/buy'),
        ('tabnine.com', 'https://tabnine.com', 'tabnine.com'),
        
    ]
    for url, navigate_to, display in urls:
        if url in s:
            if navigate_to is None:
                navigate_to = url
            s = s.replace(html.escape(url), '<a href="{}">{}</a>'.format(navigate_to, display))
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

class OpenconfigCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        request = {
            "Configuration": {
            }
        }

        response = tabnine_proc.request(request)

def plugin_unloaded():
    from package_control import events

    if events.remove('TabNine'):
        TabNineProcess.run_tabnine(True, ['--uninstalling'])
