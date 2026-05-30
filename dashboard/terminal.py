from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


def fetch_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return {"error": str(exc)}


def endpoint(base_url: str, path: str, params: dict[str, str | None]) -> str:
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value})
    suffix = f"?{query}" if query else ""
    return f"{base_url.rstrip('/')}{path}{suffix}"


def clear_screen() -> None:
    print("\033[2J\033[H", end="")


def render(
    store_id: str,
    metrics: dict[str, Any],
    funnel: dict[str, Any],
    anomalies: dict[str, Any],
    health: dict[str, Any],
) -> str:
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        "Store Intelligence Live Dashboard",
        "=" * 39,
        f"Store: {store_id}",
        f"Updated: {now}",
        "",
    ]
    if "error" in metrics:
        lines.append(f"API unavailable: {metrics['error']}")
        return "\n".join(lines)

    lines.extend(
        [
            "Live Metrics",
            f"  Unique visitors      : {metrics.get('unique_visitors', 0)}",
            f"  Converted visitors   : {metrics.get('converted_visitors', 0)}",
            f"  Conversion rate      : {metrics.get('conversion_rate', 0)}",
            f"  Queue depth          : {metrics.get('queue_depth', 0)}",
            f"  Abandonment rate     : {metrics.get('abandonment_rate', 0)}",
            f"  Customer events      : {metrics.get('customer_event_count', 0)}",
            "",
            "Funnel",
        ]
    )
    for stage in funnel.get("stages", []):
        lines.append(
            f"  {stage.get('stage', '').ljust(15)} {str(stage.get('count', 0)).rjust(4)} "
            f"dropoff={stage.get('dropoff_from_previous', 0)}"
        )
    if not funnel.get("stages"):
        lines.append("  No funnel events yet.")

    lines.extend(["", "Anomalies"])
    active_anomalies = anomalies.get("anomalies", [])
    if active_anomalies:
        for anomaly in active_anomalies[:5]:
            lines.append(
                f"  {anomaly.get('severity', 'INFO').ljust(8)} {anomaly.get('type', 'UNKNOWN')}"
            )
    else:
        lines.append("  None active.")

    lines.extend(["", "Health"])
    lines.append(f"  Service status       : {health.get('status', 'unknown')}")
    store_health = health.get("stores", {}).get(store_id)
    if store_health:
        lines.append(f"  Last event timestamp : {store_health.get('last_event_timestamp')}")
        lines.append(f"  Feed lag seconds     : {store_health.get('lag_seconds')}")
    else:
        lines.append("  Waiting for first event.")
    lines.extend(["", "Press Ctrl+C to stop."])
    return "\n".join(lines)


def run_dashboard(
    base_url: str,
    store_id: str,
    refresh_seconds: float,
    start: str | None,
    end: str | None,
) -> None:
    params = {"start": start, "end": end}
    while True:
        metrics = fetch_json(endpoint(base_url, f"/stores/{store_id}/metrics", params))
        funnel = fetch_json(endpoint(base_url, f"/stores/{store_id}/funnel", params))
        anomalies = fetch_json(endpoint(base_url, f"/stores/{store_id}/anomalies", params))
        health = fetch_json(endpoint(base_url, "/health", {}))
        clear_screen()
        print(render(store_id, metrics, funnel, anomalies, health), flush=True)
        time.sleep(refresh_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live terminal dashboard for store metrics.")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--store-id", default="ST1008")
    parser.add_argument("--refresh-seconds", type=float, default=1.0)
    parser.add_argument("--start", default="2026-04-10T00:00:00Z")
    parser.add_argument("--end", default="2026-04-11T00:00:00Z")
    args = parser.parse_args()
    try:
        run_dashboard(
            args.api_url,
            args.store_id,
            max(args.refresh_seconds, 0.2),
            args.start,
            args.end,
        )
    except KeyboardInterrupt:
        clear_screen()
        print("Dashboard stopped.")


if __name__ == "__main__":
    main()
