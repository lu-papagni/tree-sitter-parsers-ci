#!/usr/bin/env python3
"""
Build tree-sitter parsers from git submodules.

Discovers parser grammars in submodules, regenerates the C source with
`npx tree-sitter-cli generate`, then compiles shared libraries with
`npx tree-sitter-cli build` (no global install needed, just Node + npx).

Cross-compiling (e.g. for Android/Termux) uses --direct, which compiles
with $CC/$CXX instead of `tree-sitter build`:
    TARGET=aarch64-linux-android29
    CC="<ndk>/toolchains/llvm/prebuilt/linux-x86_64/bin/$TARGET-clang" \
    CFLAGS="--target=$TARGET" CXXFLAGS="--target=$TARGET" \
        python build.py -o dist-android --direct
--direct is required, not optional: `tree-sitter build` unconditionally
dlopens its output to verify it, which fails for foreign-arch libraries.
(CC/CFLAGS alone fix the target triple but not the dlopen.) The output
keeps the host extension (.so on Linux runners) but targets the Android ABI.
"""

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
import tempfile
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


def load_aliases(root: Path) -> dict[str, str]:
    """Load parser name aliases from aliases.json if it exists."""
    aliases_file = root / "aliases.json"
    if aliases_file.exists():
        with open(aliases_file) as f:
            return json.load(f)
    return {}


# Populated once at startup from aliases.json
_aliases: dict[str, str] = {}


def language_name(parser_path: Path) -> str:
    """Return the language name for parser_path.

    Strips the conventional `tree-sitter-` prefix so the compiled library
    is named after the language only, then applies any alias defined in
    aliases.json.
    """
    name = parser_path.name
    if name.startswith("tree-sitter-"):
        name = name[len("tree-sitter-"):]
    return _aliases.get(name, name)


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


def _split_env(name: str) -> list[str]:
    """Split a flags-style env var (CC/CFLAGS/...) like a shell would."""
    return shlex.split(os.environ.get(name, ""), posix=(os.name != "nt"))


def direct_compile(parser_path: Path, output_file: Path) -> bool:
    """Compile a parser with $CC/$CXX directly, bypassing `tree-sitter build`.

    `tree-sitter build` unconditionally dlopens its output to verify it
    (Loader::load_language_at_path_with_name -> Library::new), which fails
    for cross-compiled foreign-arch libraries. Driving the compiler
    ourselves avoids the load check, and also sidesteps the CLI pinning the
    cc crate's target triple to the host (which needs the CFLAGS --target
    counter-hack to undo).

    Mirrors the CLI's own flags: -O2 -fPIC -shared -std=c11 (-std=c++17 for
    C++ scanners), -Werror=implicit-function-declaration,
    -Wl,--no-undefined. Extra flags come from $CFLAGS/$CXXFLAGS, which is
    how --target reaches the cross-compiler here.
    """
    src = parser_path / "src"
    parser_c = src / "parser.c"
    if not parser_c.exists():
        print(f"  [error] {parser_c} not found (generate first?)")
        return False

    c_sources = [parser_c]
    scanner_c = src / "scanner.c"
    if scanner_c.exists():
        c_sources.append(scanner_c)
    cxx_sources = [src / n for n in ("scanner.cc", "scanner.cpp", "scanner.cxx")
                   if (src / n).exists()]

    cc = _split_env("CC") or ["cc"]
    cxx = _split_env("CXX") or ["c++"]

    includes = [f"-I{src}"]
    if not (src / "tree_sitter" / "parser.h").exists():
        vendor = Path(__file__).parent.resolve() / "vendor"
        if not (vendor / "tree_sitter" / "parser.h").exists():
            print("  [error] no parser headers: src/tree_sitter/parser.h missing")
            return False
        print("  [warn] src/tree_sitter/parser.h missing, using vendored headers")
        includes.append(f"-I{vendor}")

    with tempfile.TemporaryDirectory(prefix="ts-direct-") as tmp:
        objects: list[str] = []
        for s in c_sources:
            obj = str(Path(tmp) / f"{s.stem}.o")
            cmd = (cc + _split_env("CFLAGS")
                   + ["-c", "-O2", "-fPIC", "-std=c11",
                      "-Werror=implicit-function-declaration"]
                   + includes + [str(s), "-o", obj])
            r = run(cmd)
            if r.returncode != 0:
                print(f"  [error] compile failed ({s.name}): {(r.stderr or r.stdout).strip()}")
                return False
            objects.append(obj)
        for s in cxx_sources:
            obj = str(Path(tmp) / f"{s.stem}.o")
            cmd = (cxx + _split_env("CXXFLAGS")
                   + ["-c", "-O2", "-fPIC", "-std=c++17"]
                   + includes + [str(s), "-o", obj])
            r = run(cmd)
            if r.returncode != 0:
                print(f"  [error] compile failed ({s.name}): {(r.stderr or r.stdout).strip()}")
                return False
            objects.append(obj)

        link = (cxx if cxx_sources else cc)
        cmd = (link + _split_env("CFLAGS") + _split_env("CXXFLAGS")
               + ["-shared", "-Wl,--no-undefined"] + objects
               + ["-o", str(output_file)])
        r = run(cmd)
        if r.returncode != 0:
            print(f"  [error] link failed: {(r.stderr or r.stdout).strip()}")
            return False
    return True


def build_parser(parser_path: Path, output_dir: Path, *, generate: bool, direct: bool = False) -> bool:
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
    if direct:
        if not direct_compile(parser_path, output_file):
            return False
    else:
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
        "--direct", action="store_true",
        help="Compile with $CC/$CXX directly instead of `tree-sitter build`. "
             "Required for cross-compilation: the CLI dlopens its output, "
             "which fails for foreign-arch libraries.",
    )
    ap.add_argument(
        "parsers", nargs="*",
        help="Specific parser directories to build (default: all submodules)",
    )
    args = ap.parse_args()

    global _aliases
    root = Path(__file__).parent.resolve()
    _aliases = load_aliases(root)
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
    if args.direct:
        print(f"Compiler : {os.environ.get('CC', 'cc')} (direct, no tree-sitter build)")
    print(f"Parsers  : {', '.join(language_name(g) for g in grammars)}")

    ok: list[str] = []
    fail: list[str] = []
    for g in grammars:
        (ok if build_parser(g, output_dir, generate=gen, direct=args.direct) else fail).append(language_name(g))

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
