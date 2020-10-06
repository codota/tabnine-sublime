from .tab_nine_process import tabnine_proc

capabilities = tabnine_proc.get_capabilities()

if capabilities["enabled_features"] and "sublime.new-experience" in capabilities["enabled_features"]: 
    from .completions.completions_v2 import *
else: 
    from .completions.completions_v1 import *