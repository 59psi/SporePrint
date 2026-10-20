"""Tests for the predictive model: linear regression, training, prediction."""

import time

from app.db import get_db
from app.weather.prediction import (
    TRAINING_WINDOW_DAYS,
    _build_training_data,
    _fit_linear_regression,
    _solve_linear_system,
    _predict,
    _store_model,
    predict_indoor_conditions,
    get_model_status,
    retrain_models,
)


def test_solve_linear_system():
    # 2x + 3y = 8, x + y = 3 → x=1, y=2
    A = [[2, 3], [1, 1]]
    b = [8, 3]
    x = _solve_linear_system(A, b)
    assert x is not None
    assert abs(x[0] - 1.0) < 0.001
    assert abs(x[1] - 2.0) < 0.001


def test_solve_singular_matrix():
    A = [[1, 2], [2, 4]]  # singular
    b = [3, 6]
    x = _solve_linear_system(A, b)
    assert x is None


def test_fit_linear_regression_simple():
    # y = 2*x1 + 3*x2 + 0.5*x3 + 1
    X = [[i, j, k] for i in range(4) for j in range(4) for k in range(3)]
    y = [2 * x[0] + 3 * x[1] + 0.5 * x[2] + 1 for x in X]
    model = _fit_linear_regression(X, y)
    assert model is not None
    assert model["r_squared"] > 0.99
    coeffs = model["coefficients"]
    assert abs(coeffs[0] - 2.0) < 0.01  # a ≈ 2
    assert abs(coeffs[1] - 3.0) < 0.01  # b ≈ 3


def test_fit_insufficient_data():
    X = [[1, 2, 3]]
    y = [10]
    model = _fit_linear_regression(X, y)
    assert model is None


def test_predict():
    model = {"coefficients": [0.6, -0.1, 0.3, 12.5]}
    result = _predict(model, 90.0, 50.0, 14)
    # 0.6*90 + -0.1*50 + 0.3*14 + 12.5 = 54 - 5 + 4.2 + 12.5 = 65.7
    assert abs(result - 65.7) < 0.01


async def test_with_no_data_there_is_no_model_and_no_prediction():
    """Retraining on an empty history trains nothing; the status stays
    'learning' and a forecast gets no indoor prediction."""
    await retrain_models()
    status = await get_model_status()
    assert status["status"] == "learning"
    assert "days_collected" in status
    forecast = [{"timestamp": time.time() + 3600, "temp_f": 90, "humidity": 50}]
    assert await predict_indoor_conditions(forecast) == []


async def test_training_data_spans_rolled_up_telemetry():
    """Training claimed a 30-day window but joined only RAW
    telemetry, which retention rolls into 5-min buckets (and deletes) after 7
    days — so only ~7 days of samples ever existed. Rolled-up history must
    contribute too."""
    now = time.time()
    hour0 = now - (now % 3600)
    weather_rows, raw_rows, rollup_rows = [], [], []
    for h in range(1, 20 * 24):  # 20 days of hourly outdoor readings
        ts = hour0 - h * 3600
        weather_rows.append((ts, "openmeteo", 50.0 + (h % 24), 60.0))
        indoor = 70.0 + (h % 24) / 10
        if h < 7 * 24:  # still raw
            raw_rows.append((ts + 30, "climate-01", "temp_f", indoor))
            raw_rows.append((ts + 30, "climate-01", "humidity", 85.0))
        else:  # already compressed by retention into 5-min rollups
            bucket = ts - (ts % 300)
            rollup_rows.append((bucket, "climate-01", "temp_f", "5min", indoor, indoor, indoor, 5))
            rollup_rows.append((bucket, "climate-01", "humidity", "5min", 85.0, 85.0, 85.0, 5))

    async with get_db() as db:
        await db.executemany(
            "INSERT INTO weather_readings (timestamp, provider, temp_f, humidity) VALUES (?, ?, ?, ?)",
            weather_rows,
        )
        await db.executemany(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) VALUES (?, ?, ?, ?)",
            raw_rows,
        )
        await db.executemany(
            """INSERT INTO telemetry_rollups
               (timestamp, node_id, sensor, resolution, avg_value, min_value, max_value, count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rollup_rows,
        )
        await db.commit()

    data = await _build_training_data()
    days = {int(d["timestamp"] // 86400) for d in data}
    assert len(days) >= 19, f"only {len(days)} days of training data"
    assert len(days) <= TRAINING_WINDOW_DAYS + 1
    sample = data[0]
    assert sample["indoor_humidity"] == 85.0
    assert 70.0 <= sample["indoor_temp"] <= 72.4


async def _seed_hours(weather_rows, telemetry_rows):
    async with get_db() as db:
        await db.executemany(
            "INSERT INTO weather_readings (timestamp, provider, temp_f, humidity) VALUES (?, ?, ?, ?)",
            weather_rows,
        )
        await db.executemany(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) VALUES (?, ?, ?, ?)",
            telemetry_rows,
        )
        await db.commit()


async def test_a_closet_watched_only_by_integrations_trains_a_model():
    """Integration sensors (Aranet, Pulse, Trane, ...) write temp_c only, and
    training read temp_f alone: such a closet never got a model, so no
    forecast alert could ever fire."""
    now = time.time()
    hour0 = now - (now % 3600)
    weather_rows, telemetry_rows = [], []
    for h in range(1, 9 * 24):
        ts = hour0 - h * 3600
        outdoor = 50.0 + (h % 24)
        weather_rows.append((ts, "openmeteo", outdoor, 60.0 + (h % 7)))
        indoor_f = 60.0 + outdoor / 4 + (h % 5) * 0.1
        telemetry_rows.append((ts + 30, "aranet-1", "temp_c", (indoor_f - 32) * 5 / 9))
        telemetry_rows.append((ts + 30, "aranet-1", "humidity", 85.0 + (h % 3)))
    await _seed_hours(weather_rows, telemetry_rows)

    data = await _build_training_data()
    assert len(data) >= 9 * 24 - 5
    # The hour's temp_c mean, in °F.
    assert all(70.0 <= d["indoor_temp"] <= 79.0 for d in data)

    await retrain_models()
    status = await get_model_status()
    assert status["status"] == "active"
    assert status["temp_model"]["training_samples"] == len(data)


async def test_a_node_publishing_both_units_counts_its_readings_once():
    """The climate node sends temp_f and temp_c for every reading: the hour's
    temp_f mean wins, the temp_c copy is not averaged in."""
    now = time.time()
    ts = now - (now % 3600) - 3600
    await _seed_hours(
        [(ts, "openmeteo", 50.0, 60.0)],
        [(ts + 30, "climate-01", "temp_f", 70.0),
         (ts + 30, "climate-01", "temp_c", 30.0)],  # disagreeing on purpose
    )
    [sample] = await _build_training_data()
    assert sample["indoor_temp"] == 70.0


async def test_prediction_skips_a_null_hour_and_assumes_humidity():
    """A provider gap (temp or humidity null) raised TypeError and lost every
    forecast alert of the poll."""
    await _store_model("temp", {"coefficients": [1.0, 0.1, 0.0, 0.0], "r_squared": 0.9}, 10, 240)
    ts = time.time() + 3600
    result = await predict_indoor_conditions([
        {"timestamp": ts, "temp_f": None, "humidity": 40},
        {"timestamp": ts + 3600, "temp_f": 80.0, "humidity": None},
    ])
    assert len(result) == 1
    assert result[0]["predicted_indoor_temp_f"] == 85.0  # 80 + 0.1 * an assumed 50 %
    assert result[0]["outdoor_humidity"] is None
