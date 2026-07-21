module TraceCite

using Dates
using JSON3
using Printf
using Tables

export computed_first_row_summary, knowledge_table, table_metadata_comment

const TABLE_ID_RE = r"^[A-Za-z][A-Za-z0-9_.:-]*$"

"""Return one safe Pandoc Markdown table with optional caption and metadata."""
function knowledge_table(
    table;
    table_id::AbstractString,
    caption::Union{Nothing, AbstractString} = nothing,
    columns = nothing,
    labels = Dict(),
    formats = Dict(),
    units = Dict(),
    ordering = nothing,
    row_identity = String[],
    description = nothing,
    summary = false,
)
    occursin(TABLE_ID_RE, table_id) || throw(ArgumentError(
        "table_id must start with a letter and contain only letters, digits, underscore, dot, colon, or hyphen",
    ))

    source = Tables.columntable(table)
    available = string.(propertynames(source))
    selected = columns === nothing ? available : string.(columns)
    label_map = _string_dict(labels)
    format_map = _value_dict(formats)
    unit_map = _string_dict(units)
    identity = string.(row_identity)

    _require_columns(available, selected)
    _require_known_keys("labels", label_map, selected)
    _require_known_keys("formats", format_map, selected)
    _require_known_keys("units", unit_map, selected)
    _require_columns(available, identity)

    display_headers = [get(label_map, column, _humanise(column)) for column in selected]
    length(unique(display_headers)) == length(display_headers) ||
        throw(ArgumentError("Displayed column labels must be unique"))

    column_values = [collect(getproperty(source, Symbol(column))) for column in selected]
    row_count = isempty(column_values) ? 0 : length(first(column_values))
    all(length(values) == row_count for values in column_values) ||
        throw(ArgumentError("Table columns have inconsistent lengths"))

    rendered_rows = [
        [
            _escape_cell(_format_value(column_values[index][row], get(format_map, column, nothing)))
            for (index, column) in enumerate(selected)
        ]
        for row in 1:row_count
    ]
    numeric = [_is_numeric_column(values) for values in column_values]

    metadata = table_metadata_comment(
        table_id = caption === nothing ? table_id : nothing,
        description = description,
        ordering = ordering,
        units = Dict(
            get(label_map, column, _humanise(column)) => unit
            for (column, unit) in unit_map
        ),
        row_identity = [get(label_map, column, _humanise(column)) for column in identity],
    )

    parts = String[]
    !isempty(metadata) && append!(parts, [metadata, ""])
    append!(parts, _pipe_table(display_headers, rendered_rows, numeric))
    caption !== nothing && append!(parts, ["", ": $(caption) {#$(table_id)}"])

    if summary !== false
        summary_columns = summary === true ? selected : string.(summary)
        _require_columns(available, summary_columns)
        append!(parts, [
            "",
            computed_first_row_summary(
                table;
                columns = summary_columns,
                labels = label_map,
                units = unit_map,
                formats = format_map,
            ),
        ])
    end
    return join(parts, "\n")
end

"""Return an optional invisible TraceCite metadata comment for the next table."""
function table_metadata_comment(;
    table_id = nothing,
    description = nothing,
    ordering = nothing,
    labels = Dict(),
    units = Dict(),
    row_identity = String[],
)
    payload = Dict{String, Any}()
    _put_nonempty!(payload, "description", description)
    _put_nonempty!(payload, "table_id", table_id)
    _put_nonempty!(payload, "ordering", ordering)
    !isempty(labels) && (payload["labels"] = _string_dict(labels))
    !isempty(units) && (payload["units"] = _string_dict(units))
    !isempty(row_identity) && (payload["row_identity"] = string.(row_identity))
    isempty(payload) && return ""
    return "<!-- tracecite-table: $(JSON3.write(payload)) -->"
end

"""Describe the first row using only values computed in the supplied table."""
function computed_first_row_summary(
    table;
    title = nothing,
    columns = nothing,
    labels = Dict(),
    units = Dict(),
    formats = Dict(),
    prefix::AbstractString = "First-row finding",
)
    title = nothing
    source = Tables.columntable(table)
    available = string.(propertynames(source))
    selected = columns === nothing ? available : string.(columns)
    _require_columns(available, selected)

    isempty(selected) && return "**$(prefix).** No fields were selected."
    first_column = collect(getproperty(source, Symbol(first(selected))))
    isempty(first_column) && return "**$(prefix).** The table contains no rows."

    label_map = _string_dict(labels)
    unit_map = _string_dict(units)
    format_map = _value_dict(formats)
    fields = Tuple{String, String}[]
    for column in selected
        values = collect(getproperty(source, Symbol(column)))
        label = get(label_map, column, _humanise(column))
        value = _format_value(first(values), get(format_map, column, nothing))
        if haskey(unit_map, column) && value != "not available"
            value = "$(value) $(unit_map[column])"
        end
        push!(fields, (label, _escape_inline(value)))
    end
    length(fields) == 1 && return "**$(prefix).** $(_upper_initial(first(fields)[1])) is **$(first(fields)[2])**."
    subject = first(fields)[2]
    predicates = ["$(_lower_initial(label)) is **$(value)**" for (label, value) in fields[2:end]]
    return "**$(prefix).** For **$(subject)**, $(_join_fields(predicates))."
end

function _pipe_table(headers, rows, numeric)
    escaped_headers = _escape_cell.(headers)
    header = "| " * join(escaped_headers, " | ") * " |"
    separator = "| " * join([value ? "---:" : ":---" for value in numeric], " | ") * " |"
    body = ["| " * join(row, " | ") * " |" for row in rows]
    return [header, separator, body...]
end

function _format_value(value, formatter = nothing)
    ismissing(value) && return "not available"
    if formatter isa Function
        return string(formatter(value))
    elseif formatter isa AbstractString
        spec = startswith(formatter, "%") ? formatter : "%$(formatter)"
        return Printf.format(Printf.Format(spec), value)
    elseif value isa Date || value isa DateTime
        return string(value)
    elseif value isa AbstractFloat
        return @sprintf("%g", value)
    end
    return string(value)
end

function _escape_cell(value)
    text = replace(string(value), "&" => "&amp;", "<" => "&lt;", ">" => "&gt;")
    for character in ("\\", "|", "\$", "*", "_", "~", "`", "[", "]")
        text = replace(text, character => "\\$(character)")
    end
    return text
end

function _escape_inline(value)
    text = string(value)
    for character in ("\\", "\$", "*", "_", "~", "`", "[", "]", "<", ">")
        text = replace(text, character => "\\$(character)")
    end
    return text
end

_humanise(name) = strip(replace(string(name), "_" => " "))
_lower_initial(value::AbstractString) = isempty(value) ? String(value) : lowercasefirst(value)
_upper_initial(value::AbstractString) = isempty(value) ? String(value) : uppercasefirst(value)

function _is_numeric_column(values)
    present = [value for value in values if !ismissing(value)]
    return !isempty(present) && all(value isa Number for value in present)
end

function _require_columns(available, columns)
    unknown = [column for column in columns if column ∉ available]
    isempty(unknown) || throw(KeyError("Columns are not present in the table: $(unknown)"))
end

function _require_known_keys(name, values, columns)
    unknown = [column for column in keys(values) if column ∉ columns]
    isempty(unknown) || throw(KeyError("$(name) contains columns not selected for display: $(unknown)"))
end

_string_dict(values) = Dict(string(key) => string(value) for (key, value) in pairs(values))
_value_dict(values) = Dict(string(key) => value for (key, value) in pairs(values))

function _put_nonempty!(payload, key, value)
    value === nothing && return
    text = strip(string(value))
    !isempty(text) && (payload[key] = text)
end

function _join_fields(fields)
    isempty(fields) && return "no selected fields"
    length(fields) == 1 && return first(fields)
    length(fields) == 2 && return "$(fields[1]) and $(fields[2])"
    return join(fields[1:end-1], ", ") * ", and $(last(fields))"
end

end
