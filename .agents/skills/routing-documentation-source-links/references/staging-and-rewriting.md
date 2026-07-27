# Staging and Rewriting

## Atomic staging sequence

```text
validate registry
create fresh temporary staging directory
copy maintained source tree
rewrite target-specific definitions in the temporary tree
validate transformed tree
rename old staging tree aside
atomically rename temporary tree to final staging path
remove old staging tree after success
```

If any step fails, delete the temporary candidate and preserve the previous valid staging tree.

## Allowed transformation surface

Rewrite only Markdown link reference definitions or narrow inline links whose
destination resolves to a mapped local `.pdf` or `.md` source.

PDF destinations require a positive `#page=N` fragment:

```markdown
[label]: ../../../sources/aemo/report.pdf#page=14
```

```markdown
[descriptive text](../../../sources/aemo/report.pdf#page=14)
```

Mapped Markdown destinations use `relative.md` or `relative.md#anchor`:

```markdown
[label]: ../guide/searchable-evidence.md#anchor
```

```markdown
[descriptive text](../guide/searchable-evidence.md)
```

The destination must be whitespace-free, repository-relative, unwrapped, and
have no title or query string. A PDF candidate must end in a positive
physical `#page=N` fragment. A Markdown candidate must end in `.md`, with at
most one `#anchor` fragment carried through verbatim. Multiple recognised
links on one line are supported.

A PDF candidate with an unsafe path, malformed/non-positive page, or missing
registry entry fails rather than being partially rewritten. A Markdown
candidate behaves more conservatively: only a destination that both parses
cleanly (no query string, no angle-bracket wrapping, no remote scheme, exactly
one optional non-empty anchor, and a `.md` extension) and resolves to exactly
one registered entry is rewritten; every other `.md`-shaped destination
(malformed, escaping, absolute, query-bearing, or simply unmapped) is left
untouched rather than erroring, because most Markdown links are ordinary
documentation navigation rather than source citations.

Do not rewrite:

- images, autolinks, remote URLs, links with titles, and unsupported inline syntax;
- code fences using backticks or tildes;
- indented code blocks;
- Documenter raw blocks such as `@raw html`;
- frontmatter, Markdown table rows, generated logs, non-document output, or
  artifacts;
- links that do not resolve to a registered `.pdf`/`.md` entry;
- maintained Markdown files in place.

Committed or generated `.md` files inside the staged documentation source tree
are routable documentation inputs. This does not extend routing to generated
logs, non-document output, or artifacts. Markdown tables inside those files
remain byte-identical, including their header, delimiter, and body rows.

A conservative implementation may use a line-oriented state machine, but it must preserve line endings and all untouched bytes where practical. Do not use a broad regular expression over the entire document without fence/raw-block awareness.

## Path resolution

For each candidate definition or inline link:

1. split the destination into base path, query, and fragment;
2. for a PDF candidate, require a positive `#page=N` fragment; for a Markdown candidate, accept an optional non-empty `#anchor`;
3. resolve the base path relative to the Markdown file in the staged tree;
4. translate that path back to the corresponding repository-relative maintained path;
5. find exactly one registry entry whose normalised `local_path` matches (a PDF miss/ambiguity fails; a Markdown miss simply means "not a routing candidate," so leave it untouched);
6. treat the Markdown reference label as opaque; do not decode, validate, or infer a source path from it;
7. validate authority only from the resolved destination's normalised `local_path` plus the fragment (positive physical `#page=N` for PDF, verbatim `#anchor` for Markdown);
8. render the destination for the requested target.

Resolve inline destinations relative to the containing Markdown file, not the
documentation tree root. Do not rewrite inline code, four-space indented code,
frontmatter, backtick/tilde fences (including Documenter raw fences), raw HTML,
or escaped link syntax. Preserve all untouched bytes and the maintained source.

## Target rendering

### Local

Preserve the local destination or recalculate an equivalent path relative to the staged page when staging depth differs. Do not convert it to an absolute filesystem path. The fragment (`#page=N` or `#anchor`, if any) is carried through unchanged.

### Public

```text
public_url + original_fragment
```

When `public_url` contains a query string, append the fragment after it:

```text
https://host/report.pdf?rev=abc&lang=en#page=14
https://host/guide/searchable-evidence/?rev=abc#anchor
```

A bare Markdown destination with no authored anchor appends no fragment at all.

## Idempotence

Running the same target build twice from unchanged inputs must produce byte-identical staged Markdown. Public staged output must never be used as the next run's source; always restage from maintained Markdown.
