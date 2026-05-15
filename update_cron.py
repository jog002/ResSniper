#!/usr/bin/env python3
"""Read scheduled-drops.yaml and write cron entries for scheduled_snipe.py.
Run this daily at 1 AM via cron (it adds itself).

Each restaurant with a scheduled drop gets a cron line that runs at drop_time_et
every day (or every weekday if schedule_dates: weekdays). The scheduled_snipe.py
script computes the target date dynamically (today + days_in_advance).
"""

import os
import subprocess
import sys
import yaml
import zoneinfo

CRON_MARKER = "# ResSniper managed"
SNIPER_SCRIPT = os.path.abspath("scheduled_snipe.py")
UPDATE_SCRIPT = os.path.abspath(__file__)
PYTHON = os.path.abspath(sys.executable)
ET = zoneinfo.ZoneInfo("America/New_York")


def read_crontab():
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout


def write_crontab(content: str):
    p = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True)
    if p.returncode != 0:
        print(f"crontab write failed: {p.stderr}")
        sys.exit(1)


def make_cron_line(slug, rule, workdir):
    drop_time = rule["drop_time_et"]
    h, m = drop_time.split(":")
    days_in_advance = rule["days_in_advance"]
    schedule = rule.get("schedule_dates", "daily")

    # dow: weekdays = 1-5, daily = *
    dow = "1-5" if schedule == "weekdays" else "*"

    # Use Python to compute both TARGET and DROP_TS — avoids BSD vs GNU date differences
    py_inline = (
        f"import sys,datetime,zoneinfo; "
        f"et=zoneinfo.ZoneInfo('America/New_York'); "
        f"now=datetime.datetime.now(et); "
        f"target=(now+datetime.timedelta(days={days_in_advance})).strftime('%Y-%m-%d'); "
        f"drop=now.replace(hour={int(h)},minute={int(m)},second=0,microsecond=0); "
        f"print(target,int(drop.timestamp()))"
    )
    cmd = (
        f"cd {workdir} && "
        f"read TARGET DROP_TS <<< $({PYTHON} -c \"{py_inline}\") && "
        f"{PYTHON} {SNIPER_SCRIPT} {slug} $TARGET $DROP_TS"
    )

    # Run at (drop_time - 1 minute) so sniper can sleep into position
    fire_m = int(m) - 1
    fire_h = int(h)
    if fire_m < 0:
        fire_m = 59
        fire_h -= 1

    return (
        f"{fire_m} {fire_h} * * {dow}  {cmd}  {CRON_MARKER}:{slug}"
    )


def main():
    with open("scheduled-drops.yaml") as f:
        config = yaml.safe_load(f)

    drops = config.get("drops", {})
    workdir = os.path.abspath(".")

    existing = read_crontab()
    # Strip all ResSniper-managed lines
    lines = [
        l for l in existing.splitlines() if CRON_MARKER not in l
    ]

    # Add self-update entry if not already present
    self_update_marker = "# ResSniper-self-update"
    if self_update_marker not in existing:
        lines.append(
            f"0 1 * * *  cd {workdir} && {PYTHON} {UPDATE_SCRIPT}  {self_update_marker}"
        )

    for slug, rule in drops.items():
        lines.append(make_cron_line(slug, rule, workdir))
        print(f"Scheduled: {slug} ({rule['drop_time_et']} ET, +{rule['days_in_advance']}d)")

    new_crontab = "\n".join(lines) + "\n"
    write_crontab(new_crontab)
    print("Crontab updated.")


if __name__ == "__main__":
    main()
