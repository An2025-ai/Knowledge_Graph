"""Create the small generated ICO used by the Windows Tauri resource step."""

from __future__ import annotations

import struct
from pathlib import Path


def make_icon(size: int = 32) -> bytes:
    pixels = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            # Deep navy tile with a compact gold A mark.
            inside_a = (x == 8 + y // 4 or x == 23 - y // 4) and 4 <= y <= 26
            crossbar = 9 <= y <= 12 and 10 <= x <= 21
            if inside_a or crossbar:
                pixels.extend((98, 198, 181, 255))
            else:
                pixels.extend((28, 35, 50, 255))

    mask = bytes(size * ((size + 31) // 32 * 4))
    dib = struct.pack(
        "<IiiHHIIiiII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        len(pixels),
        0,
        0,
        0,
        0,
    )
    image = dib + pixels + mask
    directory = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(image), 6 + 16)
    return directory + entry + image


repo = Path(__file__).resolve().parents[2]
output = repo / "desktop" / "src-tauri" / "icons" / "icon.ico"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(make_icon())
print(f"Generated {output}")
