tell application "Terminal"
	activate
	do script "cd " & quoted form of "/Users/palakgarg/Desktop/Data Format" & " && /usr/bin/python3 -u " & quoted form of "/Users/palakgarg/Desktop/Data Format/format_sd_simple.py"
end tell
