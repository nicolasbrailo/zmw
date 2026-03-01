import sys
import logging
from pathlib import Path
from unittest.mock import MagicMock

# Mock z2m_services before any imports that depend on it
mock_service_runner = MagicMock()
mock_service_runner.build_logger = lambda name: logging.getLogger(name)
sys.modules['z2m_services'] = MagicMock()
sys.modules['z2m_services.service_runner'] = mock_service_runner

# Add the zzmw_lib package root to sys.path so tests can import modules
# tests/ is at zzmw_lib/zzmw_lib/z2m/tests/
zmw_lib_root = Path(__file__).parent.parent.parent.parent  # zzmw_lib/
sys.path.insert(0, str(zmw_lib_root))
