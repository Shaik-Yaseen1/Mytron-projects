# SD Card Formatter (macOS)

This project formats externally inserted removable SD cards in a repeat cycle.

## Files

- `format_sd_simple.py` - Main formatter script (self-contained)
- `sd_formatter_launcher.applescript` - Terminal launcher script

## Run in Terminal

```bash
cd "/Users/palakgarg/Desktop/Data Format"
python3 -u format_sd_simple.py
```

If formatting needs admin permissions:

```bash
cd "/Users/palakgarg/Desktop/Data Format"
sudo python3 -u format_sd_simple.py
```

## Desktop App Shortcut

Double-click `SD Card Formatter.app` on Desktop.

It opens Terminal and runs:

```bash
/usr/bin/python3 -u "/Users/palakgarg/Desktop/Data Format/format_sd_simple.py"
```

## Workflow

1. Live table updates every ~1 second.
2. Insert/remove cards and verify the table rows.
3. Press `Enter` to lock and format all listed cards.
4. Remove cards.
5. Script waits and starts next cycle automatically.

Stop anytime with `Ctrl+C`.

## Safety

Formatting is destructive and erases data on all listed SD cards.
