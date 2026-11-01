import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class LoggingTests(unittest.TestCase):
    def test_warnings_are_written_next_to_the_settings_file(self):
        root = logging.getLogger()
        saved_handlers, saved_level = root.handlers[:], root.level
        root.handlers.clear()

        def restore():
            root.handlers.clear()
            root.handlers.extend(saved_handlers)
            root.setLevel(saved_level)

        self.addCleanup(restore)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(app, "default_settings_path", return_value=Path(folder) / "sub" / "settings.json"):
                app.configure_logging()
            logging.getLogger("app_volume_manager.test").info("not recorded")
            try:
                raise RuntimeError("broken callback")
            except RuntimeError:
                logging.getLogger("app_volume_manager.test").exception("Something failed")
            for handler in root.handlers:
                handler.close()
            text = (Path(folder) / "sub" / "app.log").read_text(encoding="utf-8")
        self.assertIn("Something failed", text)
        self.assertIn("RuntimeError: broken callback", text)
        self.assertNotIn("not recorded", text)


if __name__ == "__main__":
    unittest.main()
