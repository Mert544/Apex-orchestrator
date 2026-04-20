from app.config.settings import load_settings
from app.services.order_service import OrderService


def handle_checkout(payload: dict) -> dict:
    settings = load_settings()
    service = OrderService(settings=settings)
    return service.checkout(payload)
