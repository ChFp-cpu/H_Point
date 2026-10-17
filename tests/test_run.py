import importlib
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import hpoint.config as config
from run import SingleInstance


class RunTests(unittest.TestCase):
    def test_lock_uses_the_writable_runtime_directory(self):
        identity = f"hpoint-test-{uuid.uuid4().hex}"
        with tempfile.TemporaryDirectory() as lock_dir:
            with patch.dict(os.environ, {"HPOINT_LOCK_DIR": lock_dir}, clear=False):
                instance = SingleInstance(identity)
                self.assertTrue(instance.acquire())
                try:
                    self.assertTrue(instance._lock_path().is_file())
                finally:
                    instance.release()

    def test_only_one_instance_can_hold_the_project_lock(self):
        identity = f"hpoint-test-{uuid.uuid4().hex}"
        first = SingleInstance(identity)
        second = SingleInstance(identity)
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
        finally:
            second.release()
            first.release()

    def test_lock_is_not_affected_by_the_callers_working_directory(self):
        identity = f"hpoint-test-{uuid.uuid4().hex}"
        first = SingleInstance(identity)
        original_cwd = os.getcwd()
        try:
            self.assertTrue(first.acquire())
            os.chdir(Path(__file__).resolve().parent)
            second = SingleInstance(identity)
            try:
                self.assertFalse(second.acquire())
            finally:
                second.release()
        finally:
            os.chdir(original_cwd)
            first.release()

    def test_config_can_disable_polling_in_the_website_process(self):
        try:
            with patch.dict(os.environ, {"RUN_TELEGRAM_BOT": "0"}, clear=False):
                self.assertFalse(importlib.reload(config).RUN_TELEGRAM_BOT)
        finally:
            importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
