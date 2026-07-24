"""Build docs_jl Documenter site from its own bootstrap-managed prose and Julia tutorials."""

using Documenter
using Literate
import Pkg

docs_src = joinpath(@__DIR__, "src")
docs_jl_examples = joinpath(docs_src, "examples", "julia")

# Create docs/src directory if needed
mkpath(docs_src)

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
