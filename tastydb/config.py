"""Runtime configuration, sourced from environment variables (optionally
seeded from a .env file in the working directory).

Credentials come from, in order: TT_CLIENT_SECRET / TT_REFRESH_TOKEN in the
environment (or .env), then the OS keyring (Windows Credential Manager) under the
same entry cherrypick uses -- service "cherrypick-broker", entries
"production:client_secret" and "production:refresh_token". The keyring is only
consulted for prod (those are production tokens) and can be turned off with
TASTYDB_KEYRING=off. Create the tokens at my.tastytrade.com -> Manage -> My Profile
-> API -> OAuth Applications (see README):

    TT_CLIENT_SECRET   OAuth application client secret
    TT_REFRESH_TOKEN   refresh token from a personal grant
    TT_CLIENT_ID       optional; sent along if set
    TT_ENV             "prod" (default) or "sandbox"

Other settings:

    TASTYDB_DB_URL        SQLAlchemy URL. Default depends on TT_ENV so the two
                          environments never share a database:
                          sqlite:///tastydb.sqlite3 (prod),
                          sqlite:///tastydb-sandbox.sqlite3 (sandbox).
    TASTYDB_MATCH_METHOD  "fifo" (default) or "lifo"
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

PROD_BASE_URL = "https://api.tastyworks.com"
SANDBOX_BASE_URL = "https://api.cert.tastyworks.com"

PROD_DEFAULT_DB_URL = "sqlite:///tastydb.sqlite3"
SANDBOX_DEFAULT_DB_URL = "sqlite:///tastydb-sandbox.sqlite3"

# Shared with cherrypick, so one broker login serves both tools.
KEYRING_SERVICE = "cherrypick-broker"
KEYRING_ENTRY_PREFIX = "production"

log = logging.getLogger(__name__)

USER_AGENT = "tasty-db/0.1"  # tastytrade rejects requests without a User-Agent


def load_dotenv(path: str | Path = ".env") -> dict[str, str]:
    """Load KEY=VALUE lines from a .env file into os.environ.

    Real environment variables win: a key already present in the environment
    is never overridden. Supports blank lines, `#` comments, an optional
    `export ` prefix, and single/double quotes around the value. Returns the
    keys actually applied.
    """
    path = Path(path)
    applied: dict[str, str] = {}
    if not path.is_file():
        return applied
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied


def keyring_secret(name: str) -> str | None:
    """Read `name` from the OS keyring; None if absent, disabled, or unreadable."""
    if os.environ.get("TASTYDB_KEYRING", "").lower() in ("off", "0", "false", "no"):
        return None
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, f"{KEYRING_ENTRY_PREFIX}:{name}")
    except Exception as exc:  # noqa: BLE001 - no backend / locked vault: fall back to env only
        log.debug("keyring read failed for %s: %s", name, exc)
        return None


@dataclass
class Config:
    # None means "use the per-environment default" — resolved lazily by
    # resolved_db_url so a later `--sandbox` override still picks the right file.
    db_url: str | None = field(default_factory=lambda: os.environ.get("TASTYDB_DB_URL"))
    client_id: str | None = field(default_factory=lambda: os.environ.get("TT_CLIENT_ID"))
    client_secret: str | None = field(default_factory=lambda: os.environ.get("TT_CLIENT_SECRET"))
    refresh_token: str | None = field(default_factory=lambda: os.environ.get("TT_REFRESH_TOKEN"))
    env: str = field(default_factory=lambda: os.environ.get("TT_ENV", "prod"))
    match_method: str = field(
        default_factory=lambda: os.environ.get("TASTYDB_MATCH_METHOD", "fifo").lower()
    )
    # Don't auto-expire lots until this many days past expiration, so a late-posting
    # settlement/assignment transaction can still claim them.
    expiration_grace_days: int = 4
    _keyring_tried: bool = field(default=False, repr=False)

    @property
    def base_url(self) -> str:
        return SANDBOX_BASE_URL if self.env == "sandbox" else PROD_BASE_URL

    @property
    def resolved_db_url(self) -> str:
        """Explicit --db/TASTYDB_DB_URL wins; otherwise each environment gets
        its own database so sandbox testing never touches prod data."""
        if self.db_url:
            return self.db_url
        return SANDBOX_DEFAULT_DB_URL if self.env == "sandbox" else PROD_DEFAULT_DB_URL

    def load_keyring_credentials(self) -> None:
        """Fill any missing secret from the keyring (prod only; env values win).
        Done lazily, once, so --sandbox is known and offline commands never touch it."""
        if self._keyring_tried or self.env == "sandbox":
            return
        self._keyring_tried = True
        if not self.client_secret:
            self.client_secret = keyring_secret("client_secret")
        if not self.refresh_token:
            self.refresh_token = keyring_secret("refresh_token")

    @property
    def has_credentials(self) -> bool:
        self.load_keyring_credentials()
        return bool(self.client_secret and self.refresh_token)
