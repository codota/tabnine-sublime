import sublime
import sublime_plugin
import html
import webbrowser
import time
from shutil import copyfile
import os

from ..lib.requests import (
    uninstalling,
    open_config,
    prefetch,
    autocomplete,
    set_state,
    set_completion_state,
)
from ..lib import logger
from ..lib.settings import is_tabnine_disabled
from ..lib.view_helpers import (
    get_before,
    get_after,
    should_stop_completion_after_end_line,
    is_query_after_new_line,
    should_return_empty_list,
    active_view,
    escape_tab_stop_sign,
)

from .commit_completion_handler import handle_completion

SETTINGS_PATH = "TabNine.sublime-settings"
AUTOCOMPLETE_CHAR_LIMIT = 100000
PREFERENCES_PATH = "Preferences.sublime-settings"
COMPLEATIONS_REQUEST_TRESHOLD = 1
STOP_COMPLETION_COMMANDS = [
    "left_delete",
    "commit_completion",
    "insert_best_completion",
    "replace_completion_with_next_completion",
    "toggle_comment",
    "insert_snippet",
    "undo",
    "paste",
]

ATTRIBUTION_ELEMENT = "⌬"


class TabNineCommand(sublime_plugin.TextCommand):
    def run(*args, **kwargs):  # pylint: disable=W0613,E0211
        logger.info(
            "Tabnine commands are supposed to be intercepted by TabNineListener"
        )


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

    def on_modified(self, view):
        logger.debug("in on_modified")
        self.on_any_event(view)

        view_sel = view.sel()
        if not view_sel or len(view_sel) == 0:
            return

        def _run_complete():
            logger.debug("running in on_modified")
            active_view().run_command("hide_auto_complete")
            active_view().run_command(
                "auto_complete",
                {
                    "api_completions_only": False,
                    "disable_auto_insert": True,
                    "next_completion_if_showing": False,
                    "auto_complete_commit_on_tab": True,
                },
            )

        if self.should_run_completion_on_modified(view):
            sublime.set_timeout_async(_run_complete, 0)

        self._stop_completion = None

    def should_run_completion_on_modified(self, view):
        current_location = view.sel()[0].end()
        is_disabled = is_tabnine_disabled(view)
        stop_completion_after_end_line = should_stop_completion_after_end_line(
            view, current_location
        )
        in_query_after_new_line = is_query_after_new_line(view, current_location)

        is_selector_matched = view.match_selector(current_location, "source | text")

        current_active_view = active_view()
        is_wrong_view = current_active_view is None or (
            current_active_view.id() != view.id()
        )

        if is_wrong_view:
            return False
        if not is_selector_matched:
            return False
        if self._stop_completion:
            return False
        if is_disabled:
            return False
        if stop_completion_after_end_line:
            return False
        if in_query_after_new_line:
            return False
        return (
            current_location - self._last_query_location
            >= COMPLEATIONS_REQUEST_TRESHOLD
        )

    def on_selection_modified(self, view):
        self.on_any_event(view)

    def on_activated(self, view):
        self.on_any_event(view)
        view.set_status("tabnine-status", ATTRIBUTION_ELEMENT + " tabnine")

    def on_query_completions(self, view, prefix, locations):
        def _run_complete():

            response = autocomplete(
                self.before,
                self.after,
                view.file_name(),
                self.region_includes_beginning,
                self.region_includes_end,
            )
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

            view.run_command(
                "auto_complete",
                {
                    "api_completions_only": True,
                    "disable_auto_insert": True,
                    "next_completion_if_showing": False,
                    "auto_complete_commit_on_tab": True,
                },
            )

        EMPTY_COMPLETION_LIST = (
            [],
            sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS,
        )

        if should_return_empty_list(view, locations, prefix):
            return EMPTY_COMPLETION_LIST

        if is_tabnine_disabled(view):
            return EMPTY_COMPLETION_LIST if prefix.strip() == "" else None

        if self._replace_completion_with_next_completion:
            self._replace_completion_with_next_completion = False
            return self.get_completions_with_flags()

        if self._last_query_location == locations[0] and self._last_location is None:
            if len(self._completions) == 0 and prefix == "":
                self._last_location = locations[0]
                active_view().run_command("hide_auto_complete")
                sublime.set_timeout_async(_run_complete, 0)
                return EMPTY_COMPLETION_LIST

            if self.has_competions():
                return (self._completions, sublime.INHIBIT_WORD_COMPLETIONS)
            else:
                return EMPTY_COMPLETION_LIST

        self._last_query_location = locations[0]
        self._completion_prefix = prefix
        self._old_prefix = None
        if self._last_location != locations[0]:
            self._last_location = locations[0]
            active_view().run_command("hide_auto_complete")
            sublime.set_timeout_async(_run_complete, 0)

            return EMPTY_COMPLETION_LIST
        if self._last_location == locations[0]:
            self._last_location = None
            self.handle_tabnine_commands(view, locations, prefix)

            self._completions = self.get_completion()

            logger.debug("completions: {}".format(self._completions))

            return self.get_completions_with_flags()

    def get_completion(self):
        return [
            [
                "{}\t{} {}".format(r.get("new_prefix"), ATTRIBUTION_ELEMENT, "tabnine"),
                "{}$0{}".format(
                    escape_tab_stop_sign(r.get("new_prefix")), r.get("new_suffix", "")
                ),
            ]
            for r in self._results
        ]

    def get_completions_with_flags(self):
        flags = 0
        if self.has_competions():
            flags = sublime.INHIBIT_WORD_COMPLETIONS
        return (self._completions, flags)

    def has_competions(self):
        return len(self._completions) > 0

    def handle_tabnine_commands(self, view, locations, prefix):
        if len(self._results) == 1 and self._old_prefix is None and prefix != "":
            tabnine_command = "::{}".format(prefix)
            existing_text = view.substr(
                sublime.Region(
                    max(locations[0] - len(tabnine_command), 0), locations[0]
                )
            )
            is_tabnine_command = existing_text == tabnine_command
            if is_tabnine_command:
                view.show_popup(
                    self._results[0]["new_prefix"],
                    sublime.COOPERATE_WITH_AUTO_COMPLETE,
                    location=locations[0],
                    max_width=1500,
                    max_height=1200,
                    on_navigate=webbrowser.open,
                )

    def on_activated_async(self, view):
        file_name = view.file_name()
        if file_name is not None:
            prefetch(file_name)

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
        new_after, self.region_includes_end = get_after(view, AUTOCOMPLETE_CHAR_LIMIT)
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

    def on_post_text_command(self, view, command_name, args):
        logger.debug(
            "on_post_text_command, command: {}, args: {} ".format(command_name, args)
        )

        if command_name == "replace_completion_with_next_completion":
            self._replace_completion_with_next_completion = False

        if self.is_stop_completion(command_name, args):
            self._stop_completion = True

        if command_name in [
            "commit_completion",
            "insert_best_completion",
            "replace_completion_with_next_completion",
        ]:
            handle_completion(
                view, self._results, self._last_query_location, self._completion_prefix
            )

    def on_text_command(self, view, command_name, args):

        logger.debug("text command, command: {}, args: {}".format(command_name, args))

        view.hide_popup()

        if command_name == "replace_completion_with_next_completion":
            self._replace_completion_with_next_completion = True

        if self.is_stop_completion(command_name, args):
            self._stop_completion = True

    def is_stop_completion(self, command_name, args):
        is_new_line_inserted = command_name == "insert" and args["characters"] == "\n"
        return command_name in STOP_COMPLETION_COMMANDS or is_new_line_inserted

    def on_query_context(
        self, view, key, operator, operand, match_all
    ):  # pylint: disable=W0613
        if key in [
            "tab_nine_choice_available",
            "tab_nine_leader_key_available",
            "tab_nine_reverse_leader_key_available",
        ]:
            return False


def plugin_loaded():
    _setup_config()
    _init_rules()


def _setup_config():
    sublime.load_settings(PREFERENCES_PATH).set("auto_complete", True)
    sublime.load_settings(PREFERENCES_PATH).set(
        "auto_complete_triggers",
        [
            {
                "characters": ".(){}[],'\"=<>/\\+-|&*%=$#@! ",
                "selector": "source.python",
            },
            {
                "characters": ":.(){}[],'\"=<>/\\+-|&*%=$#@! ",
                "selector": "source & - source.python - constant.numeric",
            },
            {
                "characters": " qazwsxedcrfvtgbyhnujmikolpQAZWSXEDCRFVTGBYHNUJMIKOLP",
                "selector": "text",
            },
        ],
    )
    sublime.save_settings(PREFERENCES_PATH)


def _revert_config():
    sublime.load_settings(PREFERENCES_PATH).erase("auto_complete_triggers")
    sublime.load_settings(PREFERENCES_PATH).erase("auto_complete")
    sublime.save_settings(PREFERENCES_PATH)


def _init_rules():
    for language in ["Python", "JavaScript"]:
        src = os.path.abspath(
            os.path.join(
                os.path.dirname(os.path.realpath(__file__)),
                os.pardir,
                "rules",
                language,
                "Completion Rules.tmPreferences",
            )
        )
        dest = os.path.join(
            sublime.packages_path(), language, "Completion Rules.tmPreferences"
        )
        if not os.path.exists(dest):
            if not os.path.exists(os.path.dirname(dest)):
                os.makedirs(os.path.dirname(dest))
            copyfile(src, dest)


def plugin_unloaded():
    from package_control import events

    if events.remove("Tabnine"):
        _revert_config()
        uninstalling()
