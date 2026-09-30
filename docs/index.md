# SignalForge Documentation

This site combines human-maintained architecture and engineering documentation with generated Python API reference.

## Documentation sources

- Architecture decisions remain canonical under `docs/architecture/decisions/`.
- Implementation work must satisfy the [Engineering Definition of Done](engineering-definition-of-done.md).
- Python documentation follows the [Python Documentation Standard](python-documentation-standard.md).
- API pages are generated from source docstrings and type signatures using MkDocs and mkdocstrings.

## Build locally

Install the documentation dependencies:

```bash
python -m pip install -e '.[docs]'
```

Build the site:

```bash
mkdocs build --strict
```

Run a local documentation server:

```bash
mkdocs serve
```

Generated API documentation complements source code, tests, ADRs and normative strategy specifications. It does not replace those authorities.
