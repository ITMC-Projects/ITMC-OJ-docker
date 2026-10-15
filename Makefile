SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -Command
.DEFAULT_GOAL := help

ARGS ?=
SERVICE ?=
DEV = powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1

.PHONY: help init build dev up down restart logs ps migrate static seed superuser shell manage check
help:
	@$(DEV) help

init build dev up down restart ps migrate static seed superuser shell check:
	@$(DEV) $@

logs:
	@$(DEV) logs $(SERVICE)

manage:
	@$(DEV) manage $(ARGS)
