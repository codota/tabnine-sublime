from .commit_completion_handler import handle_completion
import sublime
import sublime_plugin
import copy

from ..lib import logger
from ..lib.requests import (
    uninstalling,
    autocomplete,
)
from ..lib.view_helpers import (
    get_before,
    get_after,
    escape_tab_stop_sign,
)

AUTOCOMPLETE_CHAR_LIMIT = 100000
ATTRIBUTION_ELEMENT = "⌬"
PREFERENCES_PATH = "Preferences.sublime-settings"


class TabNinePostSubstitutionCommand(sublime_plugin.TextCommand):
    def run(self, edit, begin, end, old_suffix):
        if old_suffix in self.view.substr(sublime.Region(begin, end)):
            self.view.erase(edit, sublime.Region(begin, end))


class TabNineListener(sublime_plugin.EventListener):
    def __init__(self):
        self._state = {"location": 0, "prefix": "", "completions": []}
        self._last_state = None

    def on_query_completions(self, view, prefix, locations):
        self._state["location"] = locations[0]
        self._state["prefix"] = prefix

        before, region_includes_beginning = get_before(view, AUTOCOMPLETE_CHAR_LIMIT)
        after, region_includes_end = get_after(view, AUTOCOMPLETE_CHAR_LIMIT)
        response = autocomplete(
            before,
            after,
            view.file_name(),
            region_includes_beginning,
            region_includes_end,
        )

        self._state["completions"] = response["results"]
        completions = [
            sublime.CompletionItem(
                r.get("new_prefix"),
                annotation="tabnine",
                completion="{}$0{}".format(
                    escape_tab_stop_sign(r.get("new_prefix")), r.get("new_suffix", "")
                ),
                completion_format=sublime.COMPLETION_FORMAT_SNIPPET,
                kind=(
                    sublime.KIND_ID_COLOR_PURPLISH,
                    ATTRIBUTION_ELEMENT,
                    r.get("detail", ""),
                ),
            )
            for r in self._state["completions"]
        ]

        return sublime.CompletionList(
            completions=completions,
            flags=sublime.DYNAMIC_COMPLETIONS | sublime.INHIBIT_REORDER,
        )

    def on_text_command(self, view, command_name, args):
        self._last_state = copy.copy(self._state)

    def on_post_text_command(self, view, command_name, args):
        if command_name in [
            "commit_completion",
            "insert_best_completion",
            "replace_completion_with_next_completion",
        ]:
            handle_completion(view, **self._last_state)

    def on_activated(self, view):
        view.set_status("tabnine-status", ATTRIBUTION_ELEMENT + " tabnine")


def plugin_loaded():
    sublime.load_settings(PREFERENCES_PATH).set("auto_complete", True)


def plugin_unloaded():
    from package_control import events

    if events.remove("Tabnine"):
        uninstalling()
