from __future__ import annotations

import os
import pickle
from typing import Any

# KNOWN ISSUE 1: Hardcoded credentials
DB_PASSWORD = "legacy_bank_123"
ADMIN_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"

class AccountManager:
    """Manages bank accounts and transactions."""

    def transfer_funds(self, source_account, destination_account, amount, currency, description, reference_id, notify_user, audit_log):
        # KNOWN ISSUE 2: Too many arguments (8 args)
        # KNOWN ISSUE 3: Missing input validation / guard clause
        query = "UPDATE accounts SET balance = balance - %s WHERE id = %s" % (amount, source_account)
        return {"query": query, "transferred": amount}

    def calculate_interest(self, principal, rate, time, compound_frequency, tax_rate, fee_structure, rounding_mode, currency_conversion):
        # KNOWN ISSUE 4: Too many arguments (8 args)
        # KNOWN ISSUE 5: eval usage
        formula = eval("principal * (1 + rate / compound_frequency) ** (compound_frequency * time)")
        return formula

class LegacyReportGenerator:
    def generate_report(self, request_data):
        # KNOWN ISSUE 6: Missing docstring
        # KNOWN ISSUE 7: exec usage
        exec(request_data["template"])
        return {"report": "generated"}

class BatchProcessor:
    def process_batch(self, batch_file):
        try:
            # KNOWN ISSUE 8: os.system with user input
            os.system(f"process_batch.sh {batch_file}")
            return {"status": "processed"}
        except Exception:
            # KNOWN ISSUE 9: bare except (catching Exception is also bad practice but let's use bare)
            pass

    def load_state(self, state_blob):
        # KNOWN ISSUE 10: pickle.loads on untrusted data
        return pickle.loads(state_blob)

def reconcile_accounts(accounts, transactions, fees, interest, penalties, adjustments, overrides, audit_trail):
    # KNOWN ISSUE 11: Too many arguments (8 args)
    # KNOWN ISSUE 12: Missing docstring
    result = 0
    for acc in accounts:
        result += eval("acc['balance']")  # KNOWN ISSUE 13: eval usage
    return result
