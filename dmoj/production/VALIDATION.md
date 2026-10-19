# Validation record — 2026-10-20

Host: Windows, GNU Make 4.4.1, Git Bash, Python 3.12 runtime, Docker Compose v5.6.0.

Passed:

* `bash -n scripts/prod.sh`.
* `make -n prod` emits the Linux Bash command; `make -n dev` still emits the
  original PowerShell command. `git diff --exit-code -- scripts/dev.ps1
  dmoj/docker-compose.yml dmoj/docker-compose.dev.yml` confirms these remain unchanged.
* `docker compose -p itmc-oj-prod --env-file dmoj/production/env/prod.env
  -f dmoj/docker-compose.yml -f dmoj/docker-compose.prod.yml config --quiet`.
* `python3 scripts/test-production.py`: five tests pass. Tests exercise initializer
  idempotency/random independent secrets, fail-closed environment validation,
  Django security policy execution with API stubs for CSRF version compatibility,
  merged Compose port/mount/persistence/dependency/isolation contracts, and backup
  archive path traversal rejection. They use temporary env files and do not require
  Docker daemon or production secrets. Django stubs do not validate actual Django.
* `prod-init` run twice locally; generated env files are Git-ignored. Validator
  correctly refuses the initialized example HOST before any startup.
* `git diff --check` and Python syntax compilation.

On Windows, the test was run with `BASH_BIN=C:/Program Files/Git/bin/bash.exe`
and the installed Codex Python runtime; on Linux use `python3 scripts/test-production.py`.

Not run: Docker builds/container startup, actual Django deployment checks/migrations,
static compilation inside image, Nginx runtime, real SQL/data backup and restore,
Linux VPS runtime and end-to-end login/admin/monitoring/OTS/WebSocket/judge grading.
`docker info` reports that the Docker Desktop Linux engine named pipe is absent.
These are required staging checks before a live rollout; this record does not certify
runtime or end-to-end acceptance.

## Production bootstrap regression checks

`make prod` now runs a read-only-mounted bootstrap script after migrate and before
static/start, and checks the default registration language during prod-check.

* `python3 scripts/test-production.py`: six tests pass, including the real Bash
  deployment order with external commands mocked. Bootstrap failure prevents static
  build and service start.
* `python3 scripts/test-production-bootstrap.py`: seven tests pass using real Django
  3.2.25 ORM, django-mptt 0.13.4 and an in-memory SQLite database. Source Language and
  NavigationBar class definitions are loaded under an isolated test app; unrelated
  OJ integrations/signals are not loaded. Tests cover empty database initialization,
  existing primary keys/customizations, rerun idempotency, custom/missing defaults,
  MPTT parent relationships and transaction rollback on an invalid menu fixture.
  The source RegistrationView.get_initial method reproduces Language.DoesNotExist
  before bootstrap and succeeds with CPP17 afterwards.
* Bootstrap tests used a temporary Python 3.12 virtualenv with Django/MPTT dependencies;
  application images and their Python 3.11 runtime were not changed. These isolated
  tests do not certify complete Django 3.2/Python compatibility.
* Bash syntax, Make dry-run, Compose merge and staged whitespace checks pass.

Docker daemon remains unavailable. Full app/MariaDB migration, bootstrap with real
signals/Redis, HTTP registration and image/container runtime still require VPS validation.
