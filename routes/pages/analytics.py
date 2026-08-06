import datetime
import math
import altair as alt
import polars as pl

HEADING_TO_WORK = 100.0
HEADING_TO_HOME = 280.0

def get_dashboard_data(db_path):
    # 1. Load data with Polars
    df = pl.read_database_uri(
        query="SELECT * FROM rides WHERE end_time IS NOT NULL",
        uri=f"sqlite://{db_path}",
    )

    if df.is_empty():
        return None, None, None, None

    # 2. Calculate Duration in Minutes
    def parse_duration(s, e):
        start = datetime.datetime.fromisoformat(s)
        end = datetime.datetime.fromisoformat(e)
        diff = end - start
        return diff.total_seconds() / 60

    df = df.with_columns(
        pl.col("start_time").str.to_datetime("%Y-%m-%dT%H:%M:%S+00:00"),
        pl.struct(["start_time", "end_time"])
        .map_elements(
            lambda x: parse_duration(x["start_time"], x["end_time"]),
            return_dtype=pl.Float64,
        )
        .alias("duration_min"),
    )

    # Calculate travel bearing and head wind
    df = df.with_columns(
        pl.when(pl.col("direction").str.to_lowercase().is_in(["work", "inbound"]))
        .then(HEADING_TO_WORK)
        .otherwise(HEADING_TO_HOME)
        .alias("travel_bearing")
    )
    df = df.with_columns(
        (
            pl.col("wind_speed")
            * ((pl.col("wind_dir") - pl.col("travel_bearing")) * math.pi / 180.0).cos()
        ).alias("head_wind")
    )

    # 3. Create Timeline Chart
    timeline_chart = (
        alt.Chart(df)
        .mark_point(size=120, filled=True)
        .encode(
            x=alt.X("start_time", title="Departure time"),
            y=alt.Y("duration_min", title="Duration (Minutes)").scale(zero=False),
            color="route",
            shape="direction",
            tooltip=[
                "route",
                "direction",
                "temp",
                alt.Tooltip("duration_min", format=".1f", title="Minutter"),
                "precip_next_hour",
            ],
        )
        .interactive()
        .properties(width="container", height=400)
    )

    # 4. Create Histograms (six small figures: distribution of times for each route in each direction)
    distributions_chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("duration_min:Q", bin=alt.Bin(maxbins=20), title="Duration (Minutes)"),
            y=alt.Y("count()", title="Number of Rides"),
            color="route:N",
            tooltip=["route:N", "direction:N", alt.Tooltip("duration_min:Q", bin=True, title="Duration Range"), "count()"]
        )
        .properties(width=180, height=120)
        .facet(
            row=alt.Row("route:N", title="Route"),
            column=alt.Column("direction:N", title="Direction")
        )
        .resolve_scale(x="shared", y="shared")
    )

    # 5. Create Scatter Plot (travel time vs. head wind)
    # Ensure we filter out rows with null wind data for the scatter plot
    df_scatter = df.filter(pl.col("head_wind").is_not_null())

    brush = alt.selection_interval(name="brush")
    scatter_chart = (
        alt.Chart(df_scatter)
        .mark_point(size=100, filled=True)
        .encode(
            x=alt.X("head_wind:Q", title="Head Wind (m/s)"),
            y=alt.Y("duration_min:Q", title="Duration (Minutes)").scale(zero=False),
            color=alt.condition(brush, "route:N", alt.value("lightgray")),
            shape="direction:N",
            tooltip=[
                "route",
                "direction",
                alt.Tooltip("duration_min", format=".1f", title="Duration (Min)"),
                alt.Tooltip("head_wind", format=".1f", title="Head Wind (m/s)"),
                alt.Tooltip("wind_speed", format=".1f", title="Wind Speed (m/s)"),
                "wind_dir",
                "temp",
                "precip_next_hour"
            ]
        )
        .add_params(brush)
        .interactive()
        .properties(width="container", height=400)
    )

    # 6. Aggregated Stats
    stats = {
        "total_trips": df.height,
        "rainy_trips": df.filter(pl.col("precip_next_hour") > 0).height,
        "avg_duration": f"{round(df['duration_min'].mean(), 1)}±{round(df['duration_min'].std(), 1)}",
    }

    return timeline_chart.to_json(), distributions_chart.to_json(), scatter_chart.to_json(), stats
