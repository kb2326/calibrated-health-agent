"""Live Google Health API tools — the read endpoints the loops don't use.

The ingestion loops only need `dataPoints.list`, `dailyRollUp`, and `rollUp`.
The API exposes ten further read methods, and these wrap the ones an agent
can actually act on: who the account is, which devices feed it, and the
reconciled view across sources.

Everything routes through `client._read`, so the allowlist applies here
exactly as it does everywhere else — a write cannot be issued from a tool
even by accident.
"""
from __future__ import annotations

from health_data import client


def _points_api():
    return client.service().users().dataTypes().dataPoints()


def get_health_identity() -> dict:
    """The stable Health user id for the authorised account.

    Distinct from an email address: this is the id webhook notifications are
    keyed by, so it is what links a push notification back to stored data.

    Returns:
        dict: `identity` from the API, or `error` with the reason.
    """
    try:
        return {"identity": client._read(
            "getIdentity", client.service().users().getIdentity(name="users/me/identity")
        )}
    except Exception as e:
        return {"error": str(e)[:300]}


def list_devices() -> dict:
    """Devices paired to the account and feeding it data.

    Useful when readings disagree: the substrate has seen both a Fitbit and
    Apple HealthKit writing the same metric with different conventions.

    Returns:
        dict: `devices`, or `error`. Requires the settings.readonly scope —
        an error mentioning scopes means it was never granted.
    """
    try:
        return {"devices": client.list_paired_devices()}
    except Exception as e:
        return {"error": str(e)[:300]}


def get_health_profile() -> dict:
    """Account profile — the demographics the API holds.

    Returns:
        dict: `profile`, or `error`. Requires the profile.readonly scope.
    """
    try:
        return {"profile": client.get_profile()}
    except Exception as e:
        return {"error": str(e)[:300]}


def reconcile_data_type(metric: str, since_date: str) -> dict:
    """Changes to one metric since a date, across every contributing source.

    `dataPoints.reconcile` returns the reconciled stream rather than one
    source's view, which is how to check whether two platforms disagree
    about the same day.

    Args:
        metric: Exact data type, e.g. "heart-rate".
        since_date: ISO date, e.g. "2026-08-14".

    Returns:
        dict: `changes` and `n`, or `error`.
    """
    try:
        resp = client._read(
            "dataPoints.reconcile",
            _points_api().reconcile(
                parent=f"users/me/dataTypes/{metric}",
                filter=client.build_filter(
                    metric, f"{since_date}T00:00:00Z",
                    f"{since_date[:8]}{int(since_date[8:10]) + 1:02d}T00:00:00Z",
                ),
            ),
        )
        changes = resp.get("dataPoints", resp.get("changes", []))
        return {"metric": metric, "changes": changes[:100], "n": len(changes)}
    except Exception as e:
        return {"error": str(e)[:300]}


def sources_for_metric(metric: str) -> dict:
    """Which devices or platforms have written this metric, and how they differ.

    Reads the stored provenance rather than the API. Divergent means per
    source is the signal that two platforms are measuring differently — the
    case that produced a false alert when Apple reported HRV as SDNN while
    Fitbit reported RMSSD.

    Args:
        metric: Exact data type, e.g. "heart-rate-variability".

    Returns:
        dict: `sources` is [{source, n, mean, min, max}].
    """
    import sqlite3

    from health_data import db

    conn = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("""
            SELECT source, COUNT(*) AS n, ROUND(AVG(value),2) AS mean,
                   ROUND(MIN(value),2) AS min, ROUND(MAX(value),2) AS max
            FROM raw_points WHERE data_type = ? AND value IS NOT NULL
            GROUP BY source ORDER BY n DESC
        """, (metric,))]
    finally:
        conn.close()
    return {"metric": metric, "sources": rows, "n": len(rows)}
