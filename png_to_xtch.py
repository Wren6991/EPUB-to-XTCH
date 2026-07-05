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
# directly: 0=white, 1=dark grey, 2=light grey, 3=black. (NOT sorted.)
PALETTE_IMG = Image.new("P", (4, 1))
PALETTE_IMG.putpalette([255, 255, 255, 85, 85, 85, 170, 170, 170, 0, 0, 0])

# Bit extraction LUTs, to map palette-mode inputs to white or black depending
# if a given bit is set. Can then extract the packed bits by converting to
# 1bpp mode and calling .tobytes(). Note the output is *also* in paletted
# space, so white/black (final 1/0) are indices into the above palette:
IDX_BLACK = 3
IDX_WHITE = 0
LUT_BIT1 = bytes([IDX_WHITE if i & 0x2 else IDX_BLACK for i in range(256)])
LUT_BIT0 = bytes([IDX_WHITE if i & 0x1 else IDX_BLACK for i in range(256)])

XTCH_MARK = b"XTCH"
XTH_MARK = b"XTH\0"
XTCH_HEADER_SIZE = 56
METADATA_SIZE = 256
XTH_HEADER_SIZE = 22
INDEX_ENTRY_SIZE = 16

def page_to_xth(img):
    """Convert a PIL page image to a full XTH page (header + two bitplanes)."""
    img = img.quantize(palette=PALETTE_IMG, dither=Image.Dither.NONE)
    w, h = img.size
    assert h % 8 == 0, f"page height {h} is not a multiple of 8"
    # Rotate to match column-major output order:
    img = img.transpose(Image.Transpose.ROTATE_90)
    # Use LUTs to extract bit planes, then convert to 1bpp to pack the bits:
    plane1_bytes = img.point(LUT_BIT1).convert("1", dither=Image.Dither.NONE).tobytes()
    plane0_bytes = img.point(LUT_BIT0).convert("1", dither=Image.Dither.NONE).tobytes()
    data_size = len(plane1_bytes) + len(plane0_bytes)
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
    return header + plane1_bytes + plane0_bytes, w, h

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
