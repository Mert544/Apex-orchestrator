"""Intentionally imperfect demo fixture for the Apex static analyzer.

This microservices module deliberately contains known quality and
security defects so Apex's detectors and fix transforms have a realistic
target to find and repair. It is defensive test data that exercises a
code-analysis tool — not production code, and not an exploit.
"""
from __future__ import annotations

import ast
import json
import os
from typing import Any

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/shop")
API_KEY = os.environ.get("API_KEY", "")

class OrderService:
    """Handles order processing across microservices."""

    def create_order(
        self,
        user_id: str,
        product_id: str,
        quantity: int,
        shipping_address: str,
        billing_address: str,
        payment_token: str,
        discount_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new order for the given user and product."""
        # FIXED: Use parameterized query pattern (prepared statement)
        query = "INSERT INTO orders (user_id, product_id, qty) VALUES (?, ?, ?)"
        params = (user_id, product_id, quantity)
        return {"query": query, "params": params, "status": "created"}

    def process_payment(self, data: dict[str, Any]) -> dict[str, Any]:
        """Process payment using the provided configuration."""
        # FIXED: Use ast.literal_eval instead of eval
        config = ast.literal_eval(data["config"])
        return {"paid": True, "config": config}

class InventoryClient:
    """Client for fetching inventory stock levels."""

    def fetch_stock(self, product_id: str) -> dict[str, Any]:
        """Fetch current stock level for a product."""
        try:
            # FIXED: Use requests instead of os.system
            import urllib.request
            req = urllib.request.Request(
                f"http://inventory-service/stock/{product_id}"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return {"stock": int(resp.read())}
        except Exception:
            # FIXED: Bare except -> specific Exception
            return {"stock": 0}

class NotificationService:
    """Service for sending alerts and notifications."""

    def send_alert(self, payload: bytes) -> dict[str, Any]:
        """Send an alert notification."""
        # FIXED: Use json.loads instead of pickle.loads
        message = json.loads(payload.decode("utf-8"))
        return {"sent": True, "message": message}

def route_request(
    service_name: str,
    action: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    retry_count: int = 3,
    fallback_url: str | None = None,
    circuit_breaker: bool = False,
) -> dict[str, Any]:
    """Route a request to the specified service with the given action."""
    # FIXED: Use a registry/dispatch pattern instead of eval
    registry: dict[str, callable] = {}
    handler = registry.get(action)
    if handler is None:
        raise ValueError(f"Unknown action: {action}")
    result = handler(payload)
    return {"service": service_name, "result": result}
