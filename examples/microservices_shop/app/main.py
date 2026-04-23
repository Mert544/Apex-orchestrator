from app.services import OrderService, InventoryClient, NotificationService

app_name = "microservices-shop"


def main() -> dict[str, Any]:
    order_svc = OrderService()
    inventory = InventoryClient()
    notifier = NotificationService()

    result = order_svc.create_order(
        user_id="user-123",
        product_id="prod-456",
        quantity=2,
        shipping_address="123 Main St",
        billing_address="123 Main St",
        payment_token="tok_visa",
        discount_code="SAVE20",
        metadata={},
    )
    stock = inventory.fetch_stock("prod-456")
    return {"order": result, "stock": stock}
