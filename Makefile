PYTHON ?= python3

.DEFAULT_GOAL := help
.PHONY: help setup run fix check lint test test-unit test-ui

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make \033[36m<command>\033[0m\n\n"} /^[a-z-]+:.*## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install everything needed to work on Tileminal (Ubuntu, Debian)
	sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91 \
		python3-pytest python3-pytest-xdist mypy black isort flake8 libgtk-3-bin dbus gettext

run: ## Start Tileminal from this folder, with its own settings and session
	XDG_STATE_HOME=/tmp/tileminal-dev XDG_CONFIG_HOME=/tmp/tileminal-dev $(PYTHON) tileminal --fresh

fix: ## Format the code, sort imports, refresh the translation template
	isort .
	black .
	$(PYTHON) tools/update_pot.py

check: lint test ## Run everything CI checks

lint: ## Check formatting, lint, types and the translation template
	black --check .
	isort --check-only .
	flake8 src tests tools tileminal
	mypy
	$(PYTHON) tools/update_pot.py --check

test: test-unit test-ui ## Run all tests

test-unit: ## Run the unit tests (quick, no GTK needed)
	$(PYTHON) -m pytest tests --ignore=tests/ui

test-ui: ## Run the app itself on a headless display, tests in parallel
	@$(PYTHON) -c 'import xdist' 2>/dev/null || { echo "pytest-xdist is missing: run 'make setup'"; exit 1; }
	$(PYTHON) -m pytest tests/ui -n auto



# ------------------------------------------------------------------------------------------------
# Maintainers only - building the snap package, kept here only for transparency.
# ------------------------------------------------------------------------------------------------

.PHONY: setup-snap snap

# Install snapcraft and LXD, needed only to build the snap yourself
setup-snap:
	sudo snap install snapcraft --classic
	sudo snap install lxd
	sudo lxd init --auto
	sudo usermod -aG lxd $(USER)
	@echo "Log out and in once, then 'make snap' works."

# Build the snap package (needs 'make setup-snap' first)
snap:
	snapcraft pack
