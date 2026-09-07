set launcherPath to "/Users/equipp/Desktop/SSD2HDD/launch_ssd_to_hdd.sh"

tell application "Terminal"
	activate
	do script quoted form of launcherPath
end tell
