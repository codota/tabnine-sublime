import sublime
import re

END_LINE_STOP_COMPLETION_CHARACTERS = ",;:"


def get_before(view, char_limit):
    loc = view.sel()[0].begin()
    begin = max(0, loc - char_limit)
    return view.substr(sublime.Region(begin, loc)), begin == 0


def get_after(view, char_limit):
    loc = view.sel()[0].end()
    end = min(view.size(), loc + char_limit)
    return view.substr(sublime.Region(loc, end)), end == view.size()


def active_view():
    """Return currently active view"""
    return sublime.active_window().active_view()


def should_stop_completion_after_end_line(view, current_location):
    last_character = view.substr(max(current_location - 1, 0))
    end_of_line = view.line(current_location).end()
    return (
        end_of_line == current_location
        and last_character in END_LINE_STOP_COMPLETION_CHARACTERS
    )


def is_query_after_new_line(view, current_location):
    last_region = view.substr(
        sublime.Region(max(current_location - 2, 0), current_location)
    ).rstrip()
    is_query_after_new_line = last_region == "" or last_region == "\n"
    return is_query_after_new_line


def should_return_empty_list(view, locations, prefix):
    last_command_insert_snippet = view.command_history(-1)[0] == "insert_snippet"
    wrong_view = active_view().id() != view.id()
    return (
        wrong_view
        or should_stop_completion_after_end_line(view, locations[0])
        or prefix.strip() == ""
        and last_command_insert_snippet
        or not view.match_selector(locations[0], "source | text")
        or is_query_after_new_line(view, locations[0])
    )


def escape_tab_stop_sign(value):
    return re.sub(r"\$", "\\$", value)
