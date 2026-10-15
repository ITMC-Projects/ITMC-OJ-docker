param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'init', 'build', 'dev', 'up', 'down', 'restart', 'logs', 'ps', 'migrate', 'static', 'seed', 'superuser', 'shell', 'manage', 'check')]
    [string]$Task = 'help',
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$DmojRoot = Join-Path $ProjectRoot 'dmoj'
$RootEnv = Join-Path $ProjectRoot '.env'

function Invoke-Compose {
    & docker compose --env-file $RootEnv --project-directory $DmojRoot -f "$DmojRoot/docker-compose.yml" -f "$DmojRoot/docker-compose.dev.yml" @args
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed (exit $LASTEXITCODE)." }
}

function Initialize-Dev {
    # Source can exist while nested asset submodules are still missing.
    & git -C $ProjectRoot submodule update --init --recursive
    if ($LASTEXITCODE -ne 0) { throw 'Cannot initialize source/asset submodules.' }
    foreach ($Directory in @('media', 'problems')) {
        New-Item -ItemType Directory -Force "$DmojRoot/$Directory" | Out-Null
    }
    $Copies = @{
        'config/config.js' = 'repo/websocket/config.js'
        'config/local_settings.py' = 'repo/dmoj/local_settings.py'
        'config/uwsgi.ini' = 'repo/uwsgi.ini'
    }
    foreach ($Source in $Copies.Keys) {
        $Destination = Join-Path $DmojRoot $Copies[$Source]
        if (-not (Test-Path $Destination)) { Copy-Item (Join-Path $DmojRoot $Source) $Destination }
    }
    foreach ($Name in @('mysql', 'mysql-admin', 'site')) {
        $Destination = "$DmojRoot/environment/$Name.env"
        if (-not (Test-Path $Destination)) {
            $Content = [IO.File]::ReadAllText("$Destination.example")
            $Secret = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
            $Content = $Content.Replace('<password>', $Secret).Replace('<secret key>', $Secret)
            [IO.File]::WriteAllText($Destination, $Content, (New-Object Text.UTF8Encoding($false)))
        }
    }
    if (-not (Test-Path -LiteralPath $RootEnv)) {
        # Preserve the existing Django secret and site configuration on upgrade.
        $Content = [IO.File]::ReadAllText("$DmojRoot/environment/site.env")
        $Content = [regex]::Replace($Content, '(?m)^DEBUG=.*$', 'DEBUG=1')
        foreach ($Line in [IO.File]::ReadAllLines((Join-Path $ProjectRoot '.env.example'))) {
            if ($Line -match '^([A-Z][A-Z0-9_]*)=') {
                $Key = $Matches[1]
                if ($Content -notmatch "(?m)^$Key=") { $Content = $Content.TrimEnd() + "`n$Line`n" }
            }
        }
        [IO.File]::WriteAllText($RootEnv, $Content, (New-Object Text.UTF8Encoding($false)))
    }
}

function Build-Dev {
    # Child Dockerfiles use this local base image; build it first.
    Invoke-Compose build base
    Invoke-Compose build site celery bridged wsevent
}

function Migrate-Dev {
    Invoke-Compose up -d --wait --wait-timeout 120 db redis
    Invoke-Compose run --rm --no-deps --entrypoint python3 site manage.py migrate --noinput
}

function Build-Static {
    # Git on Windows may check out the submodule with CRLF. Bash needs LF.
    $StyleScript = Join-Path $DmojRoot 'repo/make_style.sh'
    $Content = [IO.File]::ReadAllText($StyleScript)
    if ($Content.Contains("`r`n")) {
        [IO.File]::WriteAllText($StyleScript, $Content.Replace("`r`n", "`n"), (New-Object Text.UTF8Encoding($false)))
    }
    Invoke-Compose run --rm --no-deps --entrypoint bash site -c 'set -e; bash make_style.sh; python3 manage.py collectstatic --noinput; python3 manage.py compilemessages; python3 manage.py compilejsi18n; cp -r resources /assets/; cp 502.html logo.png robots.txt /assets/'
}

try {
    if ($Task -eq 'help') {
        Write-Output @'
make dev        Initialize, build, migrate, build assets, start all services
make up/down    Start/stop services (preserves data)
make init       Create missing local configuration without overwriting it
make build      Build base image, then application images
make migrate    Apply database migrations
make static     Rebuild CSS, translations and static assets
make seed       Load navbar and language_small fixtures (explicit, once)
make superuser  Create an administrator interactively
make restart    Restart application services after code changes
make logs       Follow logs; optionally SERVICE=site
make ps         Show service status
make shell      Open a container shell
make manage ARGS="check"   Run a Django management command
make check      Validate Compose and run Django checks

Requires GNU Make, PowerShell and Docker Desktop using Linux containers.
Local overrides: edit .env at the repository root, then run make dev or make up.
Website: http://localhost/  |  Judge connection: localhost:9999
Judge worker is external; this repository only includes the bridge.
'@
        exit 0
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install Docker Desktop first.' }
    switch ($Task) {
        init { Initialize-Dev }
        build { Initialize-Dev; Build-Dev }
        dev {
            Initialize-Dev
            Build-Dev
            Migrate-Dev
            Build-Static
            Invoke-Compose up -d site celery bridged wsevent nginx
            Write-Output 'Website: http://localhost/ . Create an admin with: make superuser'
        }
        up { Invoke-Compose up -d site celery bridged wsevent nginx }
        down { Invoke-Compose down }
        restart { Invoke-Compose restart site celery bridged wsevent }
        logs { Invoke-Compose logs --follow --tail 100 @ExtraArgs }
        ps { Invoke-Compose ps }
        migrate { Migrate-Dev }
        static { Initialize-Dev; Build-Static }
        seed { Invoke-Compose exec site python3 manage.py loaddata navbar language_small }
        superuser { Invoke-Compose exec site python3 manage.py createsuperuser }
        shell { Invoke-Compose exec site bash }
        manage { Invoke-Compose exec site python3 manage.py @ExtraArgs }
        check { Invoke-Compose config --quiet; Invoke-Compose run --rm --no-deps --entrypoint python3 site manage.py check }
    }
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
