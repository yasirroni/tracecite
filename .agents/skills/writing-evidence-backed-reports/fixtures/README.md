# Writing evidence-backed reports fixtures

This fixture package is synthetic and redistributable. It stores Markdown reports and a schema-v2 source-link registry, while `validate_fixtures.py` creates fresh temporary PDFs, assets, and a corpus-specific SQLite database at validation time.

Run from a checkout:

```sh
python fixtures/validate_fixtures.py
```

The validator creates a temporary corpus, runs the installed TraceCite CLI
(`sync`, `verify quote`, `verify report`, and `doctor`), and leaves no
committed database, cache, generated PDF, or image asset behind.
