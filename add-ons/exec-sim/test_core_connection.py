import unittest
from unittest.mock import patch

import dashboard


class CoreConnectionTests(unittest.TestCase):
    def test_validates_both_cli_core_transports(self):
        with patch("dashboard.socket.create_connection") as connect:
            dashboard._validate_core_connection(
                "grpc.core.example", "50051", "ssh.core.example", "22", "core", "secret",
            )

        self.assertEqual(
            [call.args[0] for call in connect.call_args_list],
            [("grpc.core.example", 50051), ("ssh.core.example", 22)],
        )

    def test_rejects_incomplete_connection_values(self):
        with self.assertRaisesRegex(ValueError, "gRPC host"):
            dashboard._validate_core_connection("", 50051, "ssh.core.example", 22, "core", "secret")


if __name__ == "__main__":
    unittest.main()
