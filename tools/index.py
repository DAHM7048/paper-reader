#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM-first paper indexer with rule-based fallback.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

from shared_config import load_config


PAGE_MARKER_RE = re.compile(r"<!--\s*Page\s+(\d+)\s*-->", re.IGNORECASE)
HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
WHITESPACE_RE = re.compile(r"\s+")

DEFAULT_STANDARD_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


def build_parser(config: dict) -> argparse.ArgumentParser:
    api_config = config["api"]
    index_config = config["index"]

    parser = argparse.ArgumentParser(
        description="Build an LLM-first retrieval index for papers/{paper}/full.md."
    )
    parser.add_argument("md_path", help="Path to full.md")
    parser.add_argument(
        "--prompt-path",
        default=str(Path(__file__).resolve().with_name("index.md")),
        help="Prompt template file for LLM indexing",
    )
    parser.add_argument(
        "--endpoint-mode",
        choices=["standard", "coding-plan"],
        default=os.environ.get("PDF2ZH_ENDPOINT_MODE", api_config["endpoint_mode"]),
        help="Model endpoint mode",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("INDEX_BASE_URL")
        or os.environ.get("PDF2ZH_BASE_URL")
        or api_config["base_url"],
        help="Custom OpenAI-compatible base URL",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "INDEX_MODEL",
            os.environ.get("PDF2ZH_MODEL", index_config["model"]),
        ),
        help="Model used for indexing",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(index_config["timeout"]),
        help=f"Model request timeout in seconds (default: {index_config['timeout']})",
    )
    parser.add_argument(
        "--max-chunk-pages",
        type=int,
        default=int(index_config["max_chunk_pages"]),
        help=f"Maximum pages per LLM chunk (default: {index_config['max_chunk_pages']})",
    )
    parser.add_argument(
        "--fallback-only",
        action="store_true",
        help="Skip LLM indexing and build rule-based index only",
    )
    return parser


def normalize_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def make_preview(text: str, limit: int = 220) -> str:
    preview = normalize_text(text.replace("---", " "))
    if len(preview) <= limit:
        return preview
    return preview[: limit - 3].rstrip() + "..."


def line_offsets(lines: list[str]) -> list[int]:
    offsets: list[int] = []
    total = 0
    for line in lines:
        offsets.append(total)
        total += len(line) + 1
    return offsets


def page_for_offset(page_entries: list[dict], offset: int) -> int:
    current_page = 1
    for page in page_entries:
        if page["start_offset"] <= offset:
            current_page = page["page"]
        else:
            break
    return current_page


def build_pages(content: str, lines: list[str], offsets: list[int]) -> list[dict]:
    markers: list[dict] = []
    for line_index, line in enumerate(lines):
        match = PAGE_MARKER_RE.search(line)
        if match:
            markers.append(
                {
                    "page": int(match.group(1)),
                    "line_index": line_index,
                    "start_offset": offsets[line_index],
                }
            )

    pages: list[dict] = []
    for index, marker in enumerate(markers):
        end_offset = (
            markers[index + 1]["start_offset"] if index + 1 < len(markers) else len(content)
        )
        snippet = content[marker["start_offset"] : end_offset]
        pages.append(
            {
                "page": marker["page"],
                "line_index": marker["line_index"] + 1,
                "start_offset": marker["start_offset"],
                "end_offset": end_offset,
                "char_count": max(0, end_offset - marker["start_offset"]),
                "preview": make_preview(snippet),
                "text": snippet,
            }
        )
    return pages


def build_rule_sections(content: str, lines: list[str], offsets: list[int], pages: list[dict]) -> list[dict]:
    sections: list[dict] = []
    for line_index, line in enumerate(lines):
        match = HEADER_RE.match(line)
        if not match:
            continue
        title = match.group(2).strip()
        sections.append(
            {
                "id": f"sec-{len(sections) + 1}",
                "title_en": title,
                "title_zh": title,
                "level": len(match.group(1)),
                "start_offset": offsets[line_index],
            }
        )

    for index, section in enumerate(sections):
        end_offset = len(content)
        for next_section in sections[index + 1 :]:
            if next_section["level"] <= section["level"]:
                end_offset = next_section["start_offset"]
                break
        section["end_offset"] = end_offset
        section["page_start"] = page_for_offset(pages, section["start_offset"])
        section["page_end"] = page_for_offset(pages, max(section["start_offset"], end_offset - 1))
        section["keywords"] = [section["title_en"][:48]]
        section["summary_zh"] = make_preview(content[section["start_offset"] : end_offset], 160)
        section["questions_answered"] = [f"{section['title_en']} 这一部分讲了什么？"]

    return sections


def build_rule_page_fallback(pages: list[dict]) -> list[dict]:
    return [
        {
            "id": f"page-{page['page']}",
            "page": page["page"],
            "start_offset": page["start_offset"],
            "end_offset": page["end_offset"],
            "summary_zh": page["preview"],
            "keywords": [f"page-{page['page']}"],
        }
        for page in pages
    ]


def fallback_index(md_path: Path) -> dict:
    content = md_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    offsets = line_offsets(lines)
    pages = build_pages(content, lines, offsets)
    sections = build_rule_sections(content, lines, offsets, pages)

    document_title = md_path.parent.name
    return {
        "document_title": document_title,
        "source_markdown": md_path.name,
        "source_pdf_candidates": [
            "original.pdf",
            f"{document_title}-mono.pdf",
            f"{document_title}-dual.pdf",
            "bilingual.pdf",
        ],
        "total_pages": len(pages),
        "total_chars": len(content),
        "sections": sections,
        "page_fallback": build_rule_page_fallback(pages),
        "retrieval_hints": {
            "primary": "Use sections first when titles are meaningful.",
            "fallback": "Use page_fallback when section titles are weak or absent.",
        },
        "index_build": {
            "mode": "fallback",
            "model": None,
            "chunks": 0,
        },
    }


def build_client(args: argparse.Namespace) -> OpenAI:
    api_key = os.environ.get("ZHIPU_API_KEY") or os.environ.get("OPENAILIKED_API_KEY")
    if not api_key:
        raise RuntimeError("ZHIPU_API_KEY is not set.")

    base_url = args.base_url
    if not base_url:
        if args.endpoint_mode == "coding-plan":
            base_url = load_config()["api"]["base_url"]
        else:
            base_url = DEFAULT_STANDARD_BASE_URL

    return OpenAI(base_url=base_url, api_key=api_key, timeout=args.timeout)


def chunk_pages(pages: list[dict], max_chunk_pages: int) -> list[list[dict]]:
    if max_chunk_pages < 1:
        raise ValueError("--max-chunk-pages must be >= 1")
    return [pages[i : i + max_chunk_pages] for i in range(0, len(pages), max_chunk_pages)]


def load_prompt(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def render_chunk_input(chunk: list[dict]) -> str:
    blocks: list[str] = []
    for page in chunk:
        blocks.append(
            "\n".join(
                [
                    f"PAGE: {page['page']}",
                    f"START_OFFSET: {page['start_offset']}",
                    f"END_OFFSET: {page['end_offset']}",
                    "CONTENT:",
                    page["text"].strip(),
                ]
            )
        )
    return "\n\n".join(blocks)


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def chat_json(client: OpenAI, model: str, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(strip_code_fence(content))


def sanitize_text_list(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        cleaned = [normalize_text(str(item)) for item in value if normalize_text(str(item))]
        if cleaned:
            return cleaned[:8]
    return fallback


def sanitize_chunk_result(chunk_result: dict[str, Any], chunk: list[dict]) -> dict[str, Any]:
    chunk_page_start = min(page["page"] for page in chunk)
    chunk_page_end = max(page["page"] for page in chunk)
    chunk_offset_end = max(page["end_offset"] for page in chunk)
    page_lookup = {page["page"]: page for page in chunk}

    sections: list[dict] = []
    for index, item in enumerate(chunk_result.get("sections", []), start=1):
        page_start = min(max(int(item.get("page_start", chunk_page_start)), chunk_page_start), chunk_page_end)
        page_end = min(max(int(item.get("page_end", page_start)), page_start), chunk_page_end)

        start_offset = int(item.get("start_offset", page_lookup[page_start]["start_offset"]))
        end_offset = int(item.get("end_offset", page_lookup[page_end]["end_offset"]))
        start_offset = min(max(start_offset, page_lookup[page_start]["start_offset"]), chunk_offset_end - 1)
        end_offset = min(max(end_offset, start_offset + 1), page_lookup[page_end]["end_offset"])

        sections.append(
            {
                "id": str(item.get("id", f"sec-{index}")),
                "title_en": normalize_text(str(item.get("title_en", ""))) or f"Section {page_start}-{page_end}",
                "title_zh": normalize_text(str(item.get("title_zh", ""))) or f"第{page_start}-{page_end}页主题",
                "level": max(1, int(item.get("level", 1))),
                "page_start": page_start,
                "page_end": page_end,
                "start_offset": start_offset,
                "end_offset": end_offset,
                "keywords": sanitize_text_list(item.get("keywords"), [f"page-{page_start}"]),
                "summary_zh": normalize_text(str(item.get("summary_zh", ""))) or f"第{page_start}-{page_end}页内容摘要。",
                "questions_answered": sanitize_text_list(
                    item.get("questions_answered"),
                    [f"第{page_start}-{page_end}页主要讲了什么？"],
                ),
            }
        )

    page_fallback: list[dict] = []
    seen_pages: set[int] = set()
    for item in chunk_result.get("page_fallback", []):
        page = min(max(int(item.get("page", chunk_page_start)), chunk_page_start), chunk_page_end)
        seen_pages.add(page)
        page_fallback.append(
            {
                "id": str(item.get("id", f"page-{page}")),
                "page": page,
                "start_offset": page_lookup[page]["start_offset"],
                "end_offset": page_lookup[page]["end_offset"],
                "summary_zh": normalize_text(str(item.get("summary_zh", ""))) or f"第{page}页内容摘要。",
                "keywords": sanitize_text_list(item.get("keywords"), [f"page-{page}"]),
            }
        )

    for page in chunk:
        if page["page"] in seen_pages:
            continue
        page_fallback.append(
            {
                "id": f"page-{page['page']}",
                "page": page["page"],
                "start_offset": page["start_offset"],
                "end_offset": page["end_offset"],
                "summary_zh": f"第{page['page']}页内容摘要。",
                "keywords": [f"page-{page['page']}"],
            }
        )

    page_fallback.sort(key=lambda item: int(item["page"]))
    return {"sections": sections, "page_fallback": page_fallback}


def validate_section_item(item: dict[str, Any], total_pages: int, total_chars: int) -> None:
    required = [
        "id",
        "title_en",
        "title_zh",
        "level",
        "page_start",
        "page_end",
        "start_offset",
        "end_offset",
        "keywords",
        "summary_zh",
        "questions_answered",
    ]
    for key in required:
        if key not in item:
            raise ValueError(f"Missing section field: {key}")

    if not isinstance(item["keywords"], list) or not item["keywords"]:
        raise ValueError("Section keywords must be a non-empty list")
    if not isinstance(item["questions_answered"], list) or not item["questions_answered"]:
        raise ValueError("Section questions_answered must be a non-empty list")
    if int(item["page_start"]) < 1 or int(item["page_end"]) > total_pages:
        raise ValueError("Section page range out of bounds")
    if int(item["start_offset"]) < 0 or int(item["end_offset"]) > total_chars:
        raise ValueError("Section offset out of bounds")
    if int(item["start_offset"]) >= int(item["end_offset"]):
        raise ValueError("Section offsets are invalid")


def validate_page_fallback_item(item: dict[str, Any], total_pages: int, total_chars: int) -> None:
    required = ["id", "page", "start_offset", "end_offset", "summary_zh", "keywords"]
    for key in required:
        if key not in item:
            raise ValueError(f"Missing page_fallback field: {key}")

    if int(item["page"]) < 1 or int(item["page"]) > total_pages:
        raise ValueError("Page fallback page out of bounds")
    if int(item["start_offset"]) < 0 or int(item["end_offset"]) > total_chars:
        raise ValueError("Page fallback offset out of bounds")
    if int(item["start_offset"]) >= int(item["end_offset"]):
        raise ValueError("Page fallback offsets are invalid")
    if not isinstance(item["keywords"], list) or not item["keywords"]:
        raise ValueError("Page fallback keywords must be a non-empty list")


def validate_final_index(index_data: dict[str, Any], total_pages: int, total_chars: int) -> None:
    required = [
        "document_title",
        "source_markdown",
        "source_pdf_candidates",
        "total_pages",
        "total_chars",
        "sections",
        "page_fallback",
        "retrieval_hints",
    ]
    for key in required:
        if key not in index_data:
            raise ValueError(f"Missing top-level field: {key}")

    if int(index_data["total_pages"]) != total_pages:
        raise ValueError("total_pages mismatch")
    if int(index_data["total_chars"]) != total_chars:
        raise ValueError("total_chars mismatch")

    sections = index_data["sections"]
    page_fallback = index_data["page_fallback"]
    if not isinstance(sections, list) or not sections:
        raise ValueError("sections must be a non-empty list")
    if not isinstance(page_fallback, list) or not page_fallback:
        raise ValueError("page_fallback must be a non-empty list")

    for item in sections:
        validate_section_item(item, total_pages, total_chars)
    for item in page_fallback:
        validate_page_fallback_item(item, total_pages, total_chars)


def repair_final_index(index_data: dict[str, Any], total_pages: int, total_chars: int) -> dict[str, Any]:
    repaired = dict(index_data)

    repaired_sections: list[dict[str, Any]] = []
    for item in repaired.get("sections", []):
        section = dict(item)
        section["page_start"] = min(max(int(section["page_start"]), 1), total_pages)
        section["page_end"] = min(max(int(section["page_end"]), section["page_start"]), total_pages)
        section["start_offset"] = min(max(int(section["start_offset"]), 0), max(0, total_chars - 1))
        section["end_offset"] = min(max(int(section["end_offset"]), section["start_offset"] + 1), total_chars)
        if section["end_offset"] <= section["start_offset"]:
            section["end_offset"] = min(total_chars, section["start_offset"] + 1)
        section["keywords"] = sanitize_text_list(section.get("keywords"), [section.get("title_en", "section")])
        section["questions_answered"] = sanitize_text_list(
            section.get("questions_answered"),
            [f"{section.get('title_en', 'This section')} 讲了什么？"],
        )
        section["summary_zh"] = normalize_text(str(section.get("summary_zh", ""))) or "本节内容摘要。"
        repaired_sections.append(section)

    repaired_pages: list[dict[str, Any]] = []
    for item in repaired.get("page_fallback", []):
        page = dict(item)
        page["page"] = min(max(int(page["page"]), 1), total_pages)
        page["start_offset"] = min(max(int(page["start_offset"]), 0), max(0, total_chars - 1))
        page["end_offset"] = min(max(int(page["end_offset"]), page["start_offset"] + 1), total_chars)
        if page["end_offset"] <= page["start_offset"]:
            page["end_offset"] = min(total_chars, page["start_offset"] + 1)
        page["keywords"] = sanitize_text_list(page.get("keywords"), [f"page-{page['page']}"])
        page["summary_zh"] = normalize_text(str(page.get("summary_zh", ""))) or f"第{page['page']}页内容摘要。"
        repaired_pages.append(page)

    repaired["sections"] = repaired_sections
    repaired["page_fallback"] = repaired_pages
    return repaired


def merge_chunk_sections(chunk_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    counter = 1
    for chunk_result in chunk_results:
        for item in chunk_result.get("sections", []):
            merged = dict(item)
            merged["id"] = f"sec-{counter}"
            counter += 1
            sections.append(merged)
    sections.sort(key=lambda item: (int(item["start_offset"]), int(item["page_start"])))
    return sections


def merge_page_fallback(chunk_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for chunk_result in chunk_results:
        items.extend(dict(item) for item in chunk_result.get("page_fallback", []))
    items.sort(key=lambda item: int(item["page"]))
    return items


def llm_index(md_path: Path, args: argparse.Namespace) -> dict:
    prompt_template = load_prompt(Path(args.prompt_path).expanduser().resolve())
    client = build_client(args)

    content = md_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    offsets = line_offsets(lines)
    pages = build_pages(content, lines, offsets)
    if not pages:
        raise RuntimeError("No page markers found in full.md")

    chunk_results: list[dict[str, Any]] = []
    chunks = chunk_pages(pages, args.max_chunk_pages)

    for index, chunk in enumerate(chunks, start=1):
        user_prompt = "\n\n".join(
            [
                f"DOCUMENT_TITLE: {md_path.parent.name}",
                f"TOTAL_PAGES: {len(pages)}",
                f"TOTAL_CHARS: {len(content)}",
                f"CHUNK_INDEX: {index}/{len(chunks)}",
                "Produce section candidates and page_fallback entries only for the supplied pages.",
                render_chunk_input(chunk),
            ]
        )
        chunk_result = chat_json(client, args.model, prompt_template, user_prompt)
        if "sections" not in chunk_result or "page_fallback" not in chunk_result:
            raise ValueError("Chunk response missing sections or page_fallback")
        chunk_results.append(sanitize_chunk_result(chunk_result, chunk))

    result = {
        "document_title": md_path.parent.name,
        "source_markdown": md_path.name,
        "source_pdf_candidates": [
            "original.pdf",
            f"{md_path.parent.name}-mono.pdf",
            f"{md_path.parent.name}-dual.pdf",
            "bilingual.pdf",
        ],
        "total_pages": len(pages),
        "total_chars": len(content),
        "sections": merge_chunk_sections(chunk_results),
        "page_fallback": merge_page_fallback(chunk_results),
        "retrieval_hints": {
            "primary": "先查看 sections，按关键词、问题和中文摘要定位主题。",
            "fallback": "如果章节命中弱，再查看 page_fallback，然后回到 full.md 的 offset 范围读取原文。",
        },
        "index_build": {
            "mode": "llm",
            "model": args.model,
            "chunks": len(chunks),
        },
    }
    result = repair_final_index(result, len(pages), len(content))
    validate_final_index(result, len(pages), len(content))
    return result


def write_index(output_path: Path, data: dict) -> None:
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    config = load_config()
    parser = build_parser(config)
    args = parser.parse_args()
    md_path = Path(args.md_path).expanduser().resolve()

    if not md_path.exists():
        print(f"Error: Markdown file not found: {md_path}", file=sys.stderr)
        return 1

    api_key = config["api"].get("api_key", "").strip()
    if api_key and "ZHIPU_API_KEY" not in os.environ and "OPENAILIKED_API_KEY" not in os.environ:
        os.environ["ZHIPU_API_KEY"] = api_key

    output_path = md_path.parent / "index.json"
    try:
        if args.fallback_only:
            result = fallback_index(md_path)
        else:
            try:
                result = llm_index(md_path, args)
            except Exception as exc:
                print(f"Warning: LLM indexing failed, fallback to rule index: {exc}")
                result = fallback_index(md_path)

        write_index(output_path, result)
        print(f"Index generated: {output_path}")
        print(f"  - mode: {result['index_build']['mode']}")
        print(f"  - total_pages: {result['total_pages']}")
        print(f"  - total_chars: {result['total_chars']}")
        print(f"  - sections: {len(result['sections'])}")
        print(f"  - page_fallback: {len(result['page_fallback'])}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
