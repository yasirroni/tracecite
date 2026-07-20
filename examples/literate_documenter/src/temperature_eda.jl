# # Literate + Documenter HTML table
#
# This source deliberately writes the DataFrame's HTML MIME representation into
# a Documenter raw-HTML block. TraceCite preserves the HTML, converts it to
# canonical Markdown, and sends it through the same table normaliser used for
# Quarto-retained Markdown.

using DataFrames

events = DataFrame(
    rank = [1, 2],
    place = ["Oodnadatta Airport", "Mardie"],
    date = ["1960-01-02", "2022-01-13"],
    temperature_c = [50.7, 50.5],
)

html = sprint(show, MIME"text/html"(), events)
println("```@raw html")
println(html)
println("```")
