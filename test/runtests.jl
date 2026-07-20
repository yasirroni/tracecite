using Dates
using DataFrames
using Test
using TraceCite

@testset "knowledge_table" begin
    table = DataFrame(
        rank = [1],
        place = ["North | South"],
        date = [Date("1960-01-02")],
        temperature = [50.7],
        note = ["*verified* <draft>"],
    )
    rendered = knowledge_table(
        table;
        caption = "Highest event.",
        table_id = "tbl-highest-julia",
        labels = Dict("temperature" => "Maximum temperature"),
        formats = Dict("temperature" => ".1f"),
        units = Dict("temperature" => "°C"),
        ordering = "maximum temperature descending",
        row_identity = ["place", "date"],
        summary = ["place", "date", "temperature"],
    )
    @test occursin(raw"North \| South", rendered)
    @test occursin(raw"\*verified\* &lt;draft&gt;", rendered)
    @test occursin(": Highest event. {#tbl-highest-julia}", rendered)
    @test occursin("tracecite-table", rendered)
    @test occursin("50.7 °C", rendered)
end
