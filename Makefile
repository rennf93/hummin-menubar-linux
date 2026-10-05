PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib/hummin-menubar
UNITDIR ?= $(HOME)/.config/systemd/user
CONFIG ?= $(HOME)/.config/hummin-menubar/servers.json

.PHONY: check install install-config uninstall run clean

check:
	python3 -m compileall -q hummin_menubar

install: check
	rm -rf $(LIBDIR)
	install -d $(LIBDIR) $(BINDIR) $(UNITDIR)
	cp -R hummin_menubar $(LIBDIR)/hummin_menubar
	cp -R icon $(LIBDIR)/icon
	find $(LIBDIR) -name __pycache__ -type d -prune -exec rm -rf {} +
	@{ printf '#!/bin/sh\n'; \
	   printf 'PYTHONPATH=%s exec python3 -m hummin_menubar "$$@"\n' '$(LIBDIR)'; } > $(BINDIR)/hummin-menubar
	chmod 755 $(BINDIR)/hummin-menubar
	install -m 644 packaging/systemd/hummin-menubar.service $(UNITDIR)/hummin-menubar.service
	@systemctl --user daemon-reload 2>/dev/null || true
	@echo "installed $(BINDIR)/hummin-menubar + $(UNITDIR)/hummin-menubar.service"
	@echo "start with: systemctl --user enable --now hummin-menubar"

install-config:
	@mkdir -p $(dir $(CONFIG))
	@if [ -f $(CONFIG) ]; then \
		echo "$(CONFIG) already exists, leaving it alone"; \
	else \
		cp examples/servers.example.json $(CONFIG); \
		echo "seeded $(CONFIG) from the example — edit it (or copy your servers.json over from the Mac)"; \
	fi

uninstall:
	rm -f $(BINDIR)/hummin-menubar $(UNITDIR)/hummin-menubar.service
	rm -rf $(LIBDIR)
	@systemctl --user daemon-reload 2>/dev/null || true

run: check
	PYTHONPATH=. python3 -m hummin_menubar

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
