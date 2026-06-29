import readline
readline.parse_and_bind("tab: complete")
readline.parse_and_bind("bind ^I rl_complete")
print(readline.get_current_history_length())
