#!/usr/bin/env python3

HELP = """Extract an XTCH archive into a directory of PNGs (one per page),
reversing what png_to_xtch.py produces. Useful for verifying conversions
and inspecting output without a device.
"""

import argparse
import struct
import sys
from pathlib import Path
from PIL import Image

XTCH_HEADER_SIZE = 56
METADATA_SIZE = 256
XTH_HEADER_SIZE = 22
INDEX_ENTRY_SIZE = 16

# Reverse of the palette used in png_to_xtch.py: device value 0=white,
# 1=dark grey, 2=light grey, 3=black.
PALETTE = [255, 255, 255, 85, 85, 85, 170, 170, 170, 0, 0, 0]


def unpack_plane(plane_bytes, w, h):
    """Reverse pack_plane: column-major bytes (right-to-left, 8 vertical
    pixels per byte, MSB = topmost) -> row-major bytearray of 0/1, length w*h.
    h must be a multiple of 8."""
    assert h % 8 == 0, "height must be a multiple of 8"
    out = bytearray(w * h)
    row_stride = w
    oi = 0
    for x in range(w - 1, -1, -1):
        for yg in range(0, h, 8):
            b = plane_bytes[oi]
            oi += 1
            row = x + yg * row_stride
            out[row]                     = (b >> 7) & 1
            out[row +     row_stride]    = (b >> 6) & 1
            out[row + 2 * row_stride]    = (b >> 5) & 1
            out[row + 3 * row_stride]    = (b >> 4) & 1
            out[row + 4 * row_stride]    = (b >> 3) & 1
            out[row + 5 * row_stride]    = (b >> 2) & 1
            out[row + 6 * row_stride]    = (b >> 1) & 1
            out[row + 7 * row_stride]    =  b       & 1
    return out


def xth_to_image(xth_bytes):
    """Parse one XTH page (header + two bitplanes) and return a PIL image."""
    mk, w, h, cm, comp, ds, md5 = struct.unpack("<4sHHBBIQ", xth_bytes[:XTH_HEADER_SIZE])
    if mk != b"XTH\0":
        sys.exit(f"bad XTH mark: {mk!r}")
    if comp != 0:
        sys.exit("compression not supported")
    plane_size = w * (h // 8)
    if ds != plane_size * 2:
        sys.exit(f"dataSize {ds} != expected {plane_size * 2}")
    plane1 = xth_bytes[XTH_HEADER_SIZE:XTH_HEADER_SIZE + plane_size]
    plane2 = xth_bytes[XTH_HEADER_SIZE + plane_size:XTH_HEADER_SIZE + 2 * plane_size]
    bit1 = unpack_plane(plane1, w, h)  # bit 1 of device value
    bit2 = unpack_plane(plane2, w, h)  # bit 0 of device value
    # device value = (bit1 << 1) | bit2; equals palette index
    out = bytearray(w * h)
    for i in range(w * h):
        out[i] = (bit1[i] << 1) | bit2[i]
    img = Image.frombytes("P", (w, h), bytes(out))
    img.putpalette(PALETTE)
    return img


def main():
    parser = argparse.ArgumentParser(description=HELP, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("input_xtch", help="Path to the XTCH archive")
    parser.add_argument("-o", "--output", default="extracted", help="Output directory (default extracted/)")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.input_xtch, "rb") as f:
        header = f.read(XTCH_HEADER_SIZE)
        if header[:4] != b"XTCH":
            sys.exit(f"Not an XTCH file (mark={header[:4]!r})")
        (mark, ver, page_count, read_dir, has_meta, has_thumb, has_chap,
         cur_page, meta_off, index_off, data_off, thumb_off, chap_off) = struct.unpack(
            "<4sHHBBBBIQQQQQ", header)
        print(f"{page_count} pages, version {hex(ver)}, readDir {read_dir}")

        if has_meta:
            f.seek(meta_off)
            meta = f.read(METADATA_SIZE)
            title = meta[:128].split(b"\x00")[0].decode("utf-8", errors="replace")
            author = meta[0x80:0xC0].split(b"\x00")[0].decode("utf-8", errors="replace")
            if title:
                print(f"title:  {title}")
            if author:
                print(f"author: {author}")
            (out_dir / "title.txt").write_text(title)
            (out_dir / "author.txt").write_text(author)

        # Page index table
        f.seek(index_off)
        index_entries = []
        for _ in range(page_count):
            e = f.read(INDEX_ENTRY_SIZE)
            off, size, w, h = struct.unpack("<QIHH", e)
            index_entries.append((off, size, w, h))

        for i, (off, size, w, h) in enumerate(index_entries):
            f.seek(off)
            xth = f.read(size)
            img = xth_to_image(xth)
            out_path = out_dir / f"page_{i:04d}.png"
            img.save(str(out_path))
            if (i + 1) % 50 == 0 or i + 1 == page_count:
                print(f"  page {i + 1}/{page_count}")

    print(f"Wrote {page_count} pages to {out_dir}/")


if __name__ == "__main__":
    main()
