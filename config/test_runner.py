from django.db import connection
from django.test.runner import DiscoverRunner


class LedgerTestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        result = super().setup_databases(**kwargs)
        with connection.cursor() as cursor:
            if connection.settings_dict["NAME"] != "test_household_ledger":
                raise RuntimeError("Unexpected test database.")
            cursor.execute("GRANT CONNECT ON DATABASE test_household_ledger TO ledger_test_app")
            cursor.execute("GRANT USAGE ON SCHEMA public TO ledger_test_app")
            cursor.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ledger_test_app")
            cursor.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ledger_test_app")
            # Explicitly grant the posting-number sequence in case it was
            # created before the blanket sequence grant above ran.
            cursor.execute(
                "GRANT USAGE, SELECT ON SEQUENCE accounting_posting_number_seq TO ledger_test_app"
            )
        return result
