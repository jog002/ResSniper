import subprocess
import sys

LEVEL_EMOJI = {
    "info": "INFO",
    "success": "BOOKED",
    "warn": "WARN",
    "error": "ERROR",
}


def notify(title, message, level="info"):
    """Send a macOS system notification and print to stdout."""
    label = LEVEL_EMOJI.get(level, level.upper())
    print(f"[{label}] {title}: {message}", flush=True)

    # Escape for AppleScript string literals: quotes and newlines
    def esc(s):
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " | ").replace("\r", "")

    script = (
        f'display notification "{esc(message)}" '
        f'with title "ResSniper" '
        f'subtitle "{esc(title)}"'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )
    except Exception as e:
        print(f"[notify] osascript failed: {e}", file=sys.stderr)
