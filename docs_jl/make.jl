"""Build docs_jl Documenter site from its own bootstrap-managed prose and Julia tutorials."""

using Documenter
using Literate

docs_src = joinpath(@__DIR__, "src")
docs_jl_examples = joinpath(docs_src, "examples", "julia")
documenter_source = joinpath(@__DIR__, ".documenter-source")
literal_dollar_token = "TRACECITELITERALDOLLAR7F3A9C"

# Create docs/src directory if needed
mkpath(docs_src)

function _unquote(value::AbstractString)
    stripped = strip(value)
    if ncodeunits(stripped) >= 2 && first(stripped) == last(stripped) &&
       first(stripped) in ('"', '\'')
        return chop(stripped; head=1, tail=1)
    end
    return stripped
end

"""Translate the canonical Quarto/Jupytext-style Julia page for Literate.jl."""
function quarto_percent_to_literate(content::AbstractString)
    lines = split(content, '\n'; keepempty=true)
    output = String[]
    hide_cell = false
    index = 1
    while index <= length(lines)
        line = lines[index]
        if line == "# %% [markdown]"
            hide_cell = false
            index += 1
            index > length(lines) && error("markdown cell has no content")

            if lines[index] == "# ---"
                title = nothing
                subtitle = nothing
                index += 1
                while index <= length(lines) && lines[index] != "# ---"
                    metadata = replace(lines[index], r"^#\s*" => "")
                    key_value = split(metadata, ":"; limit=2)
                    if length(key_value) == 2
                        key, value = strip(key_value[1]), _unquote(key_value[2])
                        key == "title" && (title = value)
                        key == "subtitle" && (subtitle = value)
                    end
                    index += 1
                end
                index <= length(lines) || error("unterminated Quarto frontmatter")
                title === nothing || push!(output, "# # $(title)")
                subtitle === nothing || append!(output, ["#", "# *$(subtitle)*"])
                index += 1
                continue
            end

            lines[index] == "\"\"\"" || error(
                "markdown cells must contain a triple-quoted prose block",
            )
            index += 1
            while index <= length(lines) && lines[index] != "\"\"\""
                push!(output, isempty(lines[index]) ? "#" : "# " * lines[index])
                index += 1
            end
            index <= length(lines) || error("unterminated markdown prose block")
            index += 1
            continue
        elseif startswith(line, "# %%")
            hide_cell = false
            index += 1
            continue
        elseif startswith(line, "#|")
            hide_cell = strip(line) == "#| include: false"
            index += 1
            continue
        end

        if hide_cell && !isempty(strip(line)) && !startswith(strip(line), "#")
            push!(output, line * " # hide")
        else
            push!(output, line)
        end
        index += 1
    end
    return join(output, "\n")
end

# Generate Documenter-flavoured Literate markdown from Julia tutorial files.
function generate_julia_tutorials()
    julia_src = joinpath(docs_jl_examples)
    if !isdir(julia_src)
        @warn "No Julia examples directory found at $julia_src"
        return String[]
    end

    generated_pages = String[]
    for file in sort(readdir(julia_src))
        if endswith(file, ".jl")
            source = joinpath(julia_src, file)
            generated_md = replace(file, ".jl" => "")

            # Generate Markdown from Literate
            Literate.markdown(
                source,
                docs_src;
                name=generated_md,
                documenter=true,
                execute=false,
                preprocess=quarto_percent_to_literate,
            )
            push!(generated_pages, generated_md * ".md")
        end
    end
    return generated_pages
end

"""Remove Quarto YAML frontmatter from a Markdown page for Documenter."""
function strip_quarto_frontmatter(content::AbstractString)
    lines = split(content, '\n'; keepempty=true)
    isempty(lines) && return String(content)
    strip(first(lines)) == "---" || return String(content)

    closing = findnext(line -> strip(line) == "---", lines, 2)
    closing === nothing && error("unterminated Quarto frontmatter")
    first_body_line = closing + 1
    while first_body_line <= length(lines) && isempty(strip(lines[first_body_line]))
        first_body_line += 1
    end
    return first_body_line > length(lines) ? "" : join(lines[first_body_line:end], "\n")
end

# Generate tutorials from Julia Literate sources
julia_tutorials = generate_julia_tutorials()

"""Prepare a renderer-specific copy without changing bootstrap-managed source."""
function prepare_documenter_source()
    rm(documenter_source; recursive=true, force=true)
    cp(docs_src, documenter_source; force=true)
    for (directory, _, files) in walkdir(documenter_source)
        for file in files
            endswith(file, ".md") || continue
            file == "dirty_dataframe.md" && continue
            path = joinpath(directory, file)
            content = strip_quarto_frontmatter(read(path, String))
            # Quarto/Pandoc consumes `\$` as a literal dollar. Documenter treats
            # unsupported Pandoc table source as preformatted Markdown but still
            # applies Julia interpolation, so use a private build token here.
            write(path, replace(content, raw"\$" => literal_dollar_token))
        end
    end
    return documenter_source
end

function restore_documenter_literals()
    build_root = joinpath(@__DIR__, "build")
    isdir(build_root) || return
    for (directory, _, files) in walkdir(build_root)
        for file in files
            any(suffix -> endswith(file, suffix), (".html", ".js", ".json")) || continue
            path = joinpath(directory, file)
            content = read(path, String)
            write(path, replace(content, literal_dollar_token => string('\$')))
        end
    end
end

prepared_source = prepare_documenter_source()

# Build pages structure
pages = [
    "Overview" => "index.md",
    "Design" => [
        "Architecture" => "guide/architecture.md",
        "From documents to searchable evidence" => "guide/searchable-evidence.md",
        "Python API and CLI" => "guide/api.md",
        "Embedding inspection site" => "guide/embedding-site.md",
    ],
    "Formats" => [
        "Pandoc Markdown tables" => "formats/pandoc-tables.md",
        "Literate and Documenter HTML" => "formats/html-documenter.md",
        "Structural diagnostics" => "formats/diagnostics.md",
    ],
]

if !isempty(julia_tutorials)
    tutorial_pages = [
        "TraceCite with Julia" => "dirty_dataframe.md",
    ]
    push!(pages, "Tutorials" => tutorial_pages)
end

try
    makedocs(
        sitename = "TraceCite",
        source = prepared_source,
        remotes = nothing,
        pages = pages,
        format = Documenter.HTML(
            prettyurls = get(ENV, "CI", nothing) == "true",
            ansicolor = true,
            edit_link = nothing,
            repolink = nothing,
        ),
        checkdocs = :none,
        doctest = false,
    )
    restore_documenter_literals()
finally
    rm(documenter_source; recursive=true, force=true)
end
