#!/usr/bin/env python3

HELP = """Render EPUB to paginated PNGs for simple e-readers, particularly
ones with broken CJK font support.

The rendered PNGs are written to the specified output directory, with
filenames starting from page_0000.png.

Pages are rendered at a fixed resolution, which should exactly match the
resolution of your e-reader device. The default is 480x800, which matches the
XTEINK X4.

The font size, margin etc can be customised via inline CSS injection.
"""

import argparse
import fitz # PyMuPDF
import io
import posixpath
import re
import shutil
import sys
import zipfile

from pathlib import Path
from PIL import Image
from urllib.parse import unquote

CSS_FILENAME = "injected_reader_style.css"
IMAGE_SIZE_FULLSCREEN_THRESHOLD = 100
RESET_TAG_FORMATTING = [
    "html",
    "body",
    "div",
    "section",
    "main",
    "article",
    "aside",
    "p",
    "span",
    "blockquote",
    "li",
    "a",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6"
]

def build_css(args):
    """Generate a CSS stylesheet to be linked at the end of each page's
    <head>. It resets formatting for common tags, adds a special CSS class
    for full-screen images, and styles ruby text (furigana) to work around
    the lack of ruby support in pymupdf."""
    max_w = args.width - (args.padding * 2)
    max_h = args.height - (args.padding * 2)

    reset_css = "".join(
        f"{tag} {{ margin: 0 !important; padding: 0 !important; border: none !important; font-size: {args.fontsize}pt !important; }}\n"
        for tag in RESET_TAG_FORMATTING
    )

    return f"""
@page {{
    margin: 0 !important;
    padding: 0 !important;
}}

{reset_css}

html {{
    padding: {args.padding}px !important;
}}
body {{
    line-height: {args.lineheight} !important;
}}
p {{
    text-indent: 1em !important;
}}

rt {{
    font-size: {args.fontsize * 0.5}pt !important;
    vertical-align: super;
}}

img.reader-fullpage {{
    display: block !important;
    break-before: page !important;
    break-after: page !important;
    max-width: {max_w}px !important;
    max-height: {max_h}px !important;
    margin: {args.padding}px auto !important;
    object-fit: contain !important;
}}
img:not(.reader-fullpage) {{
    display: inline-block !important;
    vertical-align: middle !important;
    margin: 0 !important;
    padding: 0 !important;
}}
"""

def process_img_tag(match, html_dir, file_data):
    """Apply a full-screen class to images over a certain size, and strip size attributes."""
    img_tag = match.group(0)
    src_match = re.search(r'(?:src|xlink:href|href)\s*=\s*["\']([^"\']+)["\']', img_tag, re.IGNORECASE)
    if not src_match:
        return img_tag

    src = unquote(src_match.group(1))
    img_path = posixpath.normpath(posixpath.join(html_dir, src))

    is_fullpage = False
    if img_path in file_data:
        try:
            img = Image.open(io.BytesIO(file_data[img_path]))
            w, h = img.size
            if w >= IMAGE_SIZE_FULLSCREEN_THRESHOLD or h >= IMAGE_SIZE_FULLSCREEN_THRESHOLD:
                is_fullpage = True
        except Exception:
            pass

    if is_fullpage:
        img_tag = re.sub(r'\swidth\s*=\s*["\'][^"\']*["\']', '', img_tag, flags=re.IGNORECASE)
        img_tag = re.sub(r'\sheight\s*=\s*["\'][^"\']*["\']', '', img_tag, flags=re.IGNORECASE)

        if 'class=' in img_tag:
            img_tag = re.sub(r'class\s*=\s*["\']', 'class="reader-fullpage ', img_tag, count=1, flags=re.IGNORECASE)
        else:
            img_tag = re.sub(r'(\s*/?>)$', ' class="reader-fullpage"\\1', img_tag)

    return img_tag

def process_svg_block(match, html_dir, file_data):
    """Replace <svg><image> combos with <img>, so it's laid out normally."""
    svg_block = match.group(0)

    image_match = re.search(r'<image[^>]+>', svg_block, re.IGNORECASE)
    if not image_match:
        return svg_block

    img_tag = image_match.group(0)
    src_match = re.search(r'(?:xlink:href|href)\s*=\s*["\']([^"\']+)["\']', img_tag, re.IGNORECASE)
    if not src_match:
        return svg_block

    src = unquote(src_match.group(1))
    img_path = posixpath.normpath(posixpath.join(html_dir, src))

    is_fullpage = False
    if img_path in file_data:
        try:
            img = Image.open(io.BytesIO(file_data[img_path]))
            w, h = img.size
            if w >= IMAGE_SIZE_FULLSCREEN_THRESHOLD or h >= IMAGE_SIZE_FULLSCREEN_THRESHOLD:
                is_fullpage = True
        except Exception:
            pass

    if is_fullpage:
        return f'<img class="reader-fullpage" src="{src}" alt=""/>'

    return svg_block

def inject_css_and_heuristics(epub_bytes, args):
    css_content = build_css(args)

    in_buffer = io.BytesIO(epub_bytes)
    out_buffer = io.BytesIO()

    with zipfile.ZipFile(in_buffer, 'r') as zin, \
         zipfile.ZipFile(out_buffer, 'w', zipfile.ZIP_DEFLATED) as zout:

        file_data = {item.filename: zin.read(item.filename) for item in zin.infolist()}

        for filename, data in file_data.items():
            if filename.lower().endswith(('.xhtml', '.html', '.htm')):
                html_str = data.decode('utf-8', errors='ignore')

                html_dir = posixpath.dirname(filename)
                rel_css_path = posixpath.relpath(CSS_FILENAME, html_dir)
                link_tag = f'<link rel="stylesheet" type="text/css" href="{rel_css_path}"/>'

                if '</head>' in html_str:
                    html_str = html_str.replace('</head>', link_tag + '</head>', 1)
                elif '<head' in html_str:
                    end_of_head_tag = html_str.find('>', html_str.find('<head')) + 1
                    html_str = html_str[:end_of_head_tag] + link_tag + html_str[end_of_head_tag:]

                html_str = re.sub(r'<meta\s+name=["\']viewport["\'][^>]*>', '', html_str, flags=re.IGNORECASE)

                html_str = re.sub(r'<img[^>]+>', lambda m: process_img_tag(m, html_dir, file_data), html_str, flags=re.IGNORECASE)
                html_str = re.sub(r'<svg[^>]*>.*?</svg>', lambda m: process_svg_block(m, html_dir, file_data), html_str, flags=re.DOTALL | re.IGNORECASE)

                data = html_str.encode('utf-8')

            zout.writestr(filename, data)

        zout.writestr(CSS_FILENAME, css_content)

    return out_buffer.getvalue()

def confirm(prompt, args):
    if args.yes:
        print(f"{prompt} -> automatic yes")
        return True
    while True:
        answer = input(prompt + " (y/n) ")
        if answer.lower() in "yn":
            return answer.lower() == "y"

def main():
    parser = argparse.ArgumentParser(description=HELP, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("input_epub", help="Path to the input EPUB file.")
    parser.add_argument("-o", "--output", default="output", help="Output directory for PNGs (default output/)")
    parser.add_argument("-W", "--width", type=int, default=480, help="Target page width (default 480)")
    parser.add_argument("-H", "--height", type=int, default=800, help="Target page height (default 800)")
    parser.add_argument("-P", "--padding", type=int, default=0, help="Padding in pixels around text (default 0)")
    parser.add_argument("-F", "--fontsize", type=int, default=32, help="Font size in points (default 32)")
    parser.add_argument("-L", "--lineheight", type=float, default=1.4, help="Line height multiplier (default 1.4)")
    parser.add_argument("-y", "--yes", action="store_true", help="Automatically answer all confirmations with yes")
    args = parser.parse_args()

    out_dir = Path(args.output)
    if out_dir.exists():
        if confirm("Output directory already exist, overwrite?", args):
            shutil.rmtree(out_dir)
        else:
            sys.exit("Refusing to overwrite existing output directory")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Processing {args.input_epub}...")
    with open(args.input_epub, "rb") as f:
        original_bytes = f.read()

    modified_bytes = inject_css_and_heuristics(original_bytes, args)

    doc = fitz.open("epub", modified_bytes)
    doc.layout(width=args.width, height=args.height, fontsize=args.fontsize)

    print(f"Rendering {len(doc)} pages to {out_dir}/...")
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))
        out_path = out_dir / f"page_{i:04d}.png"
        pix.save(str(out_path))

    print("Done.")

if __name__ == "__main__":
    main()
