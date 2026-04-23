from __future__ import annotations

import os
import pickle
from typing import Any

# KNOWN ISSUE 1: Hardcoded secret
DATABASE_URL = "postgresql://admin:secret123@localhost:5432/shop"
API_KEY = "sk-live-abc123xyz789"

class OrderService:
    """Handles order processing across microservices."""

    def create_order(self, user_id, product_id, quantity, shipping_address, billing_address, payment_token, discount_code, metadata):
        # KNOWN ISSUE 2: Too many arguments (8 args)
        # KNOWN ISSUE 3: SQL injection via string formatting
        query = f"INSERT INTO orders (user_id, product_id, qty) VALUES ({user_id}, {product_id}, {quantity})"
        return {"query": query, "status": "created"}

    def process_payment(self, data):
        # KNOWN ISSUE 4: Missing docstring, missing type annotations
        # KNOWN ISSUE 5: eval() usage
        config = eval(data["config"])
        return {"paid": True, "config": config}

class InventoryClient:
    def fetch_stock(self, product_id):
        try:
            # KNOWN ISSUE 6: os.system usage
            os.system(f"curl http://inventory-service/stock/{product_id}")
            return {"stock": 100}
        except:  # KNOWN ISSUE 7: bare except
            return {"stock": 0}

class NotificationService:
    def send_alert(self, payload):
        # KNOWN ISSUE 8: pickle.loads on untrusted data
        message = pickle.loads(payload)
        return {"sent": True, "message": message}

def route_request(service_name, action, payload, headers, timeout, retry_count, fallback_url, circuit_breaker):
    # KNOWN ISSUE 9: Too many arguments (8 args)
    # KNOWN ISSUE 10: Missing docstring
    result = eval(action)(payload)
    return {"service": service_name, "result": result}
