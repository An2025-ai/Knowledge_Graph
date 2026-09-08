"""Thread-safe runtime settings snapshots shared by application services."""

from __future__ import annotations

from threading import RLock

from .config import AppPaths, RuntimeSettings, persist_settings


class SettingsStore:
    """Own the single mutable settings boundary for one application instance.

    ``RuntimeSettings`` is immutable, so readers always receive a coherent
    snapshot. A replacement is persisted before the in-memory reference is
    swapped, which keeps memory and disk aligned when persistence fails.
    """

    def __init__(self, settings: RuntimeSettings, paths: AppPaths | None = None):
        self.paths = paths
        self._settings = settings
        self._lock = RLock()

    def snapshot(self) -> RuntimeSettings:
        with self._lock:
            return self._settings

    def replace(self, settings: RuntimeSettings) -> RuntimeSettings:
        with self._lock:
            if self.paths is not None:
                persist_settings(self.paths, settings)
            self._settings = settings
            return settings
