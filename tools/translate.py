#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from shared_config import load_config


DEFAULT_PDF2ZH_EXE = Path("D:/study/python3.12/Scripts/pdf2zh.exe")
DEFAULT_THREADS = 5
DEFAULT_TIMEOUT_SECONDS = 3600
DEFAULT_CODING_PLAN_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
DEFAULT_STANDARD_SERVICE = "zhipu"
DEFAULT_CODING_PLAN_SERVICE = "openailiked"
DEFAULT_ENDPOINT_MODE = "coding-plan"
DEFAULT_MODEL = "GLM-4-Flash-250414"


def build_parser(config: dict) -> argparse.ArgumentParser:
    api_config = config["api"]
    translate_config = config["translate"]

    parser = argparse.ArgumentParser(
        description="Translate a PDF into a bilingual PDF with pdf2zh."
    )
    parser.add_argument("pdf_path", help="Path to the input PDF file")
    parser.add_argument(
        "--threads",
        type=int,
        default=int(translate_config["threads"]),
        help=f"Translation thread count passed to pdf2zh (default: {translate_config['threads']})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(translate_config["timeout"]),
        help=(
            "Translation timeout in seconds for the pdf2zh subprocess "
            f"(default: {translate_config['timeout']})"
        ),
    )
    parser.add_argument(
        "--pdf2zh-exe",
        default=str(translate_config["pdf2zh_exe"]),
        help=f"Path to pdf2zh executable (default: {translate_config['pdf2zh_exe']})",
    )
    parser.add_argument(
        "--service",
        default=os.environ.get("PDF2ZH_SERVICE", translate_config["service"]),
        help=f"Translation service for pdf2zh (default: {translate_config['service']})",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "PDF2ZH_MODEL",
            os.environ.get("ZHIPU_MODEL", translate_config["model"]),
        ),
        help="Model name for the selected translation service",
    )
    parser.add_argument(
        "--cache-root",
        default=None,
        help=(
            "Project-local runtime cache root. "
            "Defaults to .runtime/pdf2zh-home under the repo root."
        ),
    )
    parser.add_argument(
        "--endpoint-mode",
        choices=["standard", "coding-plan"],
        default=os.environ.get("PDF2ZH_ENDPOINT_MODE", api_config["endpoint_mode"]),
        help=(
            "standard: use pdf2zh's built-in service adapter; "
            "coding-plan: use the OpenAI-compatible adapter against "
            "the Coding Plan endpoint"
        ),
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PDF2ZH_BASE_URL", api_config["base_url"]),
        help=(
            "Custom OpenAI-compatible base URL. "
            "Used in coding-plan mode, or when you want to override the endpoint."
        ),
    )
    return parser


def resolve_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_runtime_home(args: argparse.Namespace, repo_root: Path) -> Path:
    if args.cache_root:
        return Path(args.cache_root).expanduser().resolve()
    return (repo_root / ".runtime" / "pdf2zh-home").resolve()


def ensure_runtime_dirs(runtime_home: Path) -> None:
    # pdf2zh uses ~/.cache/pdf2zh, babeldoc uses ~/.cache/babeldoc.
    (runtime_home / ".cache" / "pdf2zh").mkdir(parents=True, exist_ok=True)
    (runtime_home / ".cache" / "babeldoc" / "fonts").mkdir(parents=True, exist_ok=True)
    (runtime_home / ".cache" / "babeldoc" / "models").mkdir(parents=True, exist_ok=True)
    (runtime_home / ".cache" / "babeldoc" / "tiktoken").mkdir(
        parents=True, exist_ok=True
    )


def build_pdf2zh_env(
    runtime_home: Path,
    endpoint_mode: str,
    service: str,
    model: str,
    base_url: str | None,
    repo_root: Path,
) -> dict[str, str]:
    env = os.environ.copy()
    runtime_home_str = str(runtime_home)
    drive, tail = os.path.splitdrive(runtime_home_str)

    env["HOME"] = runtime_home_str
    env["USERPROFILE"] = runtime_home_str
    if drive:
        env["HOMEDRIVE"] = drive
    if tail:
        env["HOMEPATH"] = tail

    # Keep all transient assets inside the repository workspace.
    env.setdefault("TIKTOKEN_CACHE_DIR", str(runtime_home / ".cache" / "babeldoc" / "tiktoken"))

    # Mainland network access to Hugging Face is often unreliable.
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    if endpoint_mode == "coding-plan":
        api_key = env.get("ZHIPU_API_KEY") or env.get("OPENAILIKED_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ZHIPU_API_KEY is not set. Export it before running translation."
            )
        env["OPENAILIKED_API_KEY"] = api_key
        env["OPENAILIKED_BASE_URL"] = base_url or DEFAULT_CODING_PLAN_BASE_URL
        env["OPENAILIKED_MODEL"] = model
    elif service == "zhipu":
        api_key = env.get("ZHIPU_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ZHIPU_API_KEY is not set. Export it before running translation."
            )
        env["ZHIPU_MODEL"] = model
    elif service == "openailiked":
        api_key = env.get("OPENAILIKED_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAILIKED_API_KEY is not set. Export it before running translation."
            )
        if not base_url:
            raise RuntimeError(
                "OPENAILIKED_BASE_URL / --base-url is required for service=openailiked."
            )
        env["OPENAILIKED_BASE_URL"] = base_url
        env["OPENAILIKED_MODEL"] = model

    # Make downstream tools inherit a stable workspace-local temp/cache location.
    env.setdefault("TMPDIR", str(repo_root / ".runtime" / "tmp"))
    env.setdefault("TEMP", str(repo_root / ".runtime" / "tmp"))
    env.setdefault("TMP", str(repo_root / ".runtime" / "tmp"))
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)

    return env


def validate_input_pdf(pdf_path: Path) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Input PDF file not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Input file must be a PDF: {pdf_path}")


def find_translated_dual_pdf(output_dir: Path, input_stem: str) -> Path | None:
    direct_candidate = output_dir / "bilingual.pdf"
    if direct_candidate.exists():
        return direct_candidate

    candidates = [
        output_dir / f"{input_stem}-dual.pdf",
        output_dir / f"{input_stem}_dual.pdf",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    dual_pdfs = sorted(output_dir.glob("*-dual.pdf"), key=lambda p: p.stat().st_mtime)
    if dual_pdfs:
        return dual_pdfs[-1]
    return None


def main() -> int:
    repo_root = resolve_repo_root()
    config = load_config(repo_root)
    parser = build_parser(config)
    args = parser.parse_args()
    input_pdf = Path(args.pdf_path).expanduser().resolve()
    pdf2zh_exe = Path(args.pdf2zh_exe).expanduser().resolve()

    try:
        validate_input_pdf(input_pdf)
        if not pdf2zh_exe.exists():
            raise FileNotFoundError(f"pdf2zh executable not found: {pdf2zh_exe}")
        if args.threads < 1:
            raise ValueError("--threads must be >= 1")
        if args.timeout < 1:
            raise ValueError("--timeout must be >= 1")

        selected_service = args.service
        selected_base_url = args.base_url
        if args.endpoint_mode == "coding-plan":
            selected_service = DEFAULT_CODING_PLAN_SERVICE
            if not selected_base_url:
                selected_base_url = DEFAULT_CODING_PLAN_BASE_URL

        paper_name = input_pdf.stem
        output_dir = repo_root / "papers" / paper_name
        output_dir.mkdir(parents=True, exist_ok=True)
        output_pdf = output_dir / "bilingual.pdf"

        runtime_home = resolve_runtime_home(args, repo_root)
        ensure_runtime_dirs(runtime_home)
        env = build_pdf2zh_env(
            runtime_home,
            args.endpoint_mode,
            selected_service,
            args.model,
            selected_base_url,
            repo_root,
        )
        api_key = config["api"].get("api_key", "").strip()
        if api_key and "ZHIPU_API_KEY" not in env and "OPENAILIKED_API_KEY" not in env:
            env["ZHIPU_API_KEY"] = api_key

        cmd = [
            str(pdf2zh_exe),
            str(input_pdf),
            "-s",
            selected_service,
            "-t",
            str(args.threads),
            "-o",
            str(output_dir),
        ]

        print(f"Translating: {input_pdf.name}")
        print(f"Output directory: {output_dir}")
        print(f"Runtime cache home: {runtime_home}")
        print(f"Threads: {args.threads}")
        print(f"Endpoint mode: {args.endpoint_mode}")
        print(f"Service: {selected_service}")
        print(f"Model: {args.model}")
        if selected_base_url:
            print(f"Base URL: {selected_base_url}")

        subprocess.run(
            cmd,
            env=env,
            cwd=str(repo_root),
            check=True,
            timeout=args.timeout,
            capture_output=False,
        )

        translated_file = find_translated_dual_pdf(output_dir, input_pdf.stem)
        if translated_file is None:
            raise FileNotFoundError(
                "pdf2zh finished but no bilingual PDF was found in the output directory."
            )

        if translated_file != output_pdf:
            if output_pdf.exists():
                output_pdf.unlink()
            shutil.move(str(translated_file), str(output_pdf))

        print("\nTranslation completed successfully!")
        print(f"Bilingual PDF saved to: {output_pdf}")
        return 0
    except subprocess.TimeoutExpired as exc:
        print(
            f"\nError: Translation timed out after {exc.timeout} seconds.",
            file=sys.stderr,
        )
        return 1
    except subprocess.CalledProcessError as exc:
        print(
            f"\nError: Translation failed with exit code {exc.returncode}.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
