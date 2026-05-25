PYTHON ?= python3
UV ?= uv
UV_CACHE ?= .uv-cache
PREFIX ?= /usr/local
SYSCONFDIR ?= /etc
SYSTEMD_DIR ?= /etc/systemd/system
INSTALL ?= install

.PHONY: check clean dev format help install integration lint sync syntax test uninstall unit

help:
	@printf '%s\n' \
		'Targets:' \
		'  make dev          Create/update the uv virtualenv for ad hoc/dev use' \
		'  make sync         Sync the uv virtualenv' \
		'  make format       Format with Ruff' \
		'  make lint         Lint with Ruff' \
		'  make syntax       Compile faildns.py' \
		'  make unit         Run unit tests' \
		'  make integration  Run integration tests' \
		'  make test         Run all tests' \
		'  make check        Run lint, syntax, and tests' \
		'  make install      Install faildns and systemd unit' \
		'  make uninstall    Remove faildns and systemd unit'

sync:
	$(UV) --cache-dir $(UV_CACHE) sync

dev: sync

format: sync
	$(UV) --cache-dir $(UV_CACHE) run ruff format .

lint: sync
	$(UV) --cache-dir $(UV_CACHE) run ruff check .

syntax:
	$(PYTHON) -m py_compile faildns.py

unit:
	$(PYTHON) -m unittest tests.test_faildns_unit -v

integration:
	$(PYTHON) -m unittest tests.test_faildns_integration -v

test:
	$(PYTHON) -m unittest discover -s tests -v

check: lint syntax test

install:
	$(INSTALL) -d $(DESTDIR)$(PREFIX)/bin
	$(INSTALL) -d $(DESTDIR)$(SYSCONFDIR)/default
	$(INSTALL) -d $(DESTDIR)$(SYSTEMD_DIR)
	$(INSTALL) -m 0755 faildns.py $(DESTDIR)$(PREFIX)/bin/faildns
	$(INSTALL) -m 0644 faildns.default $(DESTDIR)$(SYSCONFDIR)/default/faildns
	$(INSTALL) -m 0644 faildns.service $(DESTDIR)$(SYSTEMD_DIR)/faildns.service

uninstall:
	rm -f $(DESTDIR)$(PREFIX)/bin/faildns
	rm -f $(DESTDIR)$(SYSCONFDIR)/default/faildns
	rm -f $(DESTDIR)$(SYSTEMD_DIR)/faildns.service

clean:
	rm -rf .uv-cache .ruff_cache __pycache__ tests/__pycache__ faildns.egg-info
