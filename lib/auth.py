import os
import stat
import yaml


CREDENTIALS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "credentials.yaml")


def load_credentials(path=CREDENTIALS_PATH):
    """Load Resy credentials for backward compat. Returns flat dict with api_key/auth_token/payment_id.
    Accepts both old flat format and new nested-by-provider format."""
    return load_provider_credentials("resy", path=path)


def load_provider_credentials(provider: str, path=CREDENTIALS_PATH) -> dict:
    """Load credentials for a specific provider from credentials.yaml.
    Supports both flat format (resy only, legacy) and nested-by-provider format."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"credentials.yaml not found at {path}. "
            "Copy credentials.yaml.example, fill in your tokens, and chmod 600 it."
        )
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    _warn_if_insecure(path)

    # Nested format: top-level keys are provider names
    if provider in raw and isinstance(raw[provider], dict):
        creds = raw[provider]
    elif provider == "resy" and "auth_token" in raw:
        # Old flat format — all Resy keys are at the top level
        creds = raw
    else:
        return {}

    if provider == "resy":
        required = ["api_key", "auth_token", "payment_id"]
        missing = [k for k in required if not creds.get(k)]
        if missing:
            raise ValueError(f"credentials.yaml is missing required keys for resy: {missing}")

    return creds


def save_credentials(creds, path=CREDENTIALS_PATH):
    """Write Resy credentials back to disk (backward compat wrapper)."""
    save_provider_credentials("resy", creds, path=path)


def save_provider_credentials(provider: str, new_creds: dict, path=CREDENTIALS_PATH):
    """Write credentials for a specific provider, preserving other providers."""
    existing = {}
    if os.path.exists(path):
        with open(path) as f:
            existing = yaml.safe_load(f) or {}
    # Upgrade flat format to nested on first write
    if "auth_token" in existing and "resy" not in existing:
        flat = {k: existing.pop(k) for k in list(existing.keys())}
        existing["resy"] = flat
    existing[provider] = new_creds
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        yaml.dump(existing, f, default_flow_style=False)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


def _warn_if_insecure(path):
    mode = os.stat(path).st_mode & 0o777
    if mode & 0o077:
        print(
            f"[auth] WARNING: {path} is world/group readable (mode {oct(mode)}). "
            "Run: chmod 600 credentials.yaml"
        )
