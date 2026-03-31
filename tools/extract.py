#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Extract text from a PDF and save it as papers/{paper_name}/full.md.
"""

import os
import sys
from pathlib import Path

import fitz


KNOWN_RENDER_SUFFIXES = ("-mono", "-dual")


def strip_render_suffix(name: str) -> str:
    for suffix in KNOWN_RENDER_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def resolve_output_dir(input_pdf: Path) -> tuple[Path, str]:
    input_pdf = input_pdf.resolve()

    if input_pdf.name.lower() == "original.pdf" and input_pdf.parent.parent.name == "papers":
        return input_pdf.parent, input_pdf.parent.name

    if input_pdf.parent.parent.name == "papers":
        return input_pdf.parent, strip_render_suffix(input_pdf.stem)

    paper_name = strip_render_suffix(input_pdf.stem)
    return Path("papers") / paper_name, paper_name


def resolve_preferred_pdf(input_pdf: Path) -> Path:
    input_pdf = input_pdf.resolve()
    if input_pdf.stem.endswith("-mono"):
        return input_pdf

    mono_candidate = input_pdf.with_name(f"{input_pdf.stem}-mono.pdf")
    if mono_candidate.exists():
        print(f"Found mono PDF, using: {mono_candidate}")
        return mono_candidate

    return input_pdf


def detect_heading_level(font_sizes: list[float], size: float) -> str | None:
    if not font_sizes:
        return None

    max_size = max(font_sizes)
    min_size = min(font_sizes)
    size_range = max_size - min_size
    if size_range == 0:
        return None

    if size >= max_size - size_range * 0.2:
        return "#"
    if size >= min_size + size_range * 0.5:
        return "##"
    return None


def extract_page_content(page: fitz.Page, page_num: int, font_sizes: list[float]) -> tuple[str, int]:
    content: list[str] = [f"<!-- Page {page_num} -->\n"]

    blocks = page.get_text("dict")["blocks"]
    images = page.get_images()
    image_info = [
        f"![Image placeholder](page_{page_num}_img_{img_idx})"
        for img_idx, _ in enumerate(images, start=1)
    ]

    for block in blocks:
        if block["type"] != 0:
            continue

        block_lines: list[str] = []
        for line in block["lines"]:
            line_parts: list[str] = []
            heading_prefix = None

            for span in line["spans"]:
                text = span["text"]
                if not text.strip():
                    continue

                if heading_prefix is None:
                    heading_prefix = detect_heading_level(font_sizes, span["size"])
                line_parts.append(text)

            line_text = "".join(line_parts).strip()
            if not line_text:
                continue

            if heading_prefix:
                block_lines.append(f"{heading_prefix} {line_text}")
            else:
                block_lines.append(line_text)

        if block_lines:
            content.append("\n".join(block_lines))
            content.append("\n\n")

    if image_info:
        content.extend(f"{item}\n" for item in image_info)
        content.append("\n")

    return "".join(content).rstrip() + "\n", len(images)


def extract_pdf(pdf_path: Path) -> tuple[str, int]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        raise RuntimeError(f"Unable to open PDF: {exc}") from exc

    all_font_sizes: list[float] = []
    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    all_font_sizes.append(span["size"])

    markdown_parts: list[str] = []
    total_images = 0
    total_pages = len(doc)

    for page_num, page in enumerate(doc, start=1):
        page_content, num_images = extract_page_content(page, page_num, all_font_sizes)
        markdown_parts.append(page_content)
        total_images += num_images
        if page_num < total_pages:
            markdown_parts.append("\n---\n\n")

    doc.close()
    return "".join(markdown_parts), total_images


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/extract.py <pdf_path>", file=sys.stderr)
        return 1

    input_pdf = Path(sys.argv[1]).expanduser()

    try:
        preferred_pdf = resolve_preferred_pdf(input_pdf)
        output_dir, paper_name = resolve_output_dir(preferred_pdf)
        markdown_content, total_images = extract_pdf(preferred_pdf)

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "full.md"
        output_path.write_text(markdown_content, encoding="utf-8")

        print(f"Success: extracted {len(markdown_content)} characters to {output_path}")
        print(f"Paper: {paper_name}")
        print(f"Images: {total_images}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
