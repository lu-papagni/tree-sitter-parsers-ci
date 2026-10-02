# Vendored headers (fallback only)

`tree_sitter/parser.h` copied from
[tree-sitter/tree-sitter](https://github.com/tree-sitter/tree-sitter)
(`lib/src/parser.h`, the same file `tree-sitter generate` vendors into each
parser's `src/tree_sitter/`).

`build.py --direct` uses it only when a parser's own
`src/tree_sitter/parser.h` is missing (e.g. ancient checkouts built with
`--no-generate`). Freshly generated parsers always use their own headers.
