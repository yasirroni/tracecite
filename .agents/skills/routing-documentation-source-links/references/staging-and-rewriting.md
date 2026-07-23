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

Rewrite only Markdown link reference definitions or narrow inline PDF links
whose destination resolves to a mapped local PDF:

```markdown
[label]: ../../../sources/aemo/report.pdf#page=14
```

The inline form is deliberately narrow:

```markdown
[descriptive text](../../../sources/aemo/report.pdf#page=14)
```

The destination must be whitespace-free, repository-relative, unwrapped, have
no title or query string, and end in a positive physical `#page=N` fragment.
Multiple recognised links on one line are supported. A source-PDF candidate
with an unsafe path, malformed/non-positive page, or missing registry entry
fails rather than being partially rewritten.

Do not rewrite:

- images, autolinks, remote URLs, links with titles, and unsupported inline syntax;
- code fences using backticks or tildes;
- indented code blocks;
- Documenter raw blocks such as `@raw html`;
- frontmatter, Markdown table rows, generated logs, non-document output, or
  artifacts;
- non-PDF links and ordinary inline links;
- maintained Markdown files in place.

Committed or generated `.md` files inside the staged documentation source tree
are routable documentation inputs. This does not extend routing to generated
logs, non-document output, or artifacts. Markdown tables inside those files
remain byte-identical, including their header, delimiter, and body rows.

A conservative implementation may use a line-oriented state machine, but it must preserve line endings and all untouched bytes where practical. Do not use a broad regular expression over the entire document without fence/raw-block awareness.

## Path resolution

For each candidate definition or inline link:

1. split the destination into base path, query, and fragment;
2. require a positive `#page=N` fragment for source-PDF citations;
3. resolve the base path relative to the Markdown file in the staged tree;
4. translate that path back to the corresponding repository-relative maintained path;
5. find exactly one registry entry whose normalised `local_path` matches;
6. treat the Markdown reference label as opaque; do not decode, validate, or infer a source path from it;
7. validate authority only from the resolved destination's normalised `local_path` plus the positive physical `#page=N` fragment;
8. render the destination for the requested target.

Resolve inline destinations relative to the containing Markdown file, not the
documentation tree root. Do not rewrite inline code, four-space indented code,
frontmatter, backtick/tilde fences (including Documenter raw fences), raw HTML,
or escaped link syntax. Preserve all untouched bytes and the maintained source.

## Target rendering

### Local

Preserve the local destination or recalculate an equivalent path relative to the staged page when staging depth differs. Do not convert it to an absolute filesystem path.

### Public

```text
public_url + original_fragment
```

When `public_url` contains a query string, append the fragment after it:

```text
https://host/report.pdf?rev=abc&lang=en#page=14
```

## Idempotence

Running the same target build twice from unchanged inputs must produce byte-identical staged Markdown. Public staged output must never be used as the next run's source; always restage from maintained Markdown.
