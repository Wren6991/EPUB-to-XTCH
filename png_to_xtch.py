#!/usr/bin/env python3

HELP = """Pack a directory of rendered page PNGs (as produced by epub_to_png.py)
into an XTCH image archive for XTEINK-style e-readers.

Pages are packed as 2bpp grayscale XTH images (no dithering) and written
incrementally to the output file.
"""

import argparse
import struct
import sys
import time
from pathlib import Path
from PIL import Image

# Palette ordered so that the palette index equals the device pixel value
# directly: 0=white, 1=dark grey, 2=light grey, 3=black.
PALETTE_IMG = Image.new("P", (4, 1))
PALETTE_IMG.putpalette([255, 255, 255, 85, 85, 85, 170, 170, 170, 0, 0, 0])

XTCH_MARK = b"XTCH"
XTH_MARK = b"XTH\0"
XTCH_HEADER_SIZE = 56
METADATA_SIZE = 256
XTH_HEADER_SIZE = 22
INDEX_ENTRY_SIZE = 16


def pack_plane(plane_bits, w, h):
    """Pack one bitplane (a bytearray of length w*h, row-major, values 0/1)
    into column-major bytes: columns right-to-left, 8 vertical pixels per
    byte, MSB = topmost pixel. h must be a multiple of 8."""
    assert h % 8 == 0, "height must be a multiple of 8"
    out = bytearray(w * (h // 8))
    row_stride = w
    oi = 0
    # Columns from right (x = w-1) to left (x = 0)
    for x in range(w - 1, -1, -1):
        for yg in range(0, h, 8):
            row = x + yg * row_stride
            b = 0
            if plane_bits[row]:
                b |= 0x80
            if plane_bits[row + row_stride]:
                b |= 0x40
            if plane_bits[row + 2 * row_stride]:
                b |= 0x20
            if plane_bits[row + 3 * row_stride]:
                b |= 0x10
            if plane_bits[row + 4 * row_stride]:
                b |= 0x08
            if plane_bits[row + 5 * row_stride]:
                b |= 0x04
            if plane_bits[row + 6 * row_stride]:
                b |= 0x02
            if plane_bits[row + 7 * row_stride]:
                b |= 0x01
            out[oi] = b
            oi += 1
    return out


def page_to_xth(img):
    """Convert a PIL page image to a full XTH page (header + two bitplanes)."""
    q = img.quantize(palette=PALETTE_IMG, dither=Image.Dither.NONE)
    w, h = q.size
    assert h % 8 == 0, f"page height {h} is not a multiple of 8"
    data = q.tobytes()  # row-major palette indices 0-3
    plane1 = bytearray(len(data))  # bit 1 of device value
    plane2 = bytearray(len(data))  # bit 0 of device value
    for i, v in enumerate(data):
        plane1[i] = (v >> 1) & 1
        plane2[i] = v & 1
    plane1_bytes = pack_plane(plane1, w, h)
    plane2_bytes = pack_plane(plane2, w, h)
    data_size = len(plane1_bytes) + len(plane2_bytes)
    header = struct.pack(
        "<4sHHBBIQ",
        XTH_MARK,
        w,
        h,
        0,  # colorMode
        0,  # compression
        data_size,
        0,  # md5 (first 8 bytes, zero)
    )
    return header + plane1_bytes + plane2_bytes, w, h


def find_pages(in_dir):
    pages = sorted(in_dir.glob("page_*.png"))
    if not pages:
        sys.exit(f"No page_*.png files found in {in_dir}")
    return pages


def main():
    parser = argparse.ArgumentParser(description=HELP, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("input_dir", help="Directory containing page_*.png, author.txt, title.txt")
    parser.add_argument("-o", "--output", help="Output XTCH file (default (input_dir).xtch)")
    args = parser.parse_args()

    in_dir = Path(args.input_dir)
    output = args.output if args.output is not None else f"{in_dir.resolve()}.xtch"

    pages = find_pages(in_dir)

    # Determine page dimensions from first page; assert all match.
    first = Image.open(pages[0])
    width, height = first.size
    print(f"Page dimensions: {width}x{height}, {len(pages)} pages")

    title = ""
    author = ""
    title_path = in_dir / "title.txt"
    author_path = in_dir / "author.txt"
    if title_path.exists():
        title = title_path.read_text().strip()
    if author_path.exists():
        author = author_path.read_text().strip()

    data_offset = XTCH_HEADER_SIZE + METADATA_SIZE
    index_offset_placeholder = 0  # patched at end

    with open(output, "wb") as f:
        # XTCH header (56 bytes), indexOffset patched later
        header = struct.pack(
            "<4sHHBBBBIQQQQQ",
            XTCH_MARK,
            0x0100,            # version
            len(pages),        # pageCount
            0,                 # readDirection (L->R)
            1,                 # hasMetadata
            0,                 # hasThumbnails
            0,                 # hasChapters
            0,                 # currentPage
            XTCH_HEADER_SIZE,  # metadataOffset
            0,                 # indexOffset (placeholder)
            data_offset,       # dataOffset
            0,                 # thumbOffset
            0,                 # chapterOffset
        )
        assert len(header) == XTCH_HEADER_SIZE
        f.write(header)

        # Metadata (256 bytes)
        meta = bytearray(METADATA_SIZE)
        def put_string(off, field_len, s):
            b = s.encode("utf-8")[:field_len - 1]
            meta[off:off + len(b)] = b
        put_string(0x00, 128, title)
        put_string(0x80, 64, author)
        # publisher (64) and language (32) left zero
        struct.pack_into("<I", meta, 0xF0, int(time.time()))
        struct.pack_into("<H", meta, 0xF4, 0xFFFF)  # coverPage = none
        struct.pack_into("<H", meta, 0xF6, 0)       # chapterCount
        f.write(meta)

        # Stream pages
        index_entries = []
        offset = data_offset
        for i, page_path in enumerate(pages):
            img = Image.open(page_path)
            if img.size != (width, height):
                sys.exit(f"Page {page_path} has size {img.size}, expected {(width, height)}")
            xth, w, h = page_to_xth(img)
            f.write(xth)
            index_entries.append((offset, len(xth), w, h))
            offset += len(xth)
            if (i + 1) % 50 == 0 or i + 1 == len(pages):
                print(f"  page {i + 1}/{len(pages)}")

        # Page index table
        index_offset = f.tell()
        for off, size, w, h in index_entries:
            f.write(struct.pack("<QIHH", off, size, w, h))

        # Patch indexOffset in header
        f.seek(0x18)
        f.write(struct.pack("<Q", index_offset))

    print(f"Wrote {output} ({offset + len(index_entries) * INDEX_ENTRY_SIZE} bytes)")


if __name__ == "__main__":
    main()
