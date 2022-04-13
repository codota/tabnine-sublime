from .tab_nine_process import tabnine_proc
from .completion_origin import CompletionOrigin
import os


def get_capabilities():
    return tabnine_proc.request({"Features": {}})


def uninstalling():
    tabnine_proc.request({"Uninstalling": {}})


def set_state(state):
    tabnine_proc.request({"SetState": {"state_type": state}})


def open_config():
    tabnine_proc.request({"Configuration": {}})


def prefetch(file_name):
    tabnine_proc.request({"Prefetch": {"filename": file_name}})


def autocomplete(
    before,
    after,
    file_name,
    region_includes_beginning,
    region_includes_end,
    max_num_results=5,
):
    request = {
        "Autocomplete": {
            "before": before,
            "after": after,
            "filename": file_name,
            "region_includes_beginning": region_includes_beginning,
            "region_includes_end": region_includes_end,
            "max_num_results": max_num_results,
        }
    }
    return tabnine_proc.request(request)


def set_completion_state(
    file_name,
    current_location,
    before_prefix_location,
    current_line,
    substitution,
    selected_completion,
    completions,
):
    line_prefix_length = (current_location - len(substitution)) - current_line.begin()
    length = current_location - before_prefix_location
    net_length = len(substitution)
    request = {
        "Selection": {
            "language": get_language(file_name),
            "length": length,
            "net_length": net_length,
            "strength": selected_completion.get("detail", ""),
            "origin": selected_completion.get("origin", CompletionOrigin.UNKNOWN),
            "index": completions.index(selected_completion),
            "line_prefix_length": line_prefix_length,
            "line_net_prefix_length": line_prefix_length - (length - net_length),
            "line_suffix_length": current_line.end() - current_location,
            "num_of_suggestions": len(completions),
            "num_of_vanilla_suggestions": count_by_origin(
                completions, CompletionOrigin.VANILLA
            ),
            "num_of_deep_local_suggestions": count_by_origin(
                completions, CompletionOrigin.LOCAL
            ),
            "num_of_deep_cloud_suggestions": count_by_origin(
                completions, CompletionOrigin.CLOUD
            ),
            "num_of_lsp_suggestions": count_by_origin(
                completions, CompletionOrigin.LSP
            ),
            "suggestions": [
                {
                    "length": len(x["new_prefix"]),
                    "strength": x.get("detail", ""),
                    "origin": x.get("origin", CompletionOrigin.UNKNOWN),
                }
                for x in completions
            ],
        }
    }
    set_state(request)


def count_by_origin(completions, origin):
    return len([x for x in completions if x["origin"] == origin])


def get_language(file_name):
    if file_name is not None:
        parts = file_name.split(".")
        if len(parts) > 1:
            return parts[-1]
    return "undefined"
