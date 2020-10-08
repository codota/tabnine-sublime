from .tab_nine_process import tabnine_proc
from .settings  import get_settings_eager
import sublime_plugin
import sublime

capabilities = tabnine_proc.get_capabilities()
settings = get_settings_eager()

if settings.get('native_auto_complete', False) or (capabilities["enabled_features"] and "sublime.new-experience" in capabilities["enabled_features"]): 
    from .completions.completions_v2 import *
else: 
    from .completions.completions_v1 import *
