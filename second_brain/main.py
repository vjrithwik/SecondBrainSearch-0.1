# SecondBrainSearch application entry point.
"""Application entry point."""

import sys

from PyQt6.QtWidgets import QApplication

from second_brain.config import APP_NAME, APP_VERSION
from second_brain.logging_config import configure_logging, get_logger
from second_brain.ui.main_window import MainWindow


def main() -> int:
    """Launch the SecondBrainSearch desktop application.

    Returns:
        Process exit code (0 for success).
    """
    configure_logging()
    logger = get_logger(__name__)
    logger.info("%s v%s starting", APP_NAME, APP_VERSION)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
