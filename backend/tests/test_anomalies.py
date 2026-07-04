from __future__ import annotations

from backend.app.analytics.anomalies import detect_anomalies
from backend.app.data.generate import generate_anomaly_truth, generate_readings


def test_anomaly_recall_against_truth() -> None:
    days = 30
    seed = 11
    df = generate_readings(days=days, seed=seed)
    truth = generate_anomaly_truth(days=days, seed=seed)
    detected = detect_anomalies(df, z=2.8)
    detected_pairs = {(item["meter_id"], item["timestamp"]) for item in detected}
    truth_pairs = {(item["meter_id"], item["timestamp"]) for item in truth}
    hits = len(detected_pairs & truth_pairs)
    recall = hits / max(len(truth_pairs), 1)
    assert recall >= 0.6
    assert detected
