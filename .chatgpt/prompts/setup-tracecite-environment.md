# Setup TraceCite Environment

Materialise and query the supplied offline TraceCite environment using these inputs:

```text
/mnt/data/semantic-search-linux-x86_64-py313.zip
/mnt/data/tracecite-<date>.zip
/mnt/data/tracecite.sqlite
```

Example `tracecite-<date>.zip` is `tracecite-260728.zip`.

## Artefact roles

* `semantic-search-linux-x86_64-py313.zip` contains the offline Python 3.13 semantic-search runtime dependencies, native wheels and embedding-model cache.
* `tracecite-<date>.zip` contains the TraceCite Python package and CLI source.
* `tracecite.sqlite` is an already-populated TraceCite database. Do not rebuild, synchronise, migrate, prune or modify it.
* The database may reference generated assets under an absent `imgs/` directory. Missing image assets do not block text or semantic search.

## Materialisation requirements

1. Work under:

   ```text
   /mnt/data/tracecite-query
   ```

2. First inspect the archives and identify their actual internal paths. Do not assume directory names.

3. If a valid materialised environment already exists under that directory, reuse it rather than extracting and installing everything again.

4. Verify provided checksums or manifests before extraction when they exist.

5. Materialise the semantic-search environment and TraceCite package so that the `tracecite` command runs using the bundled Python 3.13 environment.

6. Run entirely offline. Do not download packages or embedding models.

7. Do not use or extract Julia, Julia environments or Quarto; they are unrelated to this task.

8. Keep `/mnt/data/tracecite.sqlite` unchanged. Use it as the query database.

9. Set explicit environment variables or an activation script for:

   ```text
   TRACECITE_DATABASE=/mnt/data/tracecite.sqlite
   TRACECITE_MODEL_CACHE=<identified bundled model-cache path>
   ```

## Minimal validation

Run only these initial checks:

```bash
tracecite --help
```

Then use Python’s built-in `sqlite3` module to confirm:

* the database opens;
* `PRAGMA quick_check` returns `ok`;
* the expected TraceCite tables exist;
* source, page, chunk and embedding row counts are non-zero.

Do not run the full `tracecite doctor` command before querying unless the minimal validation fails. Missing generated image assets are expected and should be reported as a limitation rather than repaired.

## Query

Run this query:

```text
<INSERT QUERY HERE>
```

Use:

```bash
tracecite search "<INSERT QUERY HERE>" \
  --database /mnt/data/tracecite.sqlite \
  --model-cache-dir "<identified model-cache path>" \
  --limit 10
```

Save the complete JSON output under:

```text
/mnt/data/tracecite-query/query-results.json
```

For the three most relevant results:

1. report the search provenance, source path, physical PDF page and heading;
2. retrieve the complete retained page text with `tracecite page`;
3. save each retrieved page as a separate text file;
4. distinguish source statements from your own inference;
5. do not treat ranking score as verification of a claim.

## Final response

Report:

* exact materialised environment path;
* Python and TraceCite versions;
* identified embedding-model path;
* database quick-check result;
* table row counts;
* exact query executed;
* concise summary of the strongest results;
* links to the JSON output and retrieved page-text files;
* limitations, especially absent generated image assets.

Do not spend time repairing optional image assets, rebuilding the database, synchronising source files or running unrelated runtimes.
