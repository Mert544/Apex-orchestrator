def load_settings() -> dict:
    return {
        "currency": "USD",
        "payment_provider": "stripe-like",
        "payment_api_key": "demo-payment-key",
        "jwt_secret": "demo-secret",
        "email_sender": "noreply@synthetic-shop.local",
    }
