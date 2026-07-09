"""
Tests for the EOD Ingestion Pipeline and Database Layer.
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infrastructure.database import SQLiteAdapter, compute_file_hash
from services.ingestion.eod_service import EODIngestionService


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    adapter = SQLiteAdapter(db_path)
    adapter.initialize()
    yield adapter
    adapter.close()
    os.unlink(db_path)


@pytest.fixture
def sample_csv(tmp_path):
    """Create a sample CSV file in IBM AML format."""
    csv_content = """Timestamp,From Bank,Account,To Bank,Account.1,Amount Received,Receiving Currency,Amount Paid,Payment Currency,Payment Format,Is Laundering
2026/05/31 10:30,ICICI,ACC001,HDFC,ACC002,50000.00,Indian Rupee,50000.00,Indian Rupee,Wire,0
2026/05/31 10:31,ICICI,ACC001,SBI,ACC003,95000.00,Indian Rupee,95000.00,Indian Rupee,ACH,0
2026/05/31 10:32,HDFC,ACC002,AXIS,ACC004,25000.00,Indian Rupee,25000.00,Indian Rupee,Wire,0
2026/05/31 10:33,SBI,ACC003,ICICI,ACC001,48000.00,Indian Rupee,48000.00,Indian Rupee,Cheque,1
2026/05/31 10:34,AXIS,ACC004,PNB,ACC005,120000.00,Indian Rupee,120000.00,Indian Rupee,Wire,0
2026/05/31 10:35,PNB,ACC005,ICICI,ACC001,900000.00,Indian Rupee,900000.00,Indian Rupee,ACH,1
2026/05/31 10:36,ICICI,ACC001,BOB,ACC006,950000.00,Indian Rupee,950000.00,Indian Rupee,Wire,1
2026/05/31 10:37,ICICI,ACC001,KOTAK,ACC007,980000.00,Indian Rupee,980000.00,Indian Rupee,ACH,1
2026/05/31 10:38,ICICI,ACC001,YES,ACC008,920000.00,Indian Rupee,920000.00,Indian Rupee,Wire,1
2026/05/31 10:39,HDFC,ACC002,IDBI,ACC009,15000.00,Indian Rupee,15000.00,Indian Rupee,Credit Card,0
2026/05/31 10:40,SBI,ACC010,ICICI,ACC001,300000.00,Indian Rupee,300000.00,Indian Rupee,Wire,0
"""
    csv_path = tmp_path / "test_eod.csv"
    csv_path.write_text(csv_content.strip())
    return str(csv_path)


class TestSQLiteAdapter:
    """Test the SQLite database adapter."""

    def test_initialize(self, temp_db):
        assert temp_db is not None

    def test_upsert_accounts(self, temp_db):
        accounts = [
            {"account_id": "ACC001", "account_type": "savings", "branch_city": "Mumbai",
             "risk_score": 75.0, "risk_level": "HIGH", "role": "MULE"},
            {"account_id": "ACC002", "account_type": "current", "branch_city": "Delhi",
             "risk_score": 20.0, "risk_level": "LOW", "role": "NORMAL"},
        ]
        count = temp_db.upsert_accounts(accounts)
        assert count == 2

    def test_get_account(self, temp_db):
        accounts = [{"account_id": "ACC100", "account_type": "savings", "branch_city": "Bangalore"}]
        temp_db.upsert_accounts(accounts)
        acc = temp_db.get_account("ACC100")
        assert acc is not None
        assert acc["account_id"] == "ACC100"
        assert acc["branch_city"] == "Bangalore"

    def test_account_exists(self, temp_db):
        accounts = [{"account_id": "ACC200"}]
        temp_db.upsert_accounts(accounts)
        assert temp_db.account_exists("ACC200") is True
        assert temp_db.account_exists("NONEXIST") is False

    def test_insert_transactions(self, temp_db):
        txns = [
            {"txn_id": "TXN001", "timestamp": "2026-05-31 10:30:00",
             "source_account": "ACC001", "dest_account": "ACC002",
             "amount": 50000.0, "channel": "wire", "txn_type": "transfer",
             "is_laundering": 0, "ingestion_date": "2026-05-31"},
            {"txn_id": "TXN002", "timestamp": "2026-05-31 10:31:00",
             "source_account": "ACC002", "dest_account": "ACC003",
             "amount": 25000.0, "channel": "ach", "txn_type": "transfer",
             "is_laundering": 0, "ingestion_date": "2026-05-31"},
        ]
        count = temp_db.insert_transactions(txns)
        assert count == 2

    def test_get_transactions_for_account(self, temp_db):
        txns = [
            {"txn_id": "TXN010", "timestamp": "2026-05-31 10:00:00",
             "source_account": "ACC_A", "dest_account": "ACC_B",
             "amount": 10000.0, "channel": "wire", "txn_type": "transfer",
             "is_laundering": 0, "ingestion_date": "2026-05-31"},
        ]
        temp_db.insert_transactions(txns)
        results = temp_db.get_transactions_for_account("ACC_A", days=7)
        assert len(results) >= 1
        assert results[0]["source_account"] == "ACC_A"

    def test_idempotency(self, temp_db):
        temp_db.record_ingestion("abc123", "test.csv", "2026-05-31", 100, 50)
        assert temp_db.is_file_ingested("abc123") is True
        assert temp_db.is_file_ingested("xyz789") is False

    def test_alerts(self, temp_db):
        alert = {
            "alert_id": "ALT-001",
            "account_id": "ACC001",
            "risk_score": 85.0,
            "risk_level": "CRITICAL",
            "pattern_type": "structuring",
            "status": "open",
        }
        temp_db.upsert_alert(alert)
        alerts = temp_db.get_alerts(risk_level="CRITICAL")
        assert len(alerts) >= 1
        assert alerts[0]["alert_id"] == "ALT-001"

    def test_get_account_count(self, temp_db):
        accounts = [{"account_id": f"ACC_{i}"} for i in range(10)]
        temp_db.upsert_accounts(accounts)
        assert temp_db.get_account_count() == 10

    def test_get_transaction_count(self, temp_db):
        txns = [
            {"txn_id": f"TXN_{i}", "timestamp": "2026-05-31 10:00:00",
             "source_account": "A", "dest_account": "B",
             "amount": 100.0, "ingestion_date": "2026-05-31"}
            for i in range(5)
        ]
        temp_db.insert_transactions(txns)
        assert temp_db.get_transaction_count() == 5


class TestEODIngestion:
    """Test the EOD Ingestion Service."""

    def test_ingest_daily_file(self, sample_csv, tmp_path, monkeypatch):
        """Test full ingestion of a CSV file."""
        db_path = str(tmp_path / "test_ingest.db")
        monkeypatch.setenv("SQLITE_PATH", db_path)

        # Reset the singleton
        import infrastructure.database as db_mod
        db_mod._db_instance = None
        db_mod.SQLITE_PATH = db_path

        svc = EODIngestionService()
        svc._db = None  # Force re-init

        result = svc.ingest_daily_file(
            filepath=sample_csv,
            date="2026-05-31",
        )

        assert result["status"] == "completed"
        assert result["total_transactions"] == 11
        assert result["total_accounts"] > 0
        assert result["new_accounts"] > 0
        # Detection/alerting no longer happens inside ingest_daily_file() itself —
        # the caller runs AnalysisPipeline.run_from_db() once afterward instead of
        # this method's own lightweight pass duplicating that work (see Phase 4:
        # EOD correctness). So there's no alerts_generated/patterns_detected here
        # any more; assert the data-persistence contract this method still owns.
        assert "processing_time_sec" in result

    def test_idempotent_ingestion(self, sample_csv, tmp_path, monkeypatch):
        """Test that re-ingesting the same file is skipped."""
        db_path = str(tmp_path / "test_idemp.db")
        monkeypatch.setenv("SQLITE_PATH", db_path)

        import infrastructure.database as db_mod
        db_mod._db_instance = None
        db_mod.SQLITE_PATH = db_path

        svc = EODIngestionService()
        svc._db = None

        # First ingestion
        result1 = svc.ingest_daily_file(filepath=sample_csv, date="2026-05-31")
        assert result1["status"] == "completed"

        # Second ingestion (same file) should be skipped
        svc._db = None
        import infrastructure.database as db_mod2
        db_mod2._db_instance = None
        db_mod2.SQLITE_PATH = db_path

        svc2 = EODIngestionService()
        svc2._db = None
        result2 = svc2.ingest_daily_file(filepath=sample_csv, date="2026-05-31")
        assert result2["status"] == "skipped"
        assert result2["reason"] == "already_ingested"

    def test_force_reingest(self, sample_csv, tmp_path, monkeypatch):
        """Test forced re-ingestion."""
        db_path = str(tmp_path / "test_force.db")
        monkeypatch.setenv("SQLITE_PATH", db_path)

        import infrastructure.database as db_mod
        db_mod._db_instance = None
        db_mod.SQLITE_PATH = db_path

        svc = EODIngestionService()
        svc._db = None

        result1 = svc.ingest_daily_file(filepath=sample_csv, date="2026-05-31")
        assert result1["status"] == "completed"

        # Force re-ingest
        svc._db = None
        db_mod._db_instance = None
        svc2 = EODIngestionService()
        svc2._db = None
        result2 = svc2.ingest_daily_file(filepath=sample_csv, date="2026-05-31", force=True)
        assert result2["status"] == "completed"

    def test_file_not_found(self, tmp_path, monkeypatch):
        """Test that missing files raise appropriate errors."""
        db_path = str(tmp_path / "test_notfound.db")
        monkeypatch.setenv("SQLITE_PATH", db_path)

        import infrastructure.database as db_mod
        db_mod._db_instance = None
        db_mod.SQLITE_PATH = db_path

        svc = EODIngestionService()
        svc._db = None

        with pytest.raises(FileNotFoundError):
            svc.ingest_daily_file(filepath="/nonexistent/path.csv")


class TestFileHash:
    """Test file hashing for idempotency."""

    def test_compute_file_hash(self, sample_csv):
        h1 = compute_file_hash(sample_csv)
        h2 = compute_file_hash(sample_csv)
        assert h1 == h2
        assert len(h1) == 64  # SHA256 hex length
