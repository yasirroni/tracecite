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

@testset "captionless knowledge table" begin
    table = DataFrame(place = ["North"], temperature = [50.7])
    rendered = knowledge_table(table; table_id = "tbl-captionless-julia")
    @test occursin("\"table_id\":\"tbl-captionless-julia\"", rendered)
    @test !occursin("\n: ", rendered)
end

@testset "captioned knowledge table" begin
    table = DataFrame(place = ["North"], temperature = [50.7])
    rendered = knowledge_table(
        table;
        table_id = "tbl-captioned-julia",
        caption = "Highest event.",
    )
    @test occursin(": Highest event. {#tbl-captioned-julia}", rendered)
end

@testset "first-row findings" begin
    table = DataFrame(
        technology = ["Solar PV"],
        capital_cost = [1250.0],
        status = ["firm"],
    )
    rendered = knowledge_table(
        table;
        table_id = "tbl-natural-summary-julia",
        labels = Dict(
            "capital_cost" => "Capital cost (\$/kW)",
            "status" => "Status",
        ),
        formats = Dict("capital_cost" => ".2f"),
        units = Dict("capital_cost" => "\$/kW"),
        summary = ["technology", "capital_cost", "status"],
    )
    @test occursin(
        raw"**First-row finding.** For **Solar PV**, capital cost ($/kW) is **1250.00 \$/kW** and status is **firm**.",
        rendered,
    )
    @test computed_first_row_summary(table; columns = ["status"]) ==
        "**First-row finding.** Status is **firm**."
    @test computed_first_row_summary(table; columns = String[]) ==
        "**First-row finding.** No fields were selected."
    @test computed_first_row_summary(
        table;
        title = "Legacy title",
        columns = ["status"],
    ) ==
        "**First-row finding.** Status is **firm**."
    empty = DataFrame(status = String[])
    @test computed_first_row_summary(empty; columns = ["status"]) ==
        "**First-row finding.** The table contains no rows."
    @test occursin(
        "**First-row finding.** No fields were selected.",
        knowledge_table(
            table;
            table_id = "tbl-empty-summary-julia",
            summary = String[],
        ),
    )
end
