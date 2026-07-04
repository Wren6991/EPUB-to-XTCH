# EPUB to XTCH Conversion

This repository contains tools for converting EPUBs to statically rendered [XTCH](https://gist.github.com/bdeshi/f605499fa5eaf6f69cf288c258dfafb4) image archives, for reading on low-cost e-reader devices like XTEINK X4.

These devices have to make compromises on their CJK font rendering due to limited device RAM and processing power. However they have generous storage capacity (SD card), so pre-rendering the EPUB is a viable workaround.

## Tools

There are two tools in this repository:

[epub_to_png.py](epub_to_png.py):

* Reads a standard EPUB.
* Injects some CSS overrides to force font size and margins, and undo some publisher styling that doesn't work well on small displays.
* Scales and pre-dithers images to 2bpp (so that we *don't* have to dither the anti-aliased text later, which would look awful).
* Paginates the document and renders to PNGs, starting from `page_0000.png` to the specified output directory.
* If the EPUB has author/title metadata, write these values to `author.txt` and `title.txt` in the specified output directory.

[png_to_xtch.py](png_to_xtch.py):

* Reads such a directory of PNGs.
* Packs them into an XTCH image archive.

The two tools are separated because the EPUB-to-PNG flow is useful for other e-reader devices, but the XTCH format is somewhat specific to XTEINK devices.

## Usage

First, install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pymupdf pillow
```

Convert an EPUB:

```
./epub_to_png.py my_book.epub --output output
```

Creates a directory called `output/` containing rendered PNGs and `author.txt`/`title.txt` info files. Run `./epub_to_png.py --help` for more information on advanced options.
