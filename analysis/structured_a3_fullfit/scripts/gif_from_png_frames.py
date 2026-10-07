#!/usr/bin/env python3
"""Dependency-free PNG (RGB/RGBA, 8-bit, non-interlaced) to animated GIF encoder."""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path


def read_png(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    offset = 8
    width = height = bit_depth = color_type = interlace = None
    payload = bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", body)
            if bit_depth != 8 or compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("only 8-bit, non-interlaced PNGs are supported")
        elif kind == b"IDAT":
            payload.extend(body)
        elif kind == b"IEND":
            break
    if width is None or height is None:
        raise ValueError(f"PNG header missing: {path}")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ValueError(f"unsupported PNG color type: {color_type}")
    raw = zlib.decompress(bytes(payload))
    row_bytes = width * channels
    rows: list[bytes] = []
    previous = bytearray(row_bytes)
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        current = bytearray(raw[position : position + row_bytes])
        position += row_bytes
        for index in range(row_bytes):
            left = current[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                current[index] = (current[index] + left) & 255
            elif filter_type == 2:
                current[index] = (current[index] + up) & 255
            elif filter_type == 3:
                current[index] = (current[index] + ((left + up) // 2)) & 255
            elif filter_type == 4:
                estimate = left + up - upper_left
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
                predictor = (left, up, upper_left)[distances.index(min(distances))]
                current[index] = (current[index] + predictor) & 255
            elif filter_type != 0:
                raise ValueError(f"unsupported PNG row filter: {filter_type}")
        rows.append(bytes(current))
        previous = current
    rgb = bytearray(width * height * 3)
    out = 0
    for row in rows:
        for index in range(0, len(row), channels):
            rgb[out : out + 3] = row[index : index + 3] if channels >= 3 else bytes((row[index],) * 3)
            out += 3
    return width, height, bytes(rgb)


def palette() -> list[tuple[int, int, int]]:
    # Fixed inferno-like sequential palette plus neutral colors for the map frame.
    stops = [(0, 0, 4), (31, 12, 72), (85, 15, 109), (136, 34, 106), (186, 54, 85), (227, 89, 51), (249, 140, 10), (252, 255, 164)]
    colors: list[tuple[int, int, int]] = []
    for index in range(240):
        position = index / 239 * (len(stops) - 1)
        left = min(int(position), len(stops) - 2)
        fraction = position - left
        a, b = stops[left], stops[left + 1]
        colors.append(tuple(round(a[channel] + fraction * (b[channel] - a[channel])) for channel in range(3)))
    colors.extend((value, value, value) for value in range(0, 256, 16))
    return colors[:256]


def build_lookup(colors: list[tuple[int, int, int]]) -> list[int]:
    lookup = []
    for red in range(0, 256, 8):
        for green in range(0, 256, 8):
            for blue in range(0, 256, 8):
                lookup.append(min(range(len(colors)), key=lambda i: (colors[i][0] - red) ** 2 + (colors[i][1] - green) ** 2 + (colors[i][2] - blue) ** 2))
    return lookup


def quantize(rgb: bytes, lookup: list[int]) -> bytes:
    result = bytearray(len(rgb) // 3)
    for index in range(len(result)):
        red, green, blue = rgb[index * 3 : index * 3 + 3]
        result[index] = lookup[(red // 8) * 1024 + (green // 8) * 32 + blue // 8]
    return bytes(result)


def lzw_codes(indices: bytes) -> bytes:
    """Encode one GIF image with decoder-synchronized variable-width codes.

    The previous implementation increased the code width immediately after
    adding a dictionary entry. GIF decoders add that entry one code later, so
    the old stream became invalid at width boundaries. The width below is
    selected from the decoder-visible dictionary state (``next_code - 1``),
    keeping every emitted code synchronized with the GIF specification.
    """
    minimum = 8
    clear = 1 << minimum
    end = clear + 1
    next_code = end + 1
    dictionary = {bytes((value,)): value for value in range(clear)}

    def code_size() -> int:
        size = minimum + 1
        while size < 12 and next_code - 1 >= (1 << size):
            size += 1
        return size

    output = bytearray()
    accumulator = 0
    bits = 0

    def write(code: int, size: int) -> None:
        nonlocal accumulator, bits
        accumulator |= code << bits
        bits += size
        while bits >= 8:
            output.append(accumulator & 255)
            accumulator >>= 8
            bits -= 8

    write(clear, minimum + 1)
    if not indices:
        write(end, minimum + 1)
        if bits:
            output.append(accumulator & 255)
        return bytes(output)

    prefix = bytes((indices[0],))
    for value in indices[1:]:
        candidate = prefix + bytes((value,))
        if candidate in dictionary:
            prefix = candidate
            continue

        write(dictionary[prefix], code_size())
        if next_code < 4096:
            dictionary[candidate] = next_code
            next_code += 1
        else:
            write(clear, code_size())
            dictionary = {bytes((value,)): value for value in range(clear)}
            next_code = end + 1
        prefix = bytes((value,))

    write(dictionary[prefix], code_size())
    write(end, code_size())
    if bits:
        output.append(accumulator & 255)
    return bytes(output)


def subblocks(payload: bytes) -> bytes:
    chunks = [payload[index : index + 255] for index in range(0, len(payload), 255)]
    return b"".join(bytes((len(chunk),)) + chunk for chunk in chunks) + b"\x00"


def write_gif(frames: list[tuple[int, int, bytes]], output: Path, fps: float) -> None:
    colors = palette()
    lookup = build_lookup(colors)
    width, height = frames[0][0], frames[0][1]
    if any((frame[0], frame[1]) != (width, height) for frame in frames):
        raise ValueError("all animation frames must have identical dimensions")
    header = bytearray(b"GIF89a")
    header.extend(struct.pack("<HH", width, height))
    header.extend(b"\xf7\x00\x00")  # global table, 8-bit color resolution, 256 entries
    header.extend(bytes(channel for color in colors for channel in color))
    header.extend(b"!\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00")
    delay = max(1, round(100 / fps))
    for frame_width, frame_height, rgb in frames:
        header.extend(b"!\xf9\x04\x00" + struct.pack("<H", delay) + b"\x00\x00")
        header.extend(b"," + struct.pack("<HHHH", 0, 0, frame_width, frame_height) + b"\x00")
        header.extend(bytes((8,)))
        header.extend(subblocks(lzw_codes(quantize(rgb, lookup))))
    header.extend(b";")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(bytes(header))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fps", required=True, type=float)
    args = parser.parse_args()
    paths = sorted(args.frames.glob("frame_*.png"))
    if not paths:
        raise SystemExit("no PNG frames found")
    frames = [read_png(path) for path in paths]
    write_gif(frames, args.output, args.fps)
    print(f"GIF COMPLETE frames={len(frames)} width={frames[0][0]} height={frames[0][1]} output={args.output}")


if __name__ == "__main__":
    main()
