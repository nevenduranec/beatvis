PORT ?= 8000
BACKEND ?= auto
UNAME_S := $(shell uname -s 2>/dev/null)
ifeq ($(UNAME_S),Darwin)
DEFAULT_DEVICE := BlackHole 2ch
else
DEFAULT_DEVICE := default
endif
DEVICE ?= $(DEFAULT_DEVICE)
PY ?= .venv/bin/python

ifeq (,$(wildcard $(PY)))
PY = python3
endif

.PHONY: start
start: ## Start WS + HTTP and open browser
	@PORT=$(PORT) BACKEND="$(BACKEND)" DEVICE="$(DEVICE)" $(PY) serve.py

.PHONY: devices
devices: ## List devices/sources for BACKEND
	@BACKEND="$(BACKEND)" $(PY) visualizer.py --backend "$(BACKEND)" --list-devices

.PHONY: venv
venv: ## Create venv and install Python deps
	@python3 -m venv .venv
	@.venv/bin/python -m pip install -r requirements.txt
