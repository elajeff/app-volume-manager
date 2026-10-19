"""Small, validated color conversion helpers used by the slider color picker."""

import colorsys

def normalize_hex_color(value: str) -> str:
    """Return a normalized #RRGGBB color or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("Enter a six-digit HEX color such as #1677FF.")
    candidate = value.strip()
    if candidate.startswith("#"):
        candidate = candidate[1:]
    if len(candidate) != 6 or any(
        character not in "0123456789abcdefABCDEF" for character in candidate
    ):
        raise ValueError("Enter a six-digit HEX color such as #1677FF.")
    return f"#{candidate.upper()}"


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    color = normalize_hex_color(value)
    return tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))


def rgb_to_hex(red: int, green: int, blue: int) -> str:
    values = (red, green, blue)
    if any(not isinstance(value, int) or not 0 <= value <= 255 for value in values):
        raise ValueError("RGB values must each be whole numbers from 0 to 255.")
    return f"#{red:02X}{green:02X}{blue:02X}"


def hsv_to_hex(hue: float, saturation: float, value: float) -> str:
    red, green, blue = colorsys.hsv_to_rgb(hue % 1.0, saturation, value)
    return rgb_to_hex(round(red * 255), round(green * 255), round(blue * 255))
