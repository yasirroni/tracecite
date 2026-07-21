using Documenter
using Literate

root = normpath(joinpath(@__DIR__, ".."))
source = joinpath(root, "src", "temperature_eda.jl")
generated = joinpath(@__DIR__, "src", "temperature_eda.md")

Literate.markdown(source, dirname(generated); documenter = true, execute = true)

makedocs(
    sitename = "TraceCite Literate/Documenter fixture",
    pages = ["Overview" => "index.md", "Temperature EDA" => "temperature_eda.md"],
)
