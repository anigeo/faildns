import select
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

import dns.message
import dns.query
import dns.rcode
import dns.rdatatype


ROOT = Path(__file__).resolve().parents[1]


def free_ports(count: int) -> list[int]:
    sockets = []
    try:
        for _ in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def txt_values(response: dns.message.Message) -> set[str]:
    return {
        b"".join(rdata.strings).decode()
        for rrset in response.answer
        for rdata in rrset
        if rrset.rdtype == dns.rdatatype.TXT
    }


class FaildnsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.servfail_port, cls.refused_port = free_ports(2)
        cls.process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "faildns.py"),
                "--servfail-port",
                str(cls.servfail_port),
                "--refused-port",
                str(cls.refused_port),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        cls._wait_for_startup()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)

    @classmethod
    def _wait_for_startup(cls) -> None:
        lines = []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                output = "".join(lines)
                raise RuntimeError(f"faildns exited during startup:\n{output}")
            readable, _, _ = select.select([cls.process.stdout], [], [], 0.1)
            if not readable:
                continue
            line = cls.process.stdout.readline()
            lines.append(line)
            if len([entry for entry in lines if "listening proto=" in entry]) >= 4:
                return
        output = "".join(lines)
        raise TimeoutError(f"faildns did not start in time:\n{output}")

    def query_udp(self, name: str, rdtype: str, port: int) -> dns.message.Message:
        query = dns.message.make_query(name, rdtype)
        return dns.query.udp(query, "127.0.0.1", port=port, timeout=2)

    def query_tcp(self, name: str, rdtype: str, port: int) -> dns.message.Message:
        query = dns.message.make_query(name, rdtype)
        return dns.query.tcp(query, "127.0.0.1", port=port, timeout=2)

    def assert_rcode_for_both_transports(
        self, name: str, rdtype: str, port: int, rcode: int
    ) -> None:
        self.assertEqual(self.query_udp(name, rdtype, port).rcode(), rcode)
        self.assertEqual(self.query_tcp(name, rdtype, port).rcode(), rcode)

    def test_failure_modes(self) -> None:
        self.assert_rcode_for_both_transports(
            "example.com",
            "A",
            self.servfail_port,
            dns.rcode.SERVFAIL,
        )
        self.assert_rcode_for_both_transports(
            "example.com",
            "A",
            self.refused_port,
            dns.rcode.REFUSED,
        )

    def test_dnsdist_healthcheck_name_returns_noerror(self) -> None:
        for query_fn in (self.query_udp, self.query_tcp):
            response = query_fn("a.root-servers.net", "A", self.servfail_port)
            self.assertEqual(response.rcode(), dns.rcode.NOERROR)
            self.assertEqual(str(response.answer[0][0]), "198.41.0.4")

    def test_whoami_reports_listener_mode(self) -> None:
        checks = (
            (self.servfail_port, "servfail"),
            (self.refused_port, "refused"),
        )
        for port, mode in checks:
            for proto, query_fn in (("udp", self.query_udp), ("tcp", self.query_tcp)):
                response = query_fn("whoami.faildns", "TXT", port)
                values = txt_values(response)

                self.assertEqual(response.rcode(), dns.rcode.NOERROR)
                self.assertIn(f"local=127.0.0.1:{port}", values)
                self.assertIn(f"proto={proto}", values)
                self.assertIn(f"mode={mode}", values)
                self.assertTrue(any(value.startswith("remote=127.0.0.1:") for value in values))


if __name__ == "__main__":
    unittest.main()
