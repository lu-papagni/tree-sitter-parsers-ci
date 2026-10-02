# tree-sitter-parsers-ci

Automated CI to compile [tree-sitter](https://tree-sitter.github.io/) parsers
into shared libraries for **Linux**, **Windows**, and **Android (Termux)**.

Parsers are tracked as shallow git submodules under `parsers/`.
[Dependabot](.github/dependabot.yml) proposes weekly updates (grouped into a
single PR).  Merging to `main` triggers a build across all platforms and
publishes a GitHub Release with downloadable zip archives.

## Adding a parser

```bash
git submodule add --depth 1 https://github.com/tree-sitter/tree-sitter-python parsers/tree-sitter-python
git commit -m "Add tree-sitter-python"
```

The build script auto-discovers every submodule that contains a `grammar.js` or
`src/parser.c`.  Multi-grammar repos (e.g. `tree-sitter-typescript` with
`typescript/` and `tsx/` sub-directories) are handled automatically.

## Local build

```bash
# Prerequisites: node (npx), python, a C compiler — no global install needed,
# build.py runs the CLI via `npx -y tree-sitter-cli`

python build.py            # builds all parsers into dist/
python build.py -o out     # custom output directory
python build.py --no-generate   # skip generate, use existing parser.c
python build.py parsers/tree-sitter-c   # build a single parser
```

## Android (Termux)

Termux cannot use the Linux `.so` files: it runs on Android's **Bionic libc**,
while the Linux builds link against **glibc**
(see [Differences from Linux](https://wiki.termux.dev/wiki/Differences_from_Linux)).
The `android-aarch64` artifact is cross-compiled with the Android NDK
(`aarch64-linux-android`, minSdk 29 = Android 10) and links
against Bionic, so it loads in Termux (e.g. for Neovim's tree-sitter).

To reproduce locally with the NDK installed:

```bash
export NDK=$ANDROID_NDK_HOME   # or wherever your NDK lives
export TARGET=aarch64-linux-android29
CC="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/$TARGET-clang" \
CFLAGS="--target=$TARGET" CXXFLAGS="--target=$TARGET" \
  python build.py -o dist-android
file dist-android/*.so   # should report "ARM aarch64"
```

> **Gotcha:** setting `CC` alone is *not* enough. `tree-sitter build`
> compiles through the Rust `cc` crate with target/host pinned to the CLI's
> own build triple (x86_64 Linux), so it appends `--target=x86_64-...`
> after the NDK wrapper's `--target`, and clang honors the *last*
> `--target`. Re-stating the Android `--target` in `CFLAGS`/`CXXFLAGS`
> puts it last on the command line, restoring the Android target.

## CI workflow

| Trigger | What happens |
|---------|-------------|
| Push / PR | Build on Linux, Windows, Android (validation) |
| Push to `main` | Build + create GitHub Release with platform zips |
| `workflow_dispatch` | Same as push to main |

### Release artifacts

Each release contains one zip per platform:

- `tree-sitter-parsers-linux-x64.zip`
- `tree-sitter-parsers-windows-x64.zip`
- `tree-sitter-parsers-android-aarch64.zip`

Inside each zip you'll find the compiled shared libraries, named after the
language only (the `tree-sitter-` prefix is stripped):

| Platform | File pattern |
|----------|-------------|
| Linux | `<name>.so` (glibc, x86-64) |
| Windows | `<name>.dll` |
| Android (Termux) | `<name>.so` (Bionic, ARM aarch64) |

For example, `parsers/tree-sitter-c` builds `c.so` / `c.dll`.

## Dependabot

Submodule updates are checked weekly and grouped into a single PR
(see [`.github/dependabot.yml`](.github/dependabot.yml)).  Merge the PR to
trigger a new release.
