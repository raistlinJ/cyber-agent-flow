import readline
import sys

def completer(text, state):
    options = ['apple', 'banana', 'apricot', 'blueberry']
    matches = [o for o in options if o.startswith(text)]
    if state == 0 and len(matches) > 1:
        # Check if we should print
        # If text hasn't changed since last tab, maybe?
        pass
    if state < len(matches):
        return matches[state]
    return None

if "libedit" in readline.__doc__:
    readline.parse_and_bind("bind ^I rl_complete")
else:
    readline.parse_and_bind("tab: complete")

readline.set_completer(completer)
print("Type 'a' and hit tab:")
try:
    input("> ")
except EOFError:
    pass
