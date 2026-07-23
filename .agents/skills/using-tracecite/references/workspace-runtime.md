# Runtime Contract

This skill is the control-plane interface for a TraceCite installation. The
packaged skill does not bundle the executable, its Python environment, or its
embedding-model cache.

## Resolve runtime inputs

Identify the source root, configuration or manifest, database, model-cache
directory, and installed console script before running a command. Fail clearly
if the executable or any required input is absent:

```bash
command -v tracecite
test -f <manifest-or-config>
test -d <source-root>
```

## Invocation

Invoke the installed console script explicitly:

```bash
tracecite <command> --database <db> --model-cache-dir <cache> ...
```

For configuration-driven operations:

```bash
tracecite sync --config <config-path>
```

The caller owns runtime paths and may keep them outside the repository. Do not
execute a source entry module directly or rely on imports from an unrelated
checkout.

## Compatibility checks

Before depending on `--source-links`, confirm that the installed verifier
supports the final schema-v2 `[[source]]` registry owned by
`routing-documentation-source-links`. Do not silently generate the obsolete
temporary `[sources]` shape. If the verifier has not yet been reconciled, omit
`--source-links`, report the missing compatibility patch, and continue only
with database/local-path verification.
