from .tab_nine_process import tabnine_proc
from .lib.settings  import is_native_auto_complete
import sublime_plugin
import sublime

capabilities = tabnine_proc.get_capabilities()

if is_native_auto_complete() or (capabilities["enabled_features"] and "sublime.new-experience" in capabilities["enabled_features"]): 
    from .completions.completions_v2 import *
else: 
    from .completions.completions_v1 import *