"""Fail closed without printing credentials; also validate untrusted backup archives."""
import io
import ipaddress
import pathlib
import re
import sys
import tarfile
from urllib.parse import urlsplit


def require(condition, message):
    if not condition:
        raise ValueError(message)


def archive(path):
    with tarfile.open(path, 'r:gz') as outer:
        members = outer.getmembers()
        require({m.name for m in members} == {'FORMAT', 'database.sql', 'files.tar.gz'}
                and len(members) == 3 and all(m.isfile() for m in members), 'Invalid backup members')
        require(outer.extractfile('FORMAT').read() == b'ITMC-OJ-BACKUP-v1\n', 'Unknown backup format')
        require(outer.getmember('database.sql').size > 0, 'Empty SQL backup')
        with tarfile.open(fileobj=outer.extractfile('files.tar.gz'), mode='r|gz') as inner:
            for m in inner:
                p = pathlib.PurePosixPath(m.name)
                require(not p.is_absolute() and '..' not in p.parts and p.parts
                        and p.parts[0] in ('media', 'problems')
                        and (m.isfile() or m.isdir()), 'Unsafe backup data member')


def validate(root):
    values = {}
    for name in ('prod', 'site', 'mysql', 'mysql-admin'):
        path = root / 'env' / (name + '.env')
        require(path.is_file(), 'Missing ' + str(path) + '; run make prod-init')
        for line in path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            key, sep, value = line.partition('=')
            require(sep and re.fullmatch('[A-Z][A-Z0-9_]*', key), 'Invalid env syntax in ' + path.name)
            require(key not in values, 'Duplicate env key: ' + key)
            require(value and not any(w in value.lower() for w in ('example.', 'changeme', '<', 'replace_me')),
                    'Missing or placeholder setting: ' + key)
            require(value == value.strip() and not any(c in value for c in "'\"$`"),
                    'Use unquoted literal env values without interpolation: ' + key)
            values[key] = value
    for key in ('DEBUG', 'SECRET_KEY', 'HOST', 'ALLOWED_HOSTS', 'SITE_FULL_URL', 'MEDIA_URL',
                'CSRF_TRUSTED_ORIGINS', 'MYSQL_HOST', 'MYSQL_DATABASE', 'MYSQL_USER', 'MYSQL_PASSWORD',
                'MYSQL_ROOT_PASSWORD', 'REDIS_CACHING_URL', 'CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND',
                'OTS_SYNC_API_URL', 'OTS_SYNC_SERVICE_TOKEN', 'OTS_SYNC_ALLOW_INTERNAL_HTTP',
                'OTS_SYNC_AUTO_ENABLED', 'OTS_SYNC_TIMEOUT_SECONDS', 'OTS_SYNC_PAGE_SIZE', 'JUDGE_BIND_IP'):
        require(key in values, 'Required setting missing: ' + key)
    require(values['DEBUG'] == '0', 'Production requires DEBUG=0')
    require(values['OTS_SYNC_ALLOW_INTERNAL_HTTP'] == '0', 'Production OTS requires HTTPS')
    for key, length in (('SECRET_KEY', 50), ('MYSQL_PASSWORD', 32), ('MYSQL_ROOT_PASSWORD', 32),
                        ('OTS_SYNC_SERVICE_TOKEN', 32)):
        require(len(values[key]) >= length and len(set(values[key])) >= 8, 'Weak secret: ' + key)
    host = values['HOST']
    require(bool(re.fullmatch(r'[a-zA-Z0-9.-]+', host)) and '.' in host, 'HOST must be a public DNS name')
    hosts = values['ALLOWED_HOSTS'].split(',')
    require(host in hosts and all(re.fullmatch(r'[a-zA-Z0-9.-]+', h) for h in hosts), 'Invalid ALLOWED_HOSTS')
    for key in ('SITE_FULL_URL', 'MEDIA_URL', 'OTS_SYNC_API_URL'):
        u = urlsplit(values[key])
        require(u.scheme == 'https' and u.hostname and not u.username and not u.password,
                'Requires valid HTTPS URL: ' + key)
    require(urlsplit(values['SITE_FULL_URL']).netloc == host, 'SITE_FULL_URL must match HOST')
    for origin in values['CSRF_TRUSTED_ORIGINS'].split(','):
        u = urlsplit(origin)
        require(u.scheme == 'https' and u.hostname and u.path in ('', '/') and not u.query,
                'Invalid CSRF HTTPS origin')
    for key in ('REDIS_CACHING_URL', 'CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND'):
        require(urlsplit(values[key]).scheme in ('redis', 'rediss'), 'Invalid Redis URL: ' + key)
    require(0 < float(values['OTS_SYNC_TIMEOUT_SECONDS']) <= 120, 'Invalid OTS timeout')
    require(1 <= int(values['OTS_SYNC_PAGE_SIZE']) <= 1000, 'Invalid OTS page size')
    require(values['OTS_SYNC_AUTO_ENABLED'] in ('0', '1'), 'Invalid OTS auto flag')
    password_keys = ('OTS_PASSWORD_SERVICE_TOKEN', 'OTS_CREDENTIAL_READ_TOKEN', 'OTS_CALLBACK_TOKEN')
    for key in password_keys:
        token = values.get(key, '')
        require(len(token) >= 32 and len(set(token)) >= 8 and not any(c.isspace() for c in token),
                'Invalid password integration secret: ' + key)
    require(len({values[k] for k in password_keys + ('OTS_SYNC_SERVICE_TOKEN',)}) == 4,
            'Password service capabilities require distinct secrets')
    require(urlsplit(values.get('OTS_PASSWORD_API_URL', '')).scheme == 'https', 'Password API requires HTTPS')
    require(values.get('OTS_PASSWORD_CHANGE_ENABLED') in ('0', '1'), 'Invalid password change flag')
    require(0 < float(values.get('OTS_PASSWORD_TIMEOUT_SECONDS', '0')) <= 10, 'Invalid password timeout')
    ipaddress.ip_address(values['JUDGE_BIND_IP'])
    for file in ('django/local_settings.py', 'uwsgi.ini', 'websocket/config.js', 'nginx/nginx.conf', 'nginx/default.conf'):
        require((root / 'config' / file).is_file(), 'Missing production config: ' + file)
    for directory in ('media', 'problems', 'backups'):
        require((root / 'data' / directory).is_dir(), 'Missing data directory; run make prod-init')
    print('Production environment and config validation passed (secrets hidden).')


if __name__ == '__main__':
    try:
        if sys.argv[1] == '--archive':
            archive(sys.argv[2])
        else:
            validate(pathlib.Path(sys.argv[1]))
    except (ValueError, OSError, tarfile.TarError) as error:
        sys.exit('ERROR: ' + str(error))
