This is the Sublime Text client for [TabNine](https://tabnine.com), the all-language autocompleter.

- Indexes your whole project, reading your .gitignore to determine which files to index.
- Type long variable names in just a few keystrokes using the mnemonic completion engine.
- Zero configuration. TabNine works out of the box.
- Highly responsive: typically produces a list of suggestions in less than 10 milliseconds.

A note on licensing: this repo includes source code as well as packaged TabNine binaries. The MIT license only applies to the source code, not the binaries. The binaries are covered by the [TabNine End User License Agreement](https://tabnine.com/eula).


#### auto_complete: false

The TabNine sublime plugin disables sublime's [built in autocomplete](https://www.sublimetext.com/docs/3/auto_complete.html).  
It does that, because sublime's builtin autocomplete does not support all the features required by TabTine.  
If you ever uninstall TabNine, remember to re-enable it.
