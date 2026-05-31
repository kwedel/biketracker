from core import get_wind_arrow

def test_get_wind_arrow():
    assert get_wind_arrow(0) == "↓"
    assert get_wind_arrow(45) == "↙"
    assert get_wind_arrow(90) == "←"
    assert get_wind_arrow(135) == "↖"
    assert get_wind_arrow(180) == "↑"
    assert get_wind_arrow(225) == "↗"
    assert get_wind_arrow(270) == "→"
    assert get_wind_arrow(315) == "↘"
    assert get_wind_arrow(360) == "↓"
    assert get_wind_arrow(None) == ""

def test_get_wind_arrow_boundaries():
    assert get_wind_arrow(22.4) == "↓"
    assert get_wind_arrow(22.6) == "↙"
    assert get_wind_arrow(337.5) == "↓"
