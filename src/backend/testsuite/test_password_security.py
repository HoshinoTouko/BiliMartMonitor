import os
import sys
import tempfile
import unittest


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from bsm import db, settings
from bsm.passwords import hash_password, is_password_hash, verify_password
from backend.auth import authenticate_access_user


class PasswordSecurityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(prefix="bsm-pwd-test-", suffix=".db")
        os.close(self.db_fd)
        self.cfg_fd, self.cfg_path = tempfile.mkstemp(prefix="bsm-pwd-test-", suffix=".yaml")
        os.close(self.cfg_fd)
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("")

        os.environ["BSM_TESTING"] = "1"
        os.environ["BSM_DB_BACKEND"] = "sqlite"
        os.environ["BSM_TEST_DB_PATH"] = self.db_path
        os.environ["BSM_CONFIG_PATH"] = self.cfg_path
        db._reset_backend_cache()

    def tearDown(self) -> None:
        for key in ("BSM_TESTING", "BSM_DB_BACKEND", "BSM_TEST_DB_PATH", "BSM_CONFIG_PATH"):
            os.environ.pop(key, None)
        db._reset_backend_cache()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.cfg_path):
            os.remove(self.cfg_path)

    def test_hash_password_roundtrip(self) -> None:
        hashed = hash_password("secret123")
        self.assertTrue(is_password_hash(hashed))
        self.assertRegex(hashed, r"^pbkdf2_sha256\$\d+\$[0-9a-f]+\$[0-9a-f]+$")
        self.assertTrue(verify_password("secret123", hashed))
        self.assertFalse(verify_password("wrong", hashed))

    def test_upsert_access_user_hashes_plain_password(self) -> None:
        settings.upsert_access_user(
            username="alice",
            display_name="Alice",
            password_hash="plain-password",
            roles=["admin"],
            status="active",
        )
        row = settings.get_access_user("alice")
        self.assertIsNotNone(row)
        stored = str((row or {}).get("password_hash") or "")
        self.assertNotEqual(stored, "plain-password")
        self.assertTrue(is_password_hash(stored))
        self.assertTrue(verify_password("plain-password", stored))

    def test_authenticate_access_user_upgrades_plaintext_password(self) -> None:
        # Direct DB write to simulate legacy plaintext rows.
        backend = db._require_sqlalchemy_backend()
        from bsm.orm_models import AccessUser
        from sqlalchemy import select

        with backend.session() as session:
            session.add(
                AccessUser(
                    username="legacy",
                    display_name="Legacy",
                    password_hash="legacy-pass",
                    roles_json='["user"]',
                    status="active",
                )
            )

        user = authenticate_access_user("legacy", "legacy-pass")
        self.assertIsNotNone(user)

        with backend.session() as session:
            stored = session.scalar(select(AccessUser.password_hash).where(AccessUser.username == "legacy"))
        self.assertIsNotNone(stored)
        self.assertTrue(is_password_hash(str(stored)))
        self.assertTrue(verify_password("legacy-pass", str(stored)))

    def test_now_uses_millisecond_precision_timestamp(self) -> None:
        value = db._now()
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
        cutoff = db._utc_cutoff(hours=1)
        self.assertRegex(cutoff, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
        snap = db._snapshot_now()
        self.assertRegex(snap, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
