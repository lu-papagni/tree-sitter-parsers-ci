# tree-sitter-parsers-ci

Automated CI to compile [tree-sitter](https://tree-sitter.github.io/) parsers
into shared libraries for **Linux** and **Windows**.

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
# Prerequisites: tree-sitter-cli, node, a C compiler
npm install -g tree-sitter-cli

python build.py            # builds all parsers into dist/
python build.py -o out     # custom output directory
python build.py --no-generate   # skip tree-sitter generate, use existing parser.c
python build.py parsers/tree-sitter-c   # build a single parser
```

## CI workflow

| Trigger | What happens |
|---------|-------------|
| Push / PR | Build on Linux, macOS, Windows (validation) |
| Push to `main` | Build + create GitHub Release with platform zips |
| `workflow_dispatch` | Same as push to main |

### Release artifacts

Each release contains one zip per platform:

- `tree-sitter-parsers-linux-x64.zip`
- `tree-sitter-parsers-windows-x64.zip`

Inside each zip you'll find the compiled shared libraries:

| Platform | File pattern |
|----------|-------------|
| Linux | `libtree-sitter-<name>.so` |
| Windows | `tree-sitter-<name>.dll` |

## Dependabot

Submodule updates are checked weekly and grouped into a single PR
(see [`.github/dependabot.yml`](.github/dependabot.yml)).  Merge the PR to
trigger a new release.
