#!/usr/bin/env python3
"""Synchronize Dabot logs older than 15 days to Google Drive using rclone."""
import os
import re
import sys
import shutil
import argparse
import datetime
import subprocess

LOGS_DIR = os.environ.get("DABOT_LOGS_DIR", "/opt/dabot/logs")
GDRIVE_DEST = os.environ.get("DABOT_GDRIVE_DEST", "gdrive:Backups/dabot_logs")
RETENTION_DAYS = 15

PATTERN = re.compile(r'^(?:session|logs_dabot)_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.txt$')


def parse_args():
    parser = argparse.ArgumentParser(description="Upload old Dabot logs to Google Drive")
    parser.add_argument("--days", type=int, default=RETENTION_DAYS, help="Files older than N days (default: 15)")
    parser.add_argument("--logs-dir", type=str, default=LOGS_DIR, help="Path to local logs directory")
    parser.add_argument("--dest", type=str, default=GDRIVE_DEST, help="Remote rclone destination path")
    parser.add_argument("--dry-run", action="store_true", help="Show files to upload without transferring")
    return parser.parse_args()


def is_active_file(filepath: str) -> bool:
    """Return True if the file has been modified in the last 2 hours (likely active)."""
    try:
        mtime = os.path.getmtime(filepath)
        return (datetime.datetime.now().timestamp() - mtime) < 7200
    except Exception:
        return True


def main():
    args = parse_args()
    logs_dir = os.path.abspath(args.logs_dir)
    if not os.path.isdir(logs_dir):
        print(f"[ERROR] Logs directory '{logs_dir}' not found.", file=sys.stderr)
        sys.exit(1)

    now = datetime.datetime.now()
    cutoff_dt = now - datetime.timedelta(days=args.days)
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Checking Dabot logs older than {args.days} days (cutoff: {cutoff_dt.strftime('%Y-%m-%d %H:%M:%S')})")

    candidates = []
    for fname in os.listdir(logs_dir):
        if fname.startswith("staging_"):
            continue
        fpath = os.path.join(logs_dir, fname)
        if not os.path.isfile(fpath):
            continue

        m = PATTERN.match(fname)
        file_dt = None
        if m:
            try:
                file_dt = datetime.datetime.strptime(f"{m.group(1)}_{m.group(2)}", "%Y-%m-%d_%H-%M-%S")
            except Exception:
                pass
        if file_dt is None:
            file_dt = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))

        if file_dt < cutoff_dt and not is_active_file(fpath):
            # Target name: logs_dabot_YYYY-MM-DD_HH-MM-SS.txt
            date_part = file_dt.strftime("%Y-%m-%d_%H-%M-%S")
            dest_name = f"logs_dabot_{date_part}.txt"
            candidates.append((fpath, dest_name, file_dt))

    if not candidates:
        print("No log files found older than 15 days. Nothing to upload.")
        return

    print(f"Found {len(candidates)} log files eligible for Google Drive upload.")

    if args.dry_run:
        print("[DRY-RUN] Files that would be moved to Google Drive:")
        for src, dest, dt in candidates[:10]:
            print(f"  {os.path.basename(src)} -> {dest} (created {dt})")
        if len(candidates) > 10:
            print(f"  ... and {len(candidates) - 10} more files.")
        return

    # Create local staging directory
    staging_dir = os.path.join(logs_dir, "staging_gdrive")
    os.makedirs(staging_dir, exist_ok=True)

    try:
        staged_count = 0
        for src_path, dest_name, _ in candidates:
            staged_path = os.path.join(staging_dir, dest_name)
            try:
                shutil.move(src_path, staged_path)
                staged_count += 1
            except Exception as e:
                print(f"[WARN] Could not stage {src_path}: {e}")

        print(f"Staged {staged_count} files in {staging_dir}. Running rclone transfer to {args.dest}...")

        cmd = [
            "rclone", "move",
            staging_dir, args.dest,
            "--fast-list",
            "--transfers", "4",
            "--drive-chunk-size", "16M",
            "--stats", "10s",
            "--verbose"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Successfully uploaded {staged_count} log files to {args.dest}!")
            # Clean up empty staging dir
            try:
                os.rmdir(staging_dir)
            except Exception:
                pass
        else:
            print(f"[ERROR] rclone failed with code {result.returncode}:\n{result.stderr}", file=sys.stderr)
            sys.exit(result.returncode)

    except Exception as e:
        print(f"[CRITICAL ERROR] Failed during log sync: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
