import numpy as np
import pandas as pd

from sklearn.cluster import DBSCAN

EARTH_RADIUS_KM = 6371.0

def spatial_clustering(X: np.ndarray, min_samples: int = 1, eps_km: float = 5.0) -> np.ndarray:
    """Applies DBSCAN clustering to spatial coordinates using the haversine metric."""
    # Calculate epsilon in radians
    eps_rad = eps_km / EARTH_RADIUS_KM

    # Apply DBSCAN with haversine metric
    spatial_dbscan = DBSCAN(eps=eps_rad, min_samples=min_samples, metric="haversine")
    
    # Fit and predict cluster labels
    clusters = spatial_dbscan.fit_predict(X)

    return clusters

def identify_sequences(
    df: pd.DataFrame,
    incidence_angle_threshold: float = 3.0,
    min_sequence_length: int = 2,
) -> pd.DataFrame:
    """
    Identify sequences from a spatially clustered DataFrame.

    Expects columns: spatial_cluster, orbital_plane, orbit_state,
    observation_direction, incidence_angle, datetime_parsed.
    """
    result = df.copy()
    result["sequence_id"] = None
    result["sequence_order"] = np.nan
    result["sequence_length"] = np.nan

    seq_counter = 0
    group_keys = ["spatial_cluster", "orbital_plane", "orbit_state", "observation_direction"]

    for _, group in result.groupby(group_keys):
        labels = DBSCAN(
            eps=incidence_angle_threshold,
            min_samples=min_sequence_length,
        ).fit_predict(group["incidence_angle"].values.reshape(-1, 1))

        for label in set(labels) - {-1}:
            seq_indices = group.index[labels == label]
            if len(seq_indices) < min_sequence_length:
                continue

            seq_counter += 1
            ordered = result.loc[seq_indices].sort_values("datetime_parsed")
            result.loc[ordered.index, "sequence_id"] = f"SEQ_{seq_counter:04d}"
            result.loc[ordered.index, "sequence_order"] = range(1, len(ordered) + 1)
            result.loc[ordered.index, "sequence_length"] = len(ordered)

    return result

def summarize_sequences(df: pd.DataFrame) -> pd.DataFrame:
    """One-row-per-sequence summary with temporal and geometric features."""
    seq = df.dropna(subset=["sequence_id"]).sort_values("datetime_parsed")

    agg = seq.groupby("sequence_id").agg(
        sequence_length=("collect_id", "count"),
        first_acquisition=("datetime_parsed", "min"),
        last_acquisition=("datetime_parsed", "max"),
        center_lat_mean=("center_lat", "mean"),
        center_lon_mean=("center_lon", "mean"),
        incidence_angle_mean=("incidence_angle", "mean"),
        incidence_angle_std=("incidence_angle", "std"),
        n_platforms=("platform", "nunique"),
        platforms=("platform", lambda x: ", ".join(sorted(x.unique()))),
        orbital_plane=("orbital_plane", "first"),
        orbit_state=("orbit_state", "first"),
        observation_direction=("observation_direction", "first"),
    )

    agg["time_span_days"] = (agg["last_acquisition"] - agg["first_acquisition"]).dt.total_seconds() / 86400

    return agg.reset_index()