import polars as pl
import altair as alt
import datetime


def get_dashboard_data(db_path):
    # 1. Load data with Polars
    # query directly from sqlite
    df = pl.read_database_uri(
        query="SELECT * FROM rides WHERE end_time IS NOT NULL",
        uri=f"sqlite://{db_path}",
    )

    if df.is_empty():
        return None, None

    # 2. Calculate Duration in Minutes
    # We convert strings to time objects and calculate delta
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

    # 3. Create Altair Chart
    alt.themes.enable("carbong90")
    chart = (
        alt.Chart(df)
        .mark_circle(size=80)
        .encode(
            x=alt.X("start_time", title="Departure time"),
            y=alt.Y("duration_min", title="Duration (Minutes)"),
            color="direction",
            tooltip=[
                "route",
                "temp",
                alt.Tooltip("duration_min", format=".1f", title="Minutter"),
                "precip_next_hour",
            ],
        )
        .interactive()
        .properties(width="container", height=400)
    )

    # 4. Aggregated Stats
    stats = {
        "total_trips": df.height,
        "rainy_trips": df.filter(pl.col("precip_next_hour") > 0).height,
        "avg_duration": f'{round(df["duration_min"].mean(), 1)}±{round(df["duration_min"].std(), 1)}',
    }

    return chart.to_json(), stats
