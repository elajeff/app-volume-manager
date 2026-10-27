"""Validated volume rules for an app or a repeatable process role."""

from dataclasses import dataclass


def normalize_executable_name(value: str) -> str:
    """Return a Windows executable basename, accepting a full path as input."""
    if not isinstance(value, str):
        raise ValueError("Enter an executable name, such as Discord.exe.")

    name = value.strip().replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."}:
        raise ValueError("Enter an executable name, such as Discord.exe.")
    if any(ord(character) < 32 for character in name):
        raise ValueError("The executable name contains invalid characters.")

    if not name.lower().endswith(".exe"):
        name += ".exe"
    return name


@dataclass(frozen=True)
class AppRule:
    executable: str
    volume: int
    enabled: bool = True
    process_signature: str | None = None
    process_role: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "executable", normalize_executable_name(self.executable))
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise ValueError("Volume must be a whole number from 0 to 100.")
        if not 0 <= self.volume <= 100:
            raise ValueError("Volume must be between 0 and 100.")
        if not isinstance(self.enabled, bool):
            raise ValueError("Enabled must be true or false.")
        signature = self.process_signature
        if signature is not None:
            if not isinstance(signature, str) or not signature.strip():
                raise ValueError("Process-specific rules require a valid process signature.")
            object.__setattr__(self, "process_signature", signature.strip().casefold())
            if self.process_role is not None and not isinstance(self.process_role, str):
                raise ValueError("Process role must be text.")

    @property
    def key(self) -> str:
        if self.process_signature:
            return f"process:{self.executable.casefold()}:{self.process_signature}"
        return self.executable.casefold()

    @property
    def is_process_specific(self) -> bool:
        return self.process_signature is not None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "executable": self.executable,
            "volume": self.volume,
            "enabled": self.enabled,
        }
        if self.process_signature is not None:
            data["process_signature"] = self.process_signature
            data["process_role"] = self.process_role or "Process role"
        return data

    @classmethod
    def from_dict(cls, data: object) -> "AppRule":
        if not isinstance(data, dict):
            raise ValueError("Each saved rule must be an object.")
        signature = data.get("process_signature")
        role = data.get("process_role")
        return cls(
            executable=data.get("executable", ""),
            volume=data.get("volume", -1),
            enabled=data.get("enabled", True),
            process_signature=signature,
            process_role=role,
        )


def resolve_rule(
    executable: str, signature: str | None,
    app_rules: dict[str, AppRule], process_rules: dict[str, AppRule],
) -> AppRule | None:
    """Use an enabled profile or app rule; retain a disabled rule for display."""
    profile = process_rules.get(signature) if signature else None
    app_rule = app_rules.get(executable.casefold())
    if profile is not None and profile.enabled:
        return profile
    if app_rule is not None and app_rule.enabled:
        return app_rule
    return profile or app_rule
