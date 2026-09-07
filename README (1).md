# SSD → HDD migration

`ssd_to_hdd_migrate.py` auto-detects an external **~2 TB or ~4 TB class** SSD and an external HDD above 15 TB, copies **top-level folders** from the SSD to the HDD with `rsync`, then—after you press **Enter**—permanently deletes those folders on the SSD.

## Merge behavior (default)

By default the script **merges** into the HDD: it uses `rsync --ignore-existing`, so **files that already exist on the HDD are not replaced**, and **nothing is deleted on the HDD** (this script never passes `--delete` to `rsync`). Only files that are **missing** on the destination are copied.

To allow **overwrites** when a path already exists on the HDD, run with `--overwrite`.

## Parallel copies (same run, multiple folders)

When there are **several top-level folders** on the SSD, the script can run **multiple `rsync` processes at once** (default **2** jobs when there are 2+ folders). Each job copies **one folder** into a **different** directory on the HDD, so there are no conflicting writes to the same destination path. This often **uses the SSD/USB/HDD better** than Finder’s single drag-and-drop.

- **Default:** `--parallel` is **2** if there are 2+ folders, else **1** (sequential).
- **Tune:** `python3 .../ssd_to_hdd_migrate.py --parallel 4` (capped by how many folders you have).
- **Sequential:** `--parallel 1` (one folder at a time, like before).
- **Speed:** `rsync` uses **`-W` / `--whole-file`** for local copies (avoids the delta-xfer step on same-machine transfers).

A **single** huge folder is still one `rsync`; splitting that for parallelism would require manual subfolders.

## Two SSDs or two terminals

- **Auto-detect with two SSDs plugged in:** the script may list multiple SSDs; you pick which one each time. Run it **once per SSD** (two runs), choosing a different `--ssd-disk` each time if needed.
- **Two separate script runs in two terminals** to the **same** HDD: only safe if they write to **different** `--dest-dir` trees or disjoint top-level folder names; avoid racing on the same destination folder.
- With **merge** mode, a second run into the same folder mostly **adds missing files** and does not clobber existing HDD files—still avoid parallel writes to the same paths when possible.

## Requirements

- macOS
- **Command Line Tools** (provides `rsync`). If needed: `xcode-select --install`

## If auto-detect fails (“No matching ssd-disk”)

- Many **USB enclosures** make macOS report `SolidState=false` even for an SSD; the script tries a **second pass** that ignores that flag only for drives in the **~2 TB size band** (so a 4 TB HDD is not confused with a 4 TB SSD).
- Auto-detect expects SSD capacity roughly **1.5–5.2 TiB** (typical **2 TB or 4 TB** retail models). If yours differs, use **`--ssd-disk diskN`** after `diskutil list` (the **whole disk**, e.g. `disk6`, not `disk6s2`).
- If nothing matches, the script prints a table of **external** whole disks with sizes; use those ids with `--ssd-disk` / `--hdd-disk`.

## How to run

1. Connect and **mount** the SSD and HDD (they should appear under **Locations** in Finder).

2. In Terminal:

   ```bash
   python3 /Users/palakgarg/Desktop/SSD2HDD/ssd_to_hdd_migrate.py
   ```

   Or, if the script is executable:

   ```bash
   /Users/palakgarg/Desktop/SSD2HDD/ssd_to_hdd_migrate.py
   ```

   If you see “permission denied”:

   ```bash
   chmod +x /Users/palakgarg/Desktop/SSD2HDD/ssd_to_hdd_migrate.py
   ```

3. **Preview only** (no copy, no delete):

   ```bash
   python3 /Users/palakgarg/Desktop/SSD2HDD/ssd_to_hdd_migrate.py --dry-run
   ```

4. **Interactive disk selection** (menu to pick SSD & HDD from detected external disks):

   ```bash
   python3 /Users/palakgarg/Desktop/SSD2HDD/ssd_to_hdd_migrate.py --pick-disks
   ```

   This shows a numbered list of SSD candidates and HDD candidates in the terminal and
   asks you to choose which one to use for this run.

5. **Pick disks manually** by id if auto-detection is wrong (get IDs from `diskutil list`):

   ```bash
   python3 /Users/palakgarg/Desktop/SSD2HDD/ssd_to_hdd_migrate.py --ssd-disk disk4 --hdd-disk disk5
   ```

6. **Custom destination** on the HDD:

   ```bash
   python3 /Users/palakgarg/Desktop/SSD2HDD/ssd_to_hdd_migrate.py --dest-dir /Volumes/YourHDD/Archive
   ```

7. **Overwrite existing HDD files** (not the default):

   ```bash
   python3 /Users/palakgarg/Desktop/SSD2HDD/ssd_to_hdd_migrate.py --overwrite
   ```

See `python3 ssd_to_hdd_migrate.py --help` for all options.

**Note:** Deletion after transfer is permanent (not Trash). Confirm only after you’ve verified the data on the HDD.

## Progress and ETA

Before copying, the script prints **`du`** for **each top-level folder** and a **total** for all of them. The progress bar during `rsync` is for **one folder at a time** (so the “~X GiB” line is that folder’s size, not the whole SSD volume).

While copying, the script prints a **single-line progress bar** on stderr (your normal log lines still go to stdout). **ETA** comes from **GNU rsync** (`--info=progress2`) when your `rsync` supports it (e.g. Homebrew `rsync`). Apple’s default **openrsync** does not support that flag; the script then **estimates** progress by polling **how much space the destination folder uses** on the HDD versus the **approximate source size** from `du`. That estimate is rough (especially with **merge** mode, where many files may be skipped) but gives a usable bar, throughput, and ETA.
