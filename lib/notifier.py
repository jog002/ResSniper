import subprocess
import sys
import urllib.request

LEVEL_LABEL = {
    "info": "INFO",
    "success": "BOOKED",
    "warn": "WARN",
    "error": "ERROR",
}

NTFY_PRIORITY = {
    "info": "3",
    "success": "4",
    "warn": "4",
    "error": "5",
}

NTFY_TAGS = {
    "info": "mag",
    "success": "white_check_mark",
    "warn": "warning",
    "error": "rotating_light",
}

_ntfy_config = None
_ntfy_loaded = False


def _get_ntfy_config():
    global _ntfy_config, _ntfy_loaded
    if _ntfy_loaded:
        return _ntfy_config
    _ntfy_loaded = True
    try:
        import yaml
        import os
        creds_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "credentials.yaml")
        with open(creds_path) as f:
            creds = yaml.safe_load(f) or {}
        _ntfy_config = creds.get("ntfy") or {}
    except Exception:
        _ntfy_config = {}
    return _ntfy_config


def _send_ntfy(title, message, level):
    cfg = _get_ntfy_config()
    topic = cfg.get("topic")
    if not topic:
        return
    server = cfg.get("server", "https://ntfy.sh").rstrip("/")
    url = f"{server}/{topic}"
    req = urllib.request.Request(url, data=message.encode(), method="POST")
    req.add_header("Title", title)
    req.add_header("Priority", NTFY_PRIORITY.get(level, "3"))
    req.add_header("Tags", NTFY_TAGS.get(level, "bell"))
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[notify] ntfy failed: {e}", file=sys.stderr)


def notify(title, message, level="info"):
    """Send a macOS system notification, ntfy push, and print to stdout."""
    label = LEVEL_LABEL.get(level, level.upper())
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

    _send_ntfy(title, message, level)
