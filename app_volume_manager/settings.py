"""Load and save the user's small JSON settings file."""

import json
import os
import tempfile
from pathlib import Path

from app_volume_manager.rules import AppRule


class SettingsError(Exception):
    """Raised when a saved settings file cannot be read or written safely."""


def _write_json_atomically(path: Path, data: dict, label: str) -> None:
    """Write JSON via a temporary file so interruptions don't leave partial settings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", delete=False,
            dir=path.parent, prefix=f"{label}-", suffix=".tmp"
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise SettingsError(f"Could not save settings to {path}: {exc}") from exc


def default_settings_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / "AppData" / "Local"
    return base / "AppVolumeManager" / "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_settings_path()

    def load_rules(self) -> list[AppRule]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ValueError("Unsupported settings format.")
            raw_rules = data.get("rules")
            if not isinstance(raw_rules, list):
                raise ValueError("The saved rules list is missing.")
            rules: list[AppRule] = []
            seen: set[str] = set()
            for item in raw_rules:
                rule = AppRule.from_dict(item)
                if rule.key in seen:
                    raise ValueError(f"Duplicate rule for {rule.executable}.")
                rules.append(rule)
                seen.add(rule.key)
            return rules
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise SettingsError(
                f"Could not read settings file:\n{self.path}\n\n"
                f"The original file was left untouched. Details: {exc}"
            ) from exc

    def save_rules(self, rules: list[AppRule]) -> None:
        data = {
            "version": 1,
            "rules": [rule.to_dict() for rule in rules],
        }
        _write_json_atomically(self.path, data, "settings")


class PreferenceStore:
    """Persist small UI preferences independently from volume rules."""

    THEMES = {"light", "dark"}
    DEFAULT_SLIDER_THUMB_COLOR = "#1677FF"

    def __init__(self, path: Path | None = None) -> None:
        default_path = default_settings_path().with_name("preferences.json")
        self.path = Path(path) if path is not None else default_path

    @staticmethod
    def _valid_color(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 7
            and value.startswith("#")
            and all(character in "0123456789abcdefABCDEF" for character in value[1:])
        )

    def _read_preferences(self) -> dict:
        if not self.path.exists():
            return {
                "version": 1,
                "theme": "light",
                "slider_thumb_color": self.DEFAULT_SLIDER_THUMB_COLOR,
            }
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ValueError("Unsupported preferences format.")
            if data.get("theme") not in self.THEMES:
                raise ValueError("Theme must be 'light' or 'dark'.")
            # Migrate the former preference key on the next save. It remains
            # readable so existing installations keep their chosen color.
            color = data.get(
                "slider_thumb_color",
                data.get("knob_color", self.DEFAULT_SLIDER_THUMB_COLOR),
            )
            if not self._valid_color(color):
                raise ValueError("Slider color must be a six-digit HEX color such as #1677FF.")
            # Remove the legacy key so writes migrate to one canonical field.
            normalized = {
                key: value for key, value in data.items()
                if key not in {"knob_color", "slider_thumb_color"}
            }
            return {**normalized, "slider_thumb_color": color.upper()}
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise SettingsError(
                f"Could not read preferences file:\n{self.path}\n\n"
                f"The original file was left untouched. Details: {exc}"
            ) from exc

    def load_preferences(self) -> tuple[str, str]:
        """Return the saved theme and slider color, with migration for older installs."""
        data = self._read_preferences()
        return data["theme"], data["slider_thumb_color"]

    def load_theme(self) -> str:
        """Load the saved appearance theme."""
        return self.load_preferences()[0]

    def load_slider_thumb_color(self) -> str:
        """Load the saved slider color."""
        return self.load_preferences()[1]

    def save_theme(self, theme: str) -> None:
        if not isinstance(theme, str) or theme.casefold() not in self.THEMES:
            raise SettingsError("Theme must be 'light' or 'dark'.")
        data = self._read_preferences()
        data["theme"] = theme.casefold()
        _write_json_atomically(self.path, data, "preferences")

    def save_slider_thumb_color(self, color: str) -> None:
        if not self._valid_color(color):
            raise SettingsError("Slider color must be a six-digit HEX color such as #1677FF.")
        data = self._read_preferences()
        data["slider_thumb_color"] = color.upper()
        _write_json_atomically(self.path, data, "preferences")

