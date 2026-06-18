import readline
def completer(text, state):
    options = ['apple', 'banana', 'apricot', 'blueberry']
    matches = [o for o in options if o.startswith(text)]
    if state < len(matches):
        return matches[state]
    return None

readline.parse_and_bind("bind ^I rl_complete")
readline.parse_and_bind("tab: complete")
readline.parse_and_bind("set show-all-if-ambiguous on")
readline.set_completer(completer)
print("Type 'a' and hit tab:")
input("> ")
