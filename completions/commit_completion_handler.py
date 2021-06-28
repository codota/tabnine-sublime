import sublime
from ..lib import logger
from ..lib.requests import set_completion_state


def handle_completion(view, completions, location, prefix):
    current_location = view.sel()[0].end()
    current_line = view.line(sublime.Region(current_location, current_location))
    substitution = view.substr(sublime.Region(location, current_location))

    selected_completion = next(
        (x for x in completions if x["new_prefix"] == prefix + substitution),
        None,
    )

    if selected_completion is not None:

        if selected_completion["old_suffix"].strip():

            logger.debug("selected_completion: {}".format(selected_completion))
            logger.debug("old_suffix: {}".format(selected_completion["old_suffix"]))
            logger.debug("new_suffix: {}".format(selected_completion["new_suffix"]))

            end_search_location = min(
                current_location
                + len(substitution)
                + len(selected_completion["new_suffix"]),
                current_line.end(),
            )

            start_search_location = current_location + len(
                selected_completion["new_suffix"]
            )

            after_substitution = view.substr(
                sublime.Region(start_search_location, end_search_location)
            )

            logger.debug("substitution: {}".format(substitution))
            logger.debug("after_substitution: {}".format(after_substitution))

            old_suffix_index = after_substitution.find(
                selected_completion["old_suffix"]
            )
            if old_suffix_index != -1:

                start_erase_location = start_search_location + old_suffix_index
                args = {
                    "begin": start_erase_location,
                    "end": start_erase_location
                    + len(selected_completion["old_suffix"]),
                    "old_suffix": selected_completion["old_suffix"],
                }
                view.run_command("tab_nine_post_substitution", args)
        set_completion_state(
            view.file_name(),
            current_location,
            location - len(prefix),
            current_line,
            substitution,
            selected_completion,
            completions,
        )
