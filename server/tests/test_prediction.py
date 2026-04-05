"""Tests for the predictive model: linear regression, training, prediction."""

import time

from app.weather.prediction import (
    _fit_linear_regression,
    _solve_linear_system,
    _predict,
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


async def test_predict_indoor_no_model():
    """Without a trained model, returns empty list."""
    forecast = [{"timestamp": time.time() + 3600, "temp_f": 90, "humidity": 50}]
    result = await predict_indoor_conditions(forecast)
    assert result == []


async def test_model_status_learning():
    status = await get_model_status()
    assert status["status"] == "learning"
    assert "days_collected" in status


async def test_retrain_no_data():
    """Retrain with no data should not crash."""
    await retrain_models()
