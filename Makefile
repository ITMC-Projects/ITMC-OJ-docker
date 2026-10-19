ifeq ($(OS),Windows_NT)
SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -Command
endif
.DEFAULT_GOAL := help

ARGS ?=
SERVICE ?=
DEV = powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1

.PHONY: help init build dev up down restart logs ps migrate static seed superuser shell manage check
help:
	$(info ITMC OJ deployment commands)
	$(info )
	$(info Linux production:)
	$(info   make prod-init       Create missing environment files and secrets)
	$(info   make prod            Validate, build, migrate, collect static and start)
	$(info   make prod-build      Build production images)
	$(info   make prod-up         Start/recreate without building)
	$(info   make prod-down       Stop services, preserve data)
	$(info   make prod-restart    Recreate services to apply config changes)
	$(info   make prod-logs       Follow logs; optionally SERVICE=site)
	$(info   make prod-ps         Show service status)
	$(info   make prod-migrate    Apply database migrations)
	$(info   make prod-static     Rebuild static assets)
	$(info   make prod-check      Run production checks)
	$(info   make prod-backup     Back up database, media and problems)
	$(info   make prod-restore    Restore with confirmation; BACKUP=/path/file.tar.gz)
	$(info )
	$(info Windows development requires PowerShell and Docker Desktop:)
	$(info   make dev             Initialize, build, migrate and start dev)
	$(info   make init/build/up/down/restart/logs/ps/migrate/static/check)
	$(info   make seed/superuser/shell or make manage ARGS="check")
	$(info )
	$(info Production setup and HTTPS: PRODUCTION.md)

init build dev up down restart ps migrate static seed superuser shell check:
	@$(DEV) $@

logs:
	@$(DEV) logs $(SERVICE)

manage:
	@$(DEV) manage $(ARGS)

PROD_TARGETS := prod-init prod prod-build prod-up prod-down prod-restart prod-logs prod-ps prod-migrate prod-static prod-check prod-backup prod-restore
.PHONY: $(PROD_TARGETS)
$(PROD_TARGETS): SHELL := /bin/bash
$(PROD_TARGETS): .SHELLFLAGS := -eu -c
$(PROD_TARGETS):
	@bash scripts/prod.sh "$@" "$(SERVICE)" "$(BACKUP)"
