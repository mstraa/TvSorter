from __future__ import annotations


def human_file_size(size: int | None) -> str:
    if size is None:
        return ""
    if size < 0:
        size = 0
    units = ["o", "Ko", "Mo", "Go", "To"]
    value = float(size)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    decimals = 0 if unit_index <= 2 else 2
    formatted = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return f"{formatted.replace('.', ',')} {units[unit_index]}"
