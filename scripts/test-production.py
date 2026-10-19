"""Static production contract tests. No daemon, network or production credentials needed."""
import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / 'dmoj/production'
spec = importlib.util.spec_from_file_location('production_validate', PROD / 'validate.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
BASH = os.environ.get('BASH_BIN', 'bash')


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.p = self.root / 'dmoj/production'
        shutil.copytree(PROD / 'env', self.p / 'env', ignore=shutil.ignore_patterns('*.env'))
        shutil.copytree(PROD / 'config', self.p / 'config')
        shutil.copy(PROD / 'bootstrap.py', self.p / 'bootstrap.py')
        (self.root / 'scripts').mkdir()
        shutil.copy(ROOT / 'scripts/prod.sh', self.root / 'scripts/prod.sh')
        self.init()

    def tearDown(self):
        self.temp.cleanup()

    def init(self):
        subprocess.run([BASH, 'scripts/prod.sh', 'prod-init'], cwd=self.root,
                       check=True, capture_output=True)

    def valid_env(self):
        file = self.p / 'env/site.env'
        file.write_text(file.read_text().replace('oj.example.com', 'oj.itmc.test').replace(
            'ots.example.com', 'ots.itmc.test'))

    def env(self):
        result = {}
        for file in (self.p / 'env').glob('*.env'):
            for line in file.read_text().splitlines():
                if line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    result[k] = v
        return result

    def test_init_idempotent_and_secrets_distinct(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.p / 'env').glob('*.env')}
        self.init()
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.p / 'env').glob('*.env')})
        values = self.env()
        secrets = [values[k] for k in ('SECRET_KEY', 'MYSQL_PASSWORD', 'MYSQL_ROOT_PASSWORD', 'OTS_SYNC_SERVICE_TOKEN')]
        self.assertEqual(len(set(secrets)), 4)
        self.assertTrue(all(len(s) == 128 for s in secrets))

    def test_env_rejects_placeholder_missing_and_weak_secrets(self):
        with self.assertRaisesRegex(ValueError, 'HOST'):
            validator.validate(self.p)
        self.valid_env()
        validator.validate(self.p)
        file = self.p / 'env/site.env'
        original = file.read_text()
        file.write_text(original.replace('DEBUG=0', 'DEBUG=1'))
        with self.assertRaisesRegex(ValueError, 'DEBUG'):
            validator.validate(self.p)
        file.write_text(original.replace(self.env()['SECRET_KEY'], 'a' * 64))
        with self.assertRaisesRegex(ValueError, 'Weak secret'):
            validator.validate(self.p)
        file.write_text(original.replace('ALLOWED_HOSTS=oj.itmc.test', 'ALLOWED_HOSTS=*'))
        with self.assertRaisesRegex(ValueError, 'ALLOWED_HOSTS'):
            validator.validate(self.p)

    def test_django_policy_execution_32_and_4(self):
        # Exercise config policy with Django API stubs; real deployment checks require image runtime.
        self.valid_env()
        django = types.ModuleType('django')
        exceptions = types.ModuleType('django.core.exceptions')
        exceptions.ImproperlyConfigured = ValueError
        modules = {'django': django, 'django.core': types.ModuleType('django.core'),
                   'django.core.exceptions': exceptions}
        for version in ((3, 2), (4, 2)):
            django.VERSION = version
            context = {'os': os, 'datetime': datetime, 'INSTALLED_APPS': (),
                       'STATICFILES_FINDERS': (), 'MIDDLEWARE': ('existing.middleware',)}
            with patch.dict(sys.modules, modules), patch.dict(os.environ, self.env(), clear=True):
                exec(compile((PROD / 'config/django/local_settings.py').read_text(), 'local_settings.py', 'exec'), context)
            self.assertFalse(context['DEBUG'])
            self.assertTrue(context['SESSION_COOKIE_SECURE'])
            self.assertTrue(context['CSRF_COOKIE_SECURE'])
            self.assertTrue(context['SECURE_SSL_REDIRECT'])
            self.assertEqual(context['MIDDLEWARE'][0], 'django.middleware.security.SecurityMiddleware')
            self.assertEqual(context['CSRF_TRUSTED_ORIGINS'],
                             ['oj.itmc.test'] if version < (4, 0) else ['https://oj.itmc.test'])

    def test_compose_merge_contract(self):
        # Use temporary env files without modifying real/developer env.
        shutil.copy(ROOT / 'dmoj/docker-compose.yml', self.root / 'dmoj/docker-compose.yml')
        shutil.copy(ROOT / 'dmoj/docker-compose.prod.yml', self.root / 'dmoj/docker-compose.prod.yml')
        args = ['docker', 'compose', '-p', 'itmc-oj-prod', '--env-file', str(self.p / 'env/prod.env'),
                '-f', str(self.root / 'dmoj/docker-compose.yml'), '-f', str(self.root / 'dmoj/docker-compose.prod.yml'),
                'config', '--format', 'json']
        result = subprocess.run(args, check=True, capture_output=True, text=True)
        cfg = json.loads(result.stdout)
        services = cfg['services']
        published = [(name, p['host_ip'], str(p['published'])) for name, s in services.items() for p in s.get('ports', [])]
        self.assertCountEqual(published, [('nginx', '127.0.0.1', '10080'), ('bridged', '127.0.0.1', '9999')])
        for name in ('site', 'celery', 'beat', 'bridged'):
            s = services[name]
            self.assertEqual(s['depends_on']['db']['condition'], 'service_healthy')
            mounts = {v['target'].rstrip('/'): v for v in s['volumes']}
            self.assertTrue(mounts['/site/dmoj/local_settings.py']['read_only'])
            self.assertNotIn('/site', mounts)
            for target in ('/media', '/problems'):
                self.assertIn('production', mounts[target]['source'])
            self.assertNotIn('MYSQL_ROOT_PASSWORD', s['environment'])
            self.assertNotIn('host.docker.internal', json.dumps(s))
        self.assertTrue(next(v for v in services['wsevent']['volumes'] if v['target'].endswith('config.js'))['read_only'])
        self.assertEqual(services['beat']['scale'], 1)
        self.assertEqual(services['db']['volumes'][0]['source'], 'prod_database')
        self.assertTrue(all(v['name'].startswith('itmc-oj-prod_') for v in cfg['volumes'].values()))
        for name in ('db', 'redis', 'site', 'celery', 'beat', 'bridged', 'wsevent', 'nginx'):
            self.assertEqual(services[name]['restart'], 'unless-stopped')
            self.assertEqual(services[name]['logging']['options']['max-size'], '10m')
        for s in services.values():
            for mount in s.get('volumes', []):
                if mount['type'] == 'bind' and '/config/' in mount['source'].replace('\\', '/'):
                    relative = mount['source'].replace('\\', '/').split('production/config/', 1)[1]
                    self.assertTrue((PROD / 'config' / relative).is_file())
                    self.assertTrue(mount['read_only'])

    def test_backup_validation_rejects_traversal(self):
        for name, valid in [('media/test.txt', True), ('../escape', False)]:
            nested = io.BytesIO()
            with tarfile.open(fileobj=nested, mode='w:gz') as tf:
                item = tarfile.TarInfo(name); item.size = 1
                tf.addfile(item, io.BytesIO(b'x'))
            file = self.root / 'backup.tar.gz'
            with tarfile.open(file, 'w:gz') as tf:
                for member, data in [('FORMAT', b'ITMC-OJ-BACKUP-v1\n'), ('database.sql', b'SQL'), ('files.tar.gz', nested.getvalue())]:
                    item = tarfile.TarInfo(member); item.size = len(data)
                    tf.addfile(item, io.BytesIO(data))
            if valid:
                validator.archive(file)
            else:
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    validator.archive(file)

    def test_prod_bootstraps_before_static_and_start_and_stops_on_failure(self):
        # Mock only external commands to exercise the actual Bash orchestration.
        (self.root / 'dmoj/repo').mkdir()
        (self.root / 'dmoj/repo/manage.py').touch()
        log = self.root / 'commands.log'
        command = '''
docker() {
  printf '%s\\n' "$*" >> "$TEST_COMMAND_LOG"
  if [[ "${TEST_FAIL_BOOTSTRAP:-0}" == 1 && "$*" == *"site /production-bootstrap.py" ]]; then return 23; fi
}
python3() { return 0; }
export -f docker python3
bash scripts/prod.sh prod
'''
        for fail in ('0', '1'):
            log.write_text('')
            env = dict(os.environ, TEST_COMMAND_LOG=log.as_posix(), TEST_FAIL_BOOTSTRAP=fail)
            result = subprocess.run([BASH, '-c', command], cwd=self.root, env=env, capture_output=True)
            lines = log.read_text().splitlines()
            seed = next(i for i, line in enumerate(lines) if 'site /production-bootstrap.py' in line)
            migration = next(i for i, line in enumerate(lines) if 'manage.py migrate --noinput' in line)
            self.assertLess(migration, seed)
            self.assertIn('/production-bootstrap.py:ro', lines[seed])
            if fail == '1':
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any('collectstatic' in line or 'up -d --no-build' in line for line in lines))
            else:
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                static = next(i for i, line in enumerate(lines) if 'collectstatic' in line)
                start = next(i for i, line in enumerate(lines) if 'up -d --no-build' in line)
                self.assertLess(seed, static)
                self.assertLess(static, start)
                self.assertTrue(any('site /production-bootstrap.py --check' in line for line in lines))


if __name__ == '__main__':
    unittest.main(verbosity=2)
