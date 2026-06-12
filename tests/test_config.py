import os
import unittest
from unittest.mock import patch

from agent_bus.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_port_prefers_platform_port(self):
        env = {
            "PORT": "10000",
            "AGENT_BUS_PORT": "8765",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_settings().port, 10000)

    def test_agent_bus_port_is_local_fallback(self):
        env = {
            "AGENT_BUS_PORT": "8766",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_settings().port, 8766)


if __name__ == "__main__":
    unittest.main()
