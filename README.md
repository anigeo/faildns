# faildns

`faildns` is a small DNS failure responder for testing DNS fallback flows.

It is intentionally not a general-purpose DNS server. Its main job is to make it easy to generate predictable failure responses and confirm how clients, proxies, or load balancers behave when a DNS backend returns `SERVFAIL` or `REFUSED`.

It listens on two ports by default:

- `SERVFAIL_PORT`, default `5300`, always responds with `SERVFAIL`
- `REFUSED_PORT`, default `5301`, always responds with `REFUSED`

Both UDP and TCP DNS are enabled. The server listens on `127.0.0.1` by default. Access logs are written to stdout, so under systemd they are available through journald.
The systemd unit enables journald priority parsing, so `journalctl` shows the message without Python timestamps or level text.

`A`, `AAAA`, and `ANY` queries for `a.root-servers.net.` through `m.root-servers.net.` return static IANA root-server addresses with `NOERROR`. This keeps dnsdist's default health check, `A a.root-servers.net.`, healthy even on the `SERVFAIL` port. All other queries keep the fixed failure behavior for the port.

`whoami.faildns. IN TXT` also returns one TXT record each for `remote=...`, `local=...`, `proto=...`, and `mode=servfail` or `mode=refused`. This is useful for checking which faildns listener dnsdist reached.

## Local run

Requirements:

- Debian 12 (bookworm) or newer
- Python 3.11 or newer
- Debian `python3-dnspython` package

```sh
sudo apt install python3-dnspython
python3 ./faildns.py
```

Generate failure responses:

```sh
dig @127.0.0.1 -p 5300 example.com A
dig @127.0.0.1 -p 5301 example.com A
```

Check which faildns listener was reached:

```sh
dig @127.0.0.1 -p 5300 whoami.faildns TXT
```

Example log message:

```text
proto=udp local_port=5300 remote=127.0.0.1:53422 id=1234 rcode=SERVFAIL bytes=52 question="example.com. A IN"
```

## Options

```sh
python3 ./faildns.py \
  --listen-address 127.0.0.1 \
  --servfail-port 5300 \
  --refused-port 5301
```

Environment variables with the same defaults are also supported:

- `DNS_LISTEN_ADDRESS`, default `127.0.0.1`
- `SERVFAIL_PORT`
- `REFUSED_PORT`
- `LOG_LEVEL`, default `INFO`

Use `--listen-address 0.0.0.0` only when the server should accept remote clients.

## systemd

Install on Debian 12 (bookworm) or newer:

```sh
sudo apt install python3-dnspython
sudo make install
sudo systemctl daemon-reload
sudo systemctl enable --now faildns.service
```

View logs:

```sh
journalctl -u faildns.service -f
```

## Development

`make dev` creates `.venv` with uv-managed dependencies for ad hoc local runs and development tools. uv uses `dnspython>=2.3,<3`, matching the supported dnspython 2.x series.

```sh
make dev
uv run ./faildns.py
make format
make check
make uv-test
make uv-test DNSPYTHON=2.3.0
make uv-test DNSPYTHON=2.7.0
make uv-test DNSPYTHON=2.8.0
make uv-test DNSPYTHON=latest-2.x
```

`make test` runs both unit tests and a local loopback integration test that starts `faildns.py` on random ports. By default, tests use system `python3`, so install `python3-dnspython` first. Use `make uv-test` to run the same tests in the uv-managed environment, optionally selecting `DNSPYTHON=2.3.0`, `DNSPYTHON=2.7.0`, `DNSPYTHON=2.8.0`, or `DNSPYTHON=latest-2.x`.

## License

MIT.
