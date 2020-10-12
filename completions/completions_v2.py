import sublime
import sublime_plugin
import html
import webbrowser
import time
import json
from shutil import copyfile
import os

from ..tab_nine_process import tabnine_proc
from ..lib import logger
SETTINGS_PATH = 'TabNine.sublime-settings'
AUTOCOMPLETE_CHAR_LIMIT = 100000
PREFERENCES_PATH = 'Preferences.sublime-settings'
COMPLEATIONS_REQUEST_TRESHOLD = 1


class TabNineCommand(sublime_plugin.TextCommand):
    def run(*args, **kwargs): #pylint: disable=W0613,E0211
        logger.info("TabNine commands are supposed to be intercepted by TabNineListener")

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
        self._stop_completion = True
        self._replace_completion_with_next_completion = False
        self._completions = []

        def _update_settings():
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
            sublime.save_settings(PREFERENCES_PATH)

        sublime.set_timeout(_update_settings, 250)


    def get_before(self, view, char_limit):
        loc = view.sel()[0].begin()
        begin = max(0, loc - char_limit)
        return view.substr(sublime.Region(begin, loc)), begin == 0
    def get_after(self, view, char_limit):
        loc = view.sel()[0].end()
        end = min(view.size(), loc + char_limit)
        return view.substr(sublime.Region(loc, end)), end == view.size()

    def on_modified(self, view):
        self.on_any_event(view)

        view_sel = view.sel()
        if not view_sel or len(view_sel) == 0:
            return

        current_location = view_sel[0].end()

        last_region = view.substr(sublime.Region(max(current_location - 2, 0), current_location)).rstrip()
        def _run_compete():
            logger.debug("running in on_modified")
            view.run_command('hide_auto_complete')
            view.run_command('auto_complete', {
                    'api_completions_only': False,
                    'disable_auto_insert':  True,
                    'next_completion_if_showing': True,
                    'auto_complete_commit_on_tab': True,
            })
        if current_location - self._last_query_location >= COMPLEATIONS_REQUEST_TRESHOLD and not self._stop_completion and last_region not in ["", os.linesep]:
            sublime.set_timeout_async(_run_compete, 0)

        self._stop_completion = None
    def on_selection_modified(self, view):
        self.on_any_event(view)
    def on_activated(self, view):
        self.on_any_event(view)
        if view.window():
            view.window().status_message("TabNine")
        
    def on_query_completions(self, view, prefix, locations):
        
        logger.debug("in on_query_completions")

        if not view.match_selector(locations[0], "source | text"):
            return ([], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

        last_region = view.substr(sublime.Region(max(locations[0] - 2, 0), locations[0])).rstrip()
        if last_region in [ "", os.linesep]:
            logger.debug("empty character query")
            return ([], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)
        
        if self._replace_completion_with_next_completion == True:
            self._replace_completion_with_next_completion = False
            return self._completions
            
        if self._last_query_location == locations[0] and self._last_location is None:
            logger.debug("last location is None")
            return self._completions

        self._last_query_location = locations[0]
        self._completion_prefix = prefix
        old_prefix = None
        if self._last_location != locations[0]:
            temp_location = self._last_location
            self._last_location = locations[0]
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
                if response is None :
                    self._results = []
                    self._user_message = []
                    return
                
                logger.debug("--- response ---")
                logger.jsonstr(response)
                logger.debug("--- end response ---")

                self._results = response["results"]
                self._user_message = response["user_message"]
                old_prefix = response["old_prefix"]

                if len(self._results) < 1:
                    return
                    
                if self._results and self._user_message and view.window():
                    view.window().status_message(" ".join(self._user_message))
                elif view.window():
                    view.window().status_message("TabNine")


                view.run_command('auto_complete', {
                    'api_completions_only': False,
                    'disable_auto_insert':  True,
                    'next_completion_if_showing': True,
                    'auto_complete_commit_on_tab': True,
                })
                
            view.run_command('hide_auto_complete')
            sublime.set_timeout_async(_run_complete, 0)

            return ([], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)
        if self._last_location == locations[0]:
            self._last_location = None
            if len(self._results) == 1 and old_prefix is None:
                existing = view.substr(sublime.Region(max(locations[0] - (len(prefix) + 2), 0), locations[0]))
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

            self._completions = [(r.get("new_prefix") + "\t" + r.get("detail", "TabNine"), r.get("new_prefix") + "$0" + r.get("new_suffix", "")) for r in self._results]

            logger.debug("completions: {}".format(self._completions))

            flags = sublime.INHIBIT_WORD_COMPLETIONS
            if len(self._completions) > 0:
                flags = 0
            return (self._completions, flags)

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
        ) = self.get_before(view, AUTOCOMPLETE_CHAR_LIMIT)
        new_after, self.region_includes_end = self.get_after(view, AUTOCOMPLETE_CHAR_LIMIT)
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
         logger.debug("on_post_text_command, command: {}, args: {} ".format(command_name, args))
         if command_name == "replace_completion_with_next_completion":
            self._replace_completion_with_next_completion = False
            
         if command_name in ["left_delete", "commit_completion", "insert_best_completion", "replace_completion_with_next_completion"]: 
            self._stop_completion = True
            view.hide_popup()
            
         if command_name in [ "commit_completion", "insert_best_completion", "replace_completion_with_next_completion"] :
            
            current_location = view.sel()[0].end()
            previous_location = self._last_query_location
            end_of_line = view.line(sublime.Region(current_location, current_location))
            substitution = view.substr(sublime.Region(previous_location, current_location))
            
            existing_choice = next((x for x in self._results if x["new_prefix"] == self._completion_prefix + substitution), None)

            if existing_choice is not None:

                if existing_choice["old_suffix"].strip():

                    logger.debug("existing_choice: {}".format(existing_choice))
                    logger.debug("old_suffix: {}".format(existing_choice["old_suffix"]))
                    logger.debug("new_suffix: {}".format(existing_choice["new_suffix"]))

                    end_search_location = min(current_location + len(substitution) + len(existing_choice["new_suffix"]), end_of_line.end())

                    start_search_location = current_location + len(existing_choice["new_suffix"])

                    after_substitution = view.substr(sublime.Region(start_search_location, end_search_location))

                    logger.debug("substitution: {}".format(substitution))
                    logger.debug("after_substitution: {}".format(after_substitution))
            
                    old_suffix_index = after_substitution.find(existing_choice["old_suffix"])
                    if old_suffix_index != -1:
                        
                        start_erase_location = start_search_location + old_suffix_index
                        args = {
                            "begin": start_erase_location,
                            "end": start_erase_location + len(existing_choice["old_suffix"]),
                            "old_suffix": existing_choice["old_suffix"]
                        }
                        view.run_command("tab_nine_post_substitution", args)
                        
         if command_name in ["insert_snippet"] :
            logger.debug("running insert snippet")
            def _run_compete():
                view.run_command('auto_complete', {
                    'api_completions_only': False,
                    'disable_auto_insert':  True,
                    'next_completion_if_showing': True,
                    'auto_complete_commit_on_tab': True,
                })
            view.run_command('hide_auto_complete')
            sublime.set_timeout_async(_run_compete, 0)
            return

    def on_text_command(self, view, command_name, args):


        logger.debug("text command, command: {}, args: {}".format(command_name, args))
 
        if command_name == "replace_completion_with_next_completion":
            self._replace_completion_with_next_completion = True

        if command_name in ["left_delete"] :
            def _run_complete():
                logger.debug("running left_delete")
                view.run_command('auto_complete', {
                    'api_completions_only': False,
                    'disable_auto_insert':  True,
                    'next_completion_if_showing': True,
                    'auto_complete_commit_on_tab': True,
                })
            view.run_command('hide_auto_complete')
            
            current_location = view.sel()[0].end()
            last_character = view.substr(max(current_location - 1, 0))
            selection = view.substr(view.sel()[0])
            
            if last_character != "\n" and last_character != " " and not "\n" in selection:
                sublime.set_timeout_async(_run_complete, 0)
            
        if command_name in [ "left_delete", "commit_completion", "insert_best_completion", "replace_completion_with_next_completion"] :
            self._stop_completion = True
            return

    def on_query_context(self, view, key, operator, operand, match_all): #pylint: disable=W0613
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
def plugin_loaded():
    for language in ["Python", "JavaScript"]:
        src = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir, 'rules', language, 'Completion Rules.tmPreferences'))
        dest = os.path.join(sublime.packages_path(), language, 'Completion Rules.tmPreferences')
        if not os.path.exists(dest):
            if not os.path.exists(os.path.dirname(dest)):
                os.makedirs(os.path.dirname(dest))
            copyfile(src, dest)

def plugin_unloaded():
    from package_control import events

    if events.remove('TabNine'):
        tabnine_proc.uninstalling()
