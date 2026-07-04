# EPUB to XTCH Conversion

This repository contains tools for converting EPUBs to statically rendered [XTCH](reference/XTC-XTG-XTH-XTCH.md) image archives, for reading on low-cost e-reader devices like XTEINK X4.

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

`epub_to_png.py` currently uses PyMuPDF for rendering, but this is unfortunately a dead end: custom font injection and 縦書き both impossible from Python bindings, and ruby text is essentially unsupported (there are some CSS hacks to improve it). It will likely move to headless browser rendering in the future.

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

## XTCH Format

An XTCH file is a container format with:

* A file header with:
	* Basic document metadata
	* A pointer to the page index array.
* A page index array with pointers to pages.
* Some pages, in XTH image format.

An XTH image is a raw 2bpp bit-planed bitmap image, with a simple header.

### Reference Material

* [reference/XTC-XTG-XTH-XTCH.md](reference/XTC-XTG-XTH-XTCH.md)
* [crosspoint-reader's XTC implementation](https://github.com/crosspoint-reader/crosspoint-reader/tree/develop/lib/Xtc/Xtc)

We only care about the features supported by the [crosspoint-reader](https://github.com/crosspoint-reader/crosspoint-reader) loader, and making sure that both crosspoint-reader and the official XTEINK firmware accept our files. This means the following features are ignored:

* Compression.
* MD5 checksums.
* Colour modes besides monochrome.
* Most of the document metadata fields.
