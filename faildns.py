#!/usr/bin/env python3
"""Small DNS responder that returns fixed failure rcodes on two ports."""

import argparse
import asyncio
import logging
import os
import signal
import struct
import sys
from collections.abc import Iterable

import dns.exception
import dns.flags
import dns.message
import dns.rcode
import dns.rdataclass
import dns.rdatatype
import dns.rrset


DEFAULT_LISTEN_ADDRESS = "127.0.0.1"
DEFAULT_SERVFAIL_PORT = 5300
DEFAULT_REFUSED_PORT = 5301
LOG = logging.getLogger("faildns")
SYSLOG_PRIORITIES = {
    logging.DEBUG: 7,
    logging.INFO: 6,
    logging.WARNING: 4,
    logging.ERROR: 3,
    logging.CRITICAL: 2,
}
ROOT_SERVER_TTL = 3600
DEBUG_TTL = 0
ROOT_SERVER_RECORDS = {
    "a.root-servers.net.": {
        dns.rdatatype.A: ("198.41.0.4",),
        dns.rdatatype.AAAA: ("2001:503:ba3e::2:30",),
    },
    "b.root-servers.net.": {
        dns.rdatatype.A: ("170.247.170.2",),
        dns.rdatatype.AAAA: ("2801:1b8:10::b",),
    },
    "c.root-servers.net.": {
        dns.rdatatype.A: ("192.33.4.12",),
        dns.rdatatype.AAAA: ("2001:500:2::c",),
    },
    "d.root-servers.net.": {
        dns.rdatatype.A: ("199.7.91.13",),
        dns.rdatatype.AAAA: ("2001:500:2d::d",),
    },
    "e.root-servers.net.": {
        dns.rdatatype.A: ("192.203.230.10",),
        dns.rdatatype.AAAA: ("2001:500:a8::e",),
    },
    "f.root-servers.net.": {
        dns.rdatatype.A: ("192.5.5.241",),
        dns.rdatatype.AAAA: ("2001:500:2f::f",),
    },
    "g.root-servers.net.": {
        dns.rdatatype.A: ("192.112.36.4",),
        dns.rdatatype.AAAA: ("2001:500:12::d0d",),
    },
    "h.root-servers.net.": {
        dns.rdatatype.A: ("198.97.190.53",),
        dns.rdatatype.AAAA: ("2001:500:1::53",),
    },
    "i.root-servers.net.": {
        dns.rdatatype.A: ("192.36.148.17",),
        dns.rdatatype.AAAA: ("2001:7fe::53",),
    },
    "j.root-servers.net.": {
        dns.rdatatype.A: ("192.58.128.30",),
        dns.rdatatype.AAAA: ("2001:503:c27::2:30",),
    },
    "k.root-servers.net.": {
        dns.rdatatype.A: ("193.0.14.129",),
        dns.rdatatype.AAAA: ("2001:7fd::1",),
    },
    "l.root-servers.net.": {
        dns.rdatatype.A: ("199.7.83.42",),
        dns.rdatatype.AAAA: ("2001:500:9f::42",),
    },
    "m.root-servers.net.": {
        dns.rdatatype.A: ("202.12.27.33",),
        dns.rdatatype.AAAA: ("2001:dc3::35",),
    },
}


class JournaldFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        priority = SYSLOG_PRIORITIES.get(record.levelno, 5)
        return f"<{priority}>{record.getMessage()}"


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {value!r}") from exc


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JournaldFormatter())

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        handlers=[handler],
        force=True,
    )


def first_question_text(request: dns.message.Message | None) -> str:
    if request is None or not request.question:
        return "-"

    question = request.question[0]
    return "%s %s %s" % (
        question.name,
        dns.rdatatype.to_text(question.rdtype),
        dns.rdataclass.to_text(question.rdclass),
    )


def endpoint_text(address: tuple | None) -> str:
    if address is None or len(address) < 2:
        return str(address)

    host, port = address[0], address[1]
    if isinstance(host, str) and ":" in host:
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def log_access(
    *,
    proto: str,
    local_port: int,
    remote: tuple | None,
    rcode: int,
    request: dns.message.Message | None,
    request_size: int,
    note: str = "",
) -> None:
    request_id = request.id if request is not None else "-"
    question = first_question_text(request)
    level = logging.WARNING if note else logging.INFO
    message = 'proto=%s local_port=%s remote=%s id=%s rcode=%s bytes=%s question="%s"'
    args: tuple[object, ...] = (
        proto,
        local_port,
        endpoint_text(remote),
        request_id,
        dns.rcode.to_text(rcode),
        request_size,
        question,
    )
    if note:
        message += " note=%s"
        args += (note,)
    LOG.log(level, message, *args)


def normalized_qname(request: dns.message.Message) -> str | None:
    if len(request.question) != 1:
        return None

    qname = request.question[0].name.to_text().lower()
    if not qname.endswith("."):
        qname += "."
    return qname


def make_static_root_server_response(request: dns.message.Message) -> dns.message.Message | None:
    qname = normalized_qname(request)
    if qname is None:
        return None

    question = request.question[0]
    if question.rdclass != dns.rdataclass.IN:
        return None

    records = ROOT_SERVER_RECORDS.get(qname)
    if records is None:
        return None

    response = dns.message.make_response(request)
    rdtypes = (
        (dns.rdatatype.A, dns.rdatatype.AAAA)
        if question.rdtype == dns.rdatatype.ANY
        else (question.rdtype,)
    )
    for rdtype in rdtypes:
        values = records.get(rdtype)
        if values:
            response.answer.append(
                dns.rrset.from_text(
                    question.name,
                    ROOT_SERVER_TTL,
                    question.rdclass,
                    rdtype,
                    *values,
                )
            )

    return response


def make_whoami_response(
    request: dns.message.Message,
    *,
    proto: str,
    remote: tuple | None,
    local: tuple | None,
    mode: int,
) -> dns.message.Message | None:
    qname = normalized_qname(request)
    if qname is None:
        return None

    question = request.question[0]
    if question.rdtype not in (dns.rdatatype.TXT, dns.rdatatype.ANY):
        return None

    if question.rdclass == dns.rdataclass.IN and qname == "whoami.faildns.":
        response = dns.message.make_response(request)
        response.answer.append(
            dns.rrset.from_text(
                question.name,
                DEBUG_TTL,
                question.rdclass,
                dns.rdatatype.TXT,
                "remote=%s" % endpoint_text(remote),
                "local=%s" % endpoint_text(local),
                "proto=%s" % proto,
                "mode=%s" % dns.rcode.to_text(mode).lower(),
            )
        )
        return response

    return None


def make_response_wire(
    data: bytes,
    response_rcode: int,
    *,
    proto: str,
    remote: tuple | None,
    local: tuple | None,
) -> tuple[bytes, dns.message.Message | None, int, str]:
    try:
        request = dns.message.from_wire(data)
        whoami_response = make_whoami_response(
            request,
            proto=proto,
            remote=remote,
            local=local,
            mode=response_rcode,
        )
        if whoami_response is not None:
            return whoami_response.to_wire(), request, whoami_response.rcode(), ""

        static_response = make_static_root_server_response(request)
        if static_response is not None:
            return static_response.to_wire(), request, static_response.rcode(), ""

        response = dns.message.make_response(request)
        response.set_rcode(response_rcode)
        return response.to_wire(), request, response_rcode, ""
    except dns.exception.DNSException as exc:
        request_id = int.from_bytes(data[:2], "big") if len(data) >= 2 else 0
        response = dns.message.Message(id=request_id)
        response.flags |= dns.flags.QR
        response.set_rcode(dns.rcode.FORMERR)
        return response.to_wire(), None, dns.rcode.FORMERR, exc.__class__.__name__


class DNSDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, response_rcode: int, local_port: int) -> None:
        self.response_rcode = response_rcode
        self.local_port = local_port
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, address: tuple) -> None:
        local = self.transport.get_extra_info("sockname") if self.transport is not None else None
        wire, request, logged_rcode, note = make_response_wire(
            data,
            self.response_rcode,
            proto="udp",
            remote=address,
            local=local,
        )
        log_access(
            proto="udp",
            local_port=self.local_port,
            remote=address,
            rcode=logged_rcode,
            request=request,
            request_size=len(data),
            note=note,
        )
        if self.transport is not None:
            self.transport.sendto(wire, address)

    def error_received(self, exc: Exception) -> None:
        LOG.error("proto=udp error=%s", exc)


async def read_dns_tcp_message(reader: asyncio.StreamReader) -> bytes | None:
    try:
        length_wire = await reader.readexactly(2)
    except asyncio.IncompleteReadError as exc:
        if exc.partial:
            raise ValueError("truncated-length") from exc
        return None

    size = struct.unpack("!H", length_wire)[0]
    try:
        return await reader.readexactly(size)
    except asyncio.IncompleteReadError as exc:
        raise ValueError("truncated-message") from exc


async def handle_tcp_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    response_rcode: int,
) -> None:
    remote = writer.get_extra_info("peername")
    local = writer.get_extra_info("sockname")
    local_port = local[1] if local and len(local) >= 2 else 0

    try:
        while True:
            try:
                data = await read_dns_tcp_message(reader)
            except ValueError as exc:
                log_access(
                    proto="tcp",
                    local_port=local_port,
                    remote=remote,
                    rcode=dns.rcode.FORMERR,
                    request=None,
                    request_size=0,
                    note=str(exc),
                )
                return

            if data is None:
                return

            wire, request, logged_rcode, note = make_response_wire(
                data,
                response_rcode,
                proto="tcp",
                remote=remote,
                local=local,
            )
            log_access(
                proto="tcp",
                local_port=local_port,
                remote=remote,
                rcode=logged_rcode,
                request=request,
                request_size=len(data),
                note=note,
            )
            writer.write(struct.pack("!H", len(wire)) + wire)
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def start_udp(
    *,
    listen_address: str,
    port: int,
    response_rcode: int,
) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: DNSDatagramProtocol(response_rcode, port),
        local_addr=(listen_address, port),
    )
    LOG.info(
        "listening proto=udp address=%s port=%s rcode=%s",
        listen_address,
        port,
        dns.rcode.to_text(response_rcode),
    )
    return transport


async def start_tcp(
    *,
    listen_address: str,
    port: int,
    response_rcode: int,
) -> asyncio.Server:
    server = await asyncio.start_server(
        lambda reader, writer: handle_tcp_client(reader, writer, response_rcode),
        listen_address,
        port,
    )

    for sock in server.sockets or []:
        address = sock.getsockname()
        LOG.info(
            "listening proto=tcp address=%s port=%s rcode=%s",
            address[0],
            address[1],
            dns.rcode.to_text(response_rcode),
        )

    return server


async def run_servers(
    *,
    listen_address: str,
    port_rcodes: Iterable[tuple[int, int]],
) -> None:
    stop = asyncio.Event()

    def handle_signal(signum: int) -> None:
        LOG.info("stopping signal=%s", signum)
        stop.set()

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, handle_signal, signum)

    udp_transports: list[asyncio.DatagramTransport] = []
    tcp_servers: list[asyncio.Server] = []

    for port, response_rcode in port_rcodes:
        udp_transports.append(
            await start_udp(
                listen_address=listen_address,
                port=port,
                response_rcode=response_rcode,
            )
        )
        tcp_servers.append(
            await start_tcp(
                listen_address=listen_address,
                port=port,
                response_rcode=response_rcode,
            )
        )

    try:
        await stop.wait()
    finally:
        for transport in udp_transports:
            transport.close()
        for server in tcp_servers:
            server.close()
            await server.wait_closed()
        LOG.info("stopped")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run two DNS failure responders.")
    parser.add_argument(
        "--listen-address",
        default=os.getenv("DNS_LISTEN_ADDRESS", DEFAULT_LISTEN_ADDRESS),
        help=f"address to bind, default: ${'DNS_LISTEN_ADDRESS'} or {DEFAULT_LISTEN_ADDRESS}",
    )
    parser.add_argument(
        "--servfail-port",
        type=int,
        default=env_int("SERVFAIL_PORT", DEFAULT_SERVFAIL_PORT),
        help=f"port that returns SERVFAIL, default: ${'SERVFAIL_PORT'} or {DEFAULT_SERVFAIL_PORT}",
    )
    parser.add_argument(
        "--refused-port",
        type=int,
        default=env_int("REFUSED_PORT", DEFAULT_REFUSED_PORT),
        help=f"port that returns REFUSED, default: ${'REFUSED_PORT'} or {DEFAULT_REFUSED_PORT}",
    )
    return parser


def main() -> int:
    configure_logging()

    parser = build_arg_parser()
    args = parser.parse_args()
    if args.servfail_port == args.refused_port:
        parser.error("--servfail-port and --refused-port must be different")

    asyncio.run(
        run_servers(
            listen_address=args.listen_address,
            port_rcodes=[
                (args.servfail_port, dns.rcode.SERVFAIL),
                (args.refused_port, dns.rcode.REFUSED),
            ],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
