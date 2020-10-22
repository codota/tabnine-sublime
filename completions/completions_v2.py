import sublime
import sublime_plugin
import html
import webbrowser
import time
from shutil import copyfile
import os


from ..lib.tab_nine_process import tabnine_proc
from ..lib import logger
from ..lib.settings import is_tabnine_disabled
from ..lib.view_helpers import (get_before,
                           get_after,
                           is_json_end_line,
                           is_query_after_new_line,
                           should_return_empty_list)

SETTINGS_PATH = 'TabNine.sublime-settings'
AUTOCOMPLETE_CHAR_LIMIT = 100000
PREFERENCES_PATH = 'Preferences.sublime-settings'
COMPLEATIONS_REQUEST_TRESHOLD = 1
STOP_COMPLETION_COMMANDS = ["left_delete", "commit_completion", "insert_best_completion",
                            "replace_completion_with_next_completion", "toggle_comment", "insert_snippet"]


class TabNineCommand(sublime_plugin.TextCommand):
    def run(*args, **kwargs):  # pylint: disable=W0613,E0211
        logger.info(
            "TabNine commands are supposed to be intercepted by TabNineListener")


class TabNinePostSubstitutionCommand(sublime_plugin.TextCommand):
    def run(self, edit, begin, end, old_suffix):
        if old_suffix in self.view.substr(sublime.Region(begin, end)):
            self.view.erase(edit, sublime.Region(begin, end))


class TabNineListener(sublime_plugin.EventListener):
    def __init__(self):
        self.before = ""
        self.after = ""
        self.region_includes_beginning = False
        self.region_includes_end = False
        self._last_query_location = 0
        self._user_message = []
        self._last_location = None
        self._results = []
        self._completion_prefix = ""
        self._old_prefix = None
        self._stop_completion = True
        self._replace_completion_with_next_completion = False
        self._completions = []
        self._left_deleted_selection = None
        self._left_deleted_character = None

    def on_modified(self, view):
        logger.debug("in on_modified")
        self.on_any_event(view)

        view_sel = view.sel()
        if not view_sel or len(view_sel) == 0:
            return

        def _run_complete():
            logger.debug("running in on_modified")
            view.run_command('hide_auto_complete')
            view.run_command('auto_complete', {
                'api_completions_only': False,
                'disable_auto_insert':  True,
                'next_completion_if_showing': True,
                'auto_complete_commit_on_tab': True,
            })
        if self.should_run_completion_on_modified(view):
            sublime.set_timeout_async(_run_complete, 0)

        self._stop_completion = None

    def should_run_completion_on_modified(self, view):
        current_location = view.sel()[0].end()
        is_disabled = is_tabnine_disabled(view)
        in_json_end_line = is_json_end_line(view, current_location)
        in_query_after_new_line = is_query_after_new_line(
            view, current_location)
        return current_location - self._last_query_location >= COMPLEATIONS_REQUEST_TRESHOLD and not self._stop_completion and not is_disabled and not in_json_end_line and not in_query_after_new_line

    def on_selection_modified(self, view):
        self.on_any_event(view)

    def on_activated(self, view):
        self.on_any_event(view)
        view.set_status("tabnine-status", "TabNine")

    def on_query_completions(self, view, prefix, locations):
        def _run_complete():
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
            if response is None:
                self._results = []
                self._user_message = []
                return

            logger.debug("--- response ---")
            logger.jsonstr(response)
            logger.debug("--- end response ---")

            self._results = response["results"]
            self._user_message = response["user_message"]
            self._old_prefix = response["old_prefix"]

            if len(self._results) < 1:
                return

            if self._results and self._user_message and view.window():
                view.window().status_message(" ".join(self._user_message))

            view.run_command('auto_complete', {
                'api_completions_only': False,
                'disable_auto_insert':  True,
                'next_completion_if_showing': True,
                'auto_complete_commit_on_tab': True,
            })
        EMPTY_COMPLETION_LIST = (
            [], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

        if should_return_empty_list(view, locations, prefix):
            return EMPTY_COMPLETION_LIST

        if is_tabnine_disabled(view):
            return EMPTY_COMPLETION_LIST if prefix.strip() == "" else None

        if self._replace_completion_with_next_completion:
            self._replace_completion_with_next_completion = False
            return self._completions

        if self._last_query_location == locations[0] and self._last_location is None:
            if len(self._completions) == 0 and prefix == "":
                self._last_location = locations[0]
                view.run_command('hide_auto_complete')
                sublime.set_timeout_async(_run_complete, 0)
                return EMPTY_COMPLETION_LIST

            if self.has_competions():
                return self._completions
            else:
                return EMPTY_COMPLETION_LIST

        self._last_query_location = locations[0]
        self._completion_prefix = prefix
        self._old_prefix = None
        if self._last_location != locations[0]:
            self._last_location = locations[0]
            view.run_command('hide_auto_complete')
            sublime.set_timeout_async(_run_complete, 0)

            return EMPTY_COMPLETION_LIST
        if self._last_location == locations[0]:
            self._last_location = None
            self.handle_tabnine_commands(view, locations, prefix)

            self._completions = self.get_completion()

            logger.debug("completions: {}".format(self._completions))

            flags = sublime.INHIBIT_WORD_COMPLETIONS
            if len(self._completions) > 0:
                flags = 0
            return (self._completions, flags)

    def get_completion(self):
        return [(r.get("new_prefix") + "\t" + r.get("detail", "TabNine"), r.get(
                "new_prefix") + "$0" + r.get("new_suffix", "")) for r in self._results]

    def has_competions(self):
        return len(self._completions) > 0

    def handle_tabnine_commands(self, view, locations, prefix):
        if len(self._results) == 1 and self._old_prefix is None:
            existing = view.substr(sublime.Region(
                max(locations[0] - (len(prefix) + 2), 0), locations[0]))
            is_tabNine_command = existing == "::{}".format(prefix)
            if is_tabNine_command:
                view.show_popup(
                    self._results[0]["new_prefix"],
                    sublime.COOPERATE_WITH_AUTO_COMPLETE,
                    location=locations[0],
                    max_width=1500,
                    max_height=1200,
                    on_navigate=webbrowser.open,
                )
            else:
                view.hide_popup()

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
        if view.is_scratch():
            return
        (
            new_before,
            self.region_includes_beginning,
        ) = get_before(view, AUTOCOMPLETE_CHAR_LIMIT)
        new_after, self.region_includes_end = get_after(
            view, AUTOCOMPLETE_CHAR_LIMIT)
        if new_before == self.before and new_after == self.after:
            return
        self.before = new_before
        self.after = new_after

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
        logger.debug("on_post_text_command, command: {}, args: {} ".format(
            command_name, args))

        if command_name == "replace_completion_with_next_completion":
            self._replace_completion_with_next_completion = False

        if self.is_stop_completion(command_name, args):
            self._stop_completion = True
            view.hide_popup()

        if command_name in ["left_delete"]:
            def _run_complete():
                logger.debug("running left_delete")
                view.run_command('auto_complete', {
                    'api_completions_only': False,
                    'disable_auto_insert':  True,
                    'next_completion_if_showing': True,
                    'auto_complete_commit_on_tab': True,
                })
            view.run_command('hide_auto_complete')

            if self.should_run_competion_on_delete(view):
                sublime.set_timeout_async(_run_complete, 0)

        if command_name in ["commit_completion", "insert_best_completion", "replace_completion_with_next_completion"]:

            current_location = view.sel()[0].end()
            previous_location = self._last_query_location
            end_of_line = view.line(sublime.Region(
                current_location, current_location))
            substitution = view.substr(sublime.Region(
                previous_location, current_location))

            existing_choice = next(
                (x for x in self._results if x["new_prefix"] == self._completion_prefix + substitution), None)

            if existing_choice is not None:

                if existing_choice["old_suffix"].strip():

                    logger.debug("existing_choice: {}".format(existing_choice))
                    logger.debug("old_suffix: {}".format(
                        existing_choice["old_suffix"]))
                    logger.debug("new_suffix: {}".format(
                        existing_choice["new_suffix"]))

                    end_search_location = min(
                        current_location + len(substitution) + len(existing_choice["new_suffix"]), end_of_line.end())

                    start_search_location = current_location + \
                        len(existing_choice["new_suffix"])

                    after_substitution = view.substr(sublime.Region(
                        start_search_location, end_search_location))

                    logger.debug("substitution: {}".format(substitution))
                    logger.debug("after_substitution: {}".format(
                        after_substitution))

                    old_suffix_index = after_substitution.find(
                        existing_choice["old_suffix"])
                    if old_suffix_index != -1:

                        start_erase_location = start_search_location + old_suffix_index
                        args = {
                            "begin": start_erase_location,
                            "end": start_erase_location + len(existing_choice["old_suffix"]),
                            "old_suffix": existing_choice["old_suffix"]
                        }
                        view.run_command("tab_nine_post_substitution", args)

    def on_text_command(self, view, command_name, args):

        logger.debug("text command, command: {}, args: {}".format(
            command_name, args))
        is_new_line_inserted = command_name == "insert" and args["characters"] == '\n'

        if command_name == "replace_completion_with_next_completion":
            self._replace_completion_with_next_completion = True

        if command_name in ["left_delete"]:
            self._left_deleted_selection = view.substr(view.sel()[0])
            self._left_deleted_character = view.substr(
                max(view.sel()[0].end() - 1, 0))

        if self.is_stop_completion(command_name, args):
            self._stop_completion = True
            return

    def should_run_competion_on_delete(self, view):
        current_location = view.sel()[0].end()
        last_character = view.substr(max(current_location - 1, 0)).strip()
        is_disabled = is_tabnine_disabled(view)
        return last_character != "" and last_character != "\n" and self._left_deleted_character != "\n" and not "\n" in self._left_deleted_selection and not is_disabled

    def is_stop_completion(self, command_name, args):
        is_new_line_inserted = command_name == "insert" and args["characters"] == '\n'
        return command_name in STOP_COMPLETION_COMMANDS or is_new_line_inserted

    def on_query_context(self, view, key, operator, operand, match_all):  # pylint: disable=W0613
        if key == "tab_nine_choice_available":
            return False
        if key == "tab_nine_leader_key_available":
            return False
        if key == "tab_nine_reverse_leader_key_available":
            return False


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
            s = s.replace(html.escape(url),
                          '<a href="{}">{}</a>'.format(navigate_to, display))
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


def plugin_loaded():
    _setup_config()
    _init_rules()


def _setup_config():
    sublime.load_settings(PREFERENCES_PATH).set('auto_complete', True)
    sublime.load_settings(PREFERENCES_PATH).set('auto_complete_triggers', [{
        "characters": ".(){}[],\'\"=<>/\\+-|&*%=$#@! ",
        "selector": "source.python"
    },
        {
        "characters": ":.(){}[],\'\"=<>/\\+-|&*%=$#@! ",
        "selector": "source & - source.python - constant.numeric"
    },
        {
        "characters": " qazwsxedcrfvtgbyhnujmikolpQAZWSXEDCRFVTGBYHNUJMIKOLP",
        "selector": "text"
    }])


def _revert_config():
    sublime.load_settings(PREFERENCES_PATH).erase("auto_complete_triggers")
    sublime.load_settings(PREFERENCES_PATH).erase("auto_complete")


def _init_rules():
    for language in ["Python", "JavaScript"]:
        src = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(
            __file__)), os.pardir, 'rules', language, 'Completion Rules.tmPreferences'))
        dest = os.path.join(sublime.packages_path(), language,
                            'Completion Rules.tmPreferences')
        if not os.path.exists(dest):
            if not os.path.exists(os.path.dirname(dest)):
                os.makedirs(os.path.dirname(dest))
            copyfile(src, dest)


def plugin_unloaded():
    from package_control import events

    if events.remove('TabNine'):
        _revert_config()
        tabnine_proc.uninstalling()
