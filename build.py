#!/usr/bin/env python3
"""
Build tree-sitter parsers from git submodules.

Discovers parser grammars in submodules, regenerates the C source with
`npx tree-sitter-cli generate`, then compiles shared libraries with
`npx tree-sitter-cli build` (no global install needed, just Node + npx).
"""

import argparse
import platform
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def lib_ext() -> str:
    s = platform.system()
    if s == "Linux":
        return ".so"
    if s == "Darwin":
        return ".dylib"
    if s == "Windows":
        return ".dll"
    raise RuntimeError(f"Unsupported platform: {s}")


def language_name(parser_path: Path) -> str:
    """Return the language name for parser_path.

    Strips the conventional `tree-sitter-` prefix so the compiled library
    is named after the language only.
    """
    name = parser_path.name
    if name.startswith("tree-sitter-"):
        return name[len("tree-sitter-"):]
    return name


def _is_grammar(path: Path) -> bool:
    """Return True if *path* looks like a tree-sitter grammar root."""
    return (path / "grammar.js").exists() or (path / "src" / "parser.c").exists()


def discover_parsers(root: Path) -> list[Path]:
    """Find parser grammars from git submodules.

    Handles single-grammar repos (grammar.js at root) and multi-grammar repos
    (e.g. tree-sitter-typescript with typescript/ and tsx/ subdirectories).
    """
    gitmodules = root / ".gitmodules"
    if not gitmodules.exists():
        return []

    result = subprocess.run(
        ["git", "config", "--file", str(gitmodules), "--get-regexp", "path"],
        capture_output=True,
        text=True,
        cwd=root,
    )
    if result.returncode != 0:
        return []

    submodule_paths: list[Path] = []
    for line in result.stdout.strip().splitlines():
        # Format: submodule.<name>.path <value>
        _, rel = line.split(maxsplit=1)
        submodule_paths.append(root / rel)

    grammars: list[Path] = []
    for path in submodule_paths:
        if not path.is_dir():
            continue
        if _is_grammar(path):
            grammars.append(path)
        else:
            # Multi-grammar repos keep each language in a subdirectory
            for child in sorted(path.iterdir()):
                if child.is_dir() and _is_grammar(child):
                    grammars.append(child)

    return sorted(grammars)


# Run the tree-sitter CLI via npx so no global install is required.
# `-y` auto-accepts the install prompt on first use / in CI.
TS_CLI: list[str] = ["npx", "-y", "tree-sitter-cli"]


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    print(f"  $ {' '.join(cmd)}")
    # On Windows, npx is a .cmd script and needs shell=True to be found.
    return subprocess.run(cmd, capture_output=True, text=True,
                          shell=(platform.system() == "Windows"), **kwargs)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_parser(parser_path: Path, output_dir: Path, *, generate: bool) -> bool:
    name = language_name(parser_path)
    output_file = output_dir / f"{name}{lib_ext()}"

    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")

    grammar_js = parser_path / "grammar.js"
    parser_c = parser_path / "src" / "parser.c"

    # Step 1 — (re)generate parser.c from grammar.js
    if generate and grammar_js.exists():
        print("  Generating parser.c ...")
        r = run([*TS_CLI, "generate"], cwd=parser_path)
        if r.returncode != 0:
            if parser_c.exists():
                print("  [warn] generate failed, falling back to existing parser.c")
                if r.stderr.strip():
                    print(f"    {r.stderr.strip()}")
            else:
                print(f"  [error] generate failed: {r.stderr.strip()}")
                return False

    # Step 2 — compile shared library
    print(f"  Compiling {output_file.name} ...")
    r = run([*TS_CLI, "build", str(parser_path), "-o", str(output_file)])
    if r.returncode != 0:
        print(f"  [error] build failed: {r.stderr.strip()}")
        return False

    kb = output_file.stat().st_size / 1024
    print(f"  [ok] {output_file.name} ({kb:.0f} KB)")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Build tree-sitter parsers from submodules")
    ap.add_argument(
        "-o", "--output", default="dist",
        help="Output directory for compiled libraries (default: dist)",
    )
    ap.add_argument(
        "--no-generate", action="store_true",
        help="Skip `npx tree-sitter-cli generate` — use pre-existing src/parser.c",
    )
    ap.add_argument(
        "parsers", nargs="*",
        help="Specific parser directories to build (default: all submodules)",
    )
    args = ap.parse_args()

    root = Path(__file__).parent.resolve()
    output_dir = (root / args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    grammars = (
        [Path(p).resolve() for p in args.parsers]
        if args.parsers
        else discover_parsers(root)
    )

    if not grammars:
        print("No parsers found. Add parser submodules first:")
        print("  git submodule add --depth 1 <url> parsers/<name>")
        sys.exit(1)

    gen = not args.no_generate
    print(f"Platform : {platform.system()} ({lib_ext()})")
    print(f"Output   : {output_dir}")
    print(f"Generate : {'yes' if gen else 'no'}")
    print(f"Parsers  : {', '.join(language_name(g) for g in grammars)}")

    ok: list[str] = []
    fail: list[str] = []
    for g in grammars:
        (ok if build_parser(g, output_dir, generate=gen) else fail).append(language_name(g))

    print(f"\n{'=' * 60}")
    print(f"  {len(ok)} succeeded, {len(fail)} failed")
    if ok:
        print(f"  [ok] {', '.join(ok)}")
    if fail:
        print(f"  [error] {', '.join(fail)}")
    print(f"{'=' * 60}")

    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
