from app.api.router import handle_checkout


def main() -> dict:
    payload = {
        "user_id": "user-123",
        "cart_total": 129.99,
        "items": ["book", "pen"],
    }
    return handle_checkout(payload)


if __name__ == "__main__":
    print(main())
