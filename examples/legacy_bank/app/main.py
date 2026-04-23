from __future__ import annotations

from app.accounts import AccountManager, BatchProcessor

app_name = "legacy-bank"


def main() -> dict[str, Any]:
    mgr = AccountManager()
    batch = BatchProcessor()

    result = mgr.transfer_funds(
        source_account="ACC-001",
        destination_account="ACC-002",
        amount=1000.00,
        currency="USD",
        description="Wire transfer",
        reference_id="REF-12345",
        notify_user=True,
        audit_log=True,
    )
    return {"transfer": result}
