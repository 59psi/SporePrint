"""Predictive model: learns weather→closet correlation from historical data.

Uses simple linear regression (no ML frameworks):
  predicted_indoor_temp = a * outdoor_temp + b * outdoor_humidity + c * hour_of_day + d

Retrains daily from the last 30 days of correlated weather + telemetry data.
Requires 7+ days of data before predictions are available.
"""

import json
import logging
import math
import time

from ..db import get_db

log = logging.getLogger(__name__)

MIN_TRAINING_DAYS = 7
TRAINING_WINDOW_DAYS = 30


async def retrain_models():
    """Rebuild prediction models from recent correlated data. Called daily."""
    training_data = await _build_training_data()
    if not training_data:
        log.info("Prediction: not enough correlated data yet")
        return

    days = len(set(int(d["timestamp"] / 86400) for d in training_data))
    if days < MIN_TRAINING_DAYS:
        log.info("Prediction: only %d days of data, need %d", days, MIN_TRAINING_DAYS)
        return

    # Train temperature model
    temp_model = _fit_linear_regression(
        X=[[d["outdoor_temp"], d["outdoor_humidity"], d["hour"]] for d in training_data],
        y=[d["indoor_temp"] for d in training_data],
    )
    if temp_model:
        await _store_model("temp", temp_model, days, len(training_data))

    # Train humidity model
    humidity_data = [d for d in training_data if d.get("indoor_humidity") is not None]
    if humidity_data:
        hum_model = _fit_linear_regression(
            X=[[d["outdoor_temp"], d["outdoor_humidity"], d["hour"]] for d in humidity_data],
            y=[d["indoor_humidity"] for d in humidity_data],
        )
        if hum_model:
            await _store_model("humidity", hum_model, days, len(humidity_data))

    log.info("Prediction models retrained: %d days, %d samples", days, len(training_data))


async def predict_indoor_conditions(forecast: list[dict]) -> list[dict]:
    """Given hourly forecast entries, predict indoor temp/humidity for each hour."""
    temp_model = await _load_latest_model("temp")
    humidity_model = await _load_latest_model("humidity")

    if not temp_model:
        return []

    predictions = []
    for entry in forecast:
        ts = entry.get("timestamp", 0)
        hour = int((ts % 86400) / 3600)
        outdoor_temp = entry.get("temp_f", 72)
        outdoor_hum = entry.get("humidity", 50)

        predicted_temp = _predict(temp_model, outdoor_temp, outdoor_hum, hour)
        predicted_hum = _predict(humidity_model, outdoor_temp, outdoor_hum, hour) if humidity_model else None

        predictions.append({
            "forecast_time": ts,
            "predicted_indoor_temp_f": round(predicted_temp, 1),
            "predicted_indoor_humidity": round(predicted_hum, 1) if predicted_hum is not None else None,
            "outdoor_temp_f": outdoor_temp,
            "outdoor_humidity": outdoor_hum,
        })

    return predictions


async def get_model_status() -> dict:
    """Return info about current prediction models for the UI."""
    temp_model = await _load_latest_model("temp")
    humidity_model = await _load_latest_model("humidity")

    if not temp_model:
        # Count how many days of data we have
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT COUNT(DISTINCT CAST(timestamp / 86400 AS INT)) as days FROM weather_readings"
            )
            row = await cursor.fetchone()
            days = row["days"] if row else 0
        return {
            "status": "learning",
            "days_collected": days,
            "days_needed": MIN_TRAINING_DAYS,
        }

    return {
        "status": "active",
        "temp_model": {
            "r_squared": temp_model.get("r_squared"),
            "training_days": temp_model.get("training_days"),
            "training_samples": temp_model.get("training_samples"),
        },
        "humidity_model": {
            "r_squared": humidity_model.get("r_squared"),
            "training_days": humidity_model.get("training_days"),
            "training_samples": humidity_model.get("training_samples"),
        } if humidity_model else None,
    }


# ── Training data ──────────────────────────────────────────────


async def _build_training_data() -> list[dict]:
    """Join weather_readings with telemetry_readings on timestamp (±5min window).

    Returns hourly-averaged data points with outdoor + indoor conditions.
    """
    cutoff = time.time() - TRAINING_WINDOW_DAYS * 86400
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT
                 CAST(w.timestamp / 3600 AS INT) * 3600 as hour_ts,
                 AVG(w.temp_f) as outdoor_temp,
                 AVG(w.humidity) as outdoor_humidity,
                 AVG(t_temp.value) as indoor_temp,
                 AVG(t_hum.value) as indoor_humidity
               FROM weather_readings w
               LEFT JOIN telemetry_readings t_temp
                 ON t_temp.sensor = 'temp_f'
                 AND ABS(t_temp.timestamp - w.timestamp) < 300
               LEFT JOIN telemetry_readings t_hum
                 ON t_hum.sensor = 'humidity'
                 AND ABS(t_hum.timestamp - w.timestamp) < 300
               WHERE w.timestamp > ?
                 AND t_temp.value IS NOT NULL
               GROUP BY hour_ts
               ORDER BY hour_ts""",
            (cutoff,),
        )
        rows = await cursor.fetchall()

    return [
        {
            "timestamp": row["hour_ts"],
            "hour": int((row["hour_ts"] % 86400) / 3600),
            "outdoor_temp": row["outdoor_temp"],
            "outdoor_humidity": row["outdoor_humidity"] or 50,
            "indoor_temp": row["indoor_temp"],
            "indoor_humidity": row["indoor_humidity"],
        }
        for row in rows
        if row["indoor_temp"] is not None
    ]


# ── Linear regression (no numpy needed) ───────────────────────


def _fit_linear_regression(X: list[list[float]], y: list[float]) -> dict | None:
    """Fit y = a*x1 + b*x2 + c*x3 + d using ordinary least squares.

    Returns {"coefficients": [a, b, c, d], "r_squared": float} or None if insufficient data.
    """
    n = len(y)
    if n < 10:
        return None

    # Add bias column (intercept)
    X_aug = [row + [1.0] for row in X]
    p = len(X_aug[0])  # number of parameters

    # X^T * X
    XtX = [[sum(X_aug[k][i] * X_aug[k][j] for k in range(n)) for j in range(p)] for i in range(p)]
    # X^T * y
    Xty = [sum(X_aug[k][i] * y[k] for k in range(n)) for i in range(p)]

    # Solve via Gaussian elimination
    coeffs = _solve_linear_system(XtX, Xty)
    if coeffs is None:
        return None

    # R-squared
    y_mean = sum(y) / n
    ss_tot = sum((yi - y_mean) ** 2 for yi in y)
    ss_res = sum((y[i] - sum(X_aug[i][j] * coeffs[j] for j in range(p))) ** 2 for i in range(n))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    return {
        "coefficients": [round(c, 6) for c in coeffs],
        "r_squared": round(r_squared, 4),
    }


def _solve_linear_system(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Solve Ax = b using Gaussian elimination with partial pivoting."""
    n = len(b)
    # Augmented matrix
    M = [A[i][:] + [b[i]] for i in range(n)]

    for col in range(n):
        # Partial pivoting
        max_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[max_row] = M[max_row], M[col]

        if abs(M[col][col]) < 1e-10:
            return None  # Singular

        # Eliminate below
        for row in range(col + 1, n):
            factor = M[row][col] / M[col][col]
            for j in range(col, n + 1):
                M[row][j] -= factor * M[col][j]

    # Back substitution
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))) / M[i][i]

    return x


def _predict(model: dict, outdoor_temp: float, outdoor_humidity: float, hour: int) -> float:
    """Predict indoor value using stored model coefficients."""
    coeffs = model["coefficients"]
    return coeffs[0] * outdoor_temp + coeffs[1] * outdoor_humidity + coeffs[2] * hour + coeffs[3]


# ── Model storage ──────────────────────────────────────────────


async def _store_model(model_type: str, model: dict, training_days: int, training_samples: int):
    async with get_db() as db:
        await db.execute(
            """INSERT INTO prediction_models (model_type, coefficients, r_squared, training_days, training_samples)
               VALUES (?, ?, ?, ?, ?)""",
            (model_type, json.dumps(model["coefficients"]), model["r_squared"],
             training_days, training_samples),
        )
        await db.commit()


async def _load_latest_model(model_type: str) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM prediction_models WHERE model_type = ? ORDER BY created_at DESC LIMIT 1",
            (model_type,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "coefficients": json.loads(row["coefficients"]),
            "r_squared": row["r_squared"],
            "training_days": row["training_days"],
            "training_samples": row["training_samples"],
        }
