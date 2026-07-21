"""Build docs_jl Documenter site from canonical prose and Julia tutorials."""

using Documenter
using Literate
import Pkg

root = normpath(joinpath(@__DIR__, ".."))
docs_src = joinpath(@__DIR__, "src")
canonical_docs = joinpath(root, "docs")
docs_jl_examples = joinpath(canonical_docs, "examples", "julia")

# Create docs/src directory if needed
mkpath(docs_src)

# Stage shared canonical prose files (excluding Python-only and Quarto artifacts)
function stage_shared_prose()
    excluded_dirs = [".quarto", "build", ".pytest_cache", ".git", ".venv"]
    excluded_files = [r"\.py$", r"_quarto.*\.yml$", r"\.html\.md$"]

    for item in readdir(canonical_docs; join=true)
        basename_item = basename(item)

        # Skip excluded directories
        if basename_item in excluded_dirs
            continue
        end

        # Skip .gitignore at canonical level (add one at docs_jl level if needed)
        if basename_item == ".gitignore"
            continue
        end

        if isdir(item)
            # Copy shared directories (guide/, formats/, examples/julia/)
            if basename_item in ["guide", "formats"]
                target_dir = joinpath(docs_src, basename_item)
                mkpath(target_dir)
                for file in readdir(item; join=true)
                    basename_file = basename(file)
                    # Skip Python files and generated/Quarto artifacts
                    if any(occursin(pattern, basename_file) for pattern in excluded_files)
                        continue
                    end
                    if isfile(file)
                        cp(file, joinpath(target_dir, basename_file); force=true)
                    end
                end
            elseif basename_item == "examples"
                # Copy only Julia examples (exclude Python)
                target_dir = joinpath(docs_src, basename_item)
                julia_examples = joinpath(item, "julia")
                if isdir(julia_examples)
                    mkpath(joinpath(target_dir, "julia"))
                    for file in readdir(julia_examples; join=true)
                        if isfile(file)
                            cp(file, joinpath(target_dir, "julia", basename(file)); force=true)
                        end
                    end
                end
            end
        elseif isfile(item)
            # Copy markdown files
            if endswith(basename_item, ".md")
                # Skip generated retained output
                if !endswith(basename_item, ".html.md")
                    cp(item, joinpath(docs_src, basename_item); force=true)
                end
            end
        end
    end
end

# Generate Literate markdown from Julia tutorial files
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
                execute=false
            )
            push!(generated_pages, generated_md * ".md")
        end
    end
    return generated_pages
end

# Stage shared prose
stage_shared_prose()

# Generate tutorials from Julia Literate sources
julia_tutorials = generate_julia_tutorials()

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

makedocs(
    sitename = "TraceCite",
    pages = pages,
    format = Documenter.HTML(
        prettyurls = get(ENV, "CI", nothing) == "true",
        ansicolor = true,
    ),
    checkdocs = :none,
    doctest = false,
    warnonly = :example_block,
)
