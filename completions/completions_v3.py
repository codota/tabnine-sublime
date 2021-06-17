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
        self._last_query_location = None
        self._user_message = []
        self._results = []
        self._completionList = sublime.CompletionList(None, sublime.DYNAMIC_COMPLETIONS)

    def on_activated(self, view):
        self.on_any_event(view)
        view.set_status("tabnine-status", ATTRIBUTION_ELEMENT + " tabnine")

    def on_query_completions(self, view, prefix, locations):
        logger.debug(
            "on_query_completions, prefix: {}, locations: {}".format(prefix, locations)
        )
        view = view.window().active_view()
        if view.is_scratch():
            return sublime.CompletionList([])

        def _run_complete():
            self.on_any_event(view)

            logger.debug("_run_complete")

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

            if self._results and self._user_message and view.window():
                view.window().status_message(" ".join(self._user_message))

            completions = self.get_completion()

            logger.debug("completions callback: {}".format(completions))

            self._completionList.set_completions(completions, sublime.DYNAMIC_COMPLETIONS)
            self._completionList = sublime.CompletionList(None, sublime.DYNAMIC_COMPLETIONS)

        EMPTY_COMPLETION_LIST = (
            [],
            0, # sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS,
        )

        if should_return_empty_list(view, locations, prefix):
            return EMPTY_COMPLETION_LIST

        if is_tabnine_disabled(view):
            return EMPTY_COMPLETION_LIST if prefix.strip() == "" else None

        # ignore setting self._last_query_location when prefix is empty
        #     set self._last_query_location in `on_text_command` event before commit_completion
        # cases when prefix is empty string:
        # 1) auto completion triggered by punctuation characters
        # 2) triggered between commit_completion command's on_text_command and on_post_text_command, debug logs:
        #       [tabnine] 06/17/21 12:39:05.764 | on_text_command, command: commit_completion, args: None
        #       [tabnine] 06/17/21 12:39:05.769 | on_query_completions, prefix: , locations: [972]
        #       [tabnine] 06/17/21 12:39:05.770 | on_post_text_command, command: commit_completion, args: None 
        #
        if prefix != "":
            self._last_query_location = locations[0] - len(prefix) # the len here must be in the same format as sublime's string
        sublime.set_timeout_async(_run_complete, 0)
        return self._completionList

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

    def on_text_command(self, view, command_name, args):
        logger.debug(
            "on_text_command, command: {}, args: {}".format(command_name, args)
        )

        if command_name in [
            "commit_completion",
            "insert_best_completion",
            "replace_completion_with_next_completion",
        ]:
            if self._last_query_location == None:
                self._last_query_location = view.sel()[0].end()

    def on_post_text_command(self, view, command_name, args):
        logger.debug(
            "on_post_text_command, command: {}, args: {} ".format(command_name, args)
        )

        if command_name in [
            "commit_completion",
            "insert_best_completion",
            "replace_completion_with_next_completion",
        ]:
            handle_completion(
                view, self._results, self._last_query_location, ""
            )

            self._last_query_location = None

    def on_query_context(
        self, view, key, operator, operand, match_all
    ):  # pylint: disable=W0613
        if key in [
            "tab_nine_choice_available",
            "tab_nine_leader_key_available",
            "tab_nine_reverse_leader_key_available",
        ]:
            return False


class OpenconfigCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        open_config()


def plugin_loaded():
    # _setup_config()
    _init_rules()


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
        # _revert_config()
        uninstalling()
