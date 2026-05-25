import unittest

import dns.message
import dns.rdataclass
import dns.rcode
import dns.rdatatype

import faildns


def response_for(
    query: dns.message.Message,
    mode: int,
    *,
    proto: str = "udp",
    remote: tuple[str, int] = ("127.0.0.1", 12345),
    local: tuple[str, int] = ("127.0.0.1", 5300),
) -> dns.message.Message:
    wire, _request, _rcode, note = faildns.make_response_wire(
        query.to_wire(),
        mode,
        proto=proto,
        remote=remote,
        local=local,
    )
    assert note == ""
    return dns.message.from_wire(wire)


def txt_values(response: dns.message.Message) -> set[str]:
    return {
        b"".join(rdata.strings).decode()
        for rrset in response.answer
        for rdata in rrset
        if rrset.rdtype == dns.rdatatype.TXT
    }


class ResponseTests(unittest.TestCase):
    def test_default_failure_response_uses_listener_mode(self) -> None:
        query = dns.message.make_query("example.com", "A")

        servfail = response_for(query, dns.rcode.SERVFAIL)
        refused = response_for(query, dns.rcode.REFUSED)

        self.assertEqual(servfail.rcode(), dns.rcode.SERVFAIL)
        self.assertEqual(refused.rcode(), dns.rcode.REFUSED)
        self.assertEqual(servfail.answer, [])
        self.assertEqual(refused.answer, [])

    def test_root_server_healthcheck_has_static_noerror_answer(self) -> None:
        query = dns.message.make_query("a.root-servers.net", "A")

        response = response_for(query, dns.rcode.SERVFAIL)

        self.assertEqual(response.rcode(), dns.rcode.NOERROR)
        self.assertEqual(len(response.answer), 1)
        self.assertEqual(response.answer[0].rdtype, dns.rdatatype.A)
        self.assertEqual(str(response.answer[0][0]), "198.41.0.4")

    def test_root_server_any_includes_a_and_aaaa_answers(self) -> None:
        query = dns.message.make_query("a.root-servers.net", "ANY")

        response = response_for(query, dns.rcode.SERVFAIL)
        answer_types = {rrset.rdtype for rrset in response.answer}

        self.assertEqual(response.rcode(), dns.rcode.NOERROR)
        self.assertEqual(answer_types, {dns.rdatatype.A, dns.rdatatype.AAAA})

    def test_whoami_reports_request_context_and_mode(self) -> None:
        query = dns.message.make_query("whoami.faildns", "TXT")

        response = response_for(
            query,
            dns.rcode.REFUSED,
            proto="tcp",
            remote=("192.0.2.10", 42000),
            local=("127.0.0.1", 5301),
        )

        self.assertEqual(response.rcode(), dns.rcode.NOERROR)
        self.assertEqual(
            txt_values(response),
            {
                "remote=192.0.2.10:42000",
                "local=127.0.0.1:5301",
                "proto=tcp",
                "mode=refused",
            },
        )

    def test_whoami_is_in_class_only(self) -> None:
        query = dns.message.make_query("whoami.faildns", "TXT", rdclass=dns.rdataclass.CH)

        response = response_for(query, dns.rcode.SERVFAIL)

        self.assertEqual(response.rcode(), dns.rcode.SERVFAIL)
        self.assertEqual(response.answer, [])

    def test_malformed_wire_returns_formerr(self) -> None:
        wire, request, rcode, note = faildns.make_response_wire(
            b"\x12\x34\x00",
            dns.rcode.SERVFAIL,
            proto="udp",
            remote=("127.0.0.1", 12345),
            local=("127.0.0.1", 5300),
        )
        response = dns.message.from_wire(wire)

        self.assertIsNone(request)
        self.assertEqual(rcode, dns.rcode.FORMERR)
        self.assertEqual(response.rcode(), dns.rcode.FORMERR)
        self.assertTrue(note)


if __name__ == "__main__":
    unittest.main()
