"""Real Django ORM/MPTT tests with SQLite and model classes from the source submodule.

Requires Django 3.2 and django-mptt (the application's dependencies).
Does not load the complete OJ app or require MariaDB/Redis.
"""
import ast
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

import django
from django.conf import settings

settings.configure(INSTALLED_APPS=['mptt'], USE_I18N=False, SECRET_KEY='test-only',
                   DEFAULT_AUTO_FIELD='django.db.models.AutoField',
                   DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}})
django.setup()

from django.db import connection, models
from django.utils.functional import cached_property
from mptt.fields import TreeForeignKey
from mptt.models import MPTTModel

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'dmoj/repo/judge/fixtures'
spec = importlib.util.spec_from_file_location('production_bootstrap', ROOT / 'dmoj/production/bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def source_model(file, name):
    node = next(n for n in ast.parse(file.read_text(encoding='utf-8')).body
                if isinstance(n, ast.ClassDef) and n.name == name)
    meta = next(n for n in node.body if isinstance(n, ast.ClassDef) and n.name == 'Meta')
    # Register isolated source models under the installed test app, without loading
    # unrelated OJ integrations. Fields and MPTT behavior are the source definitions.
    meta.body.append(ast.Assign(targets=[ast.Name(id='app_label', ctx=ast.Store())],
                                value=ast.Constant(value='mptt')))
    context = {'__name__': __name__, 'models': models, 'cached_property': cached_property,
               '_': lambda text: text, 'MPTTModel': MPTTModel, 'TreeForeignKey': TreeForeignKey,
               'validate_regex': lambda value: re.compile(value)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(file), 'exec'), context)
    return context[name]


Language = source_model(ROOT / 'dmoj/repo/judge/models/runtime.py', 'Language')
NavigationBar = source_model(ROOT / 'dmoj/repo/judge/models/interface.py', 'NavigationBar')


class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            editor.create_model(Language)
            editor.create_model(NavigationBar)

    def setUp(self):
        NavigationBar.objects.all().delete()
        Language.objects.all().delete()

    def seed(self, default='CPP17', fixtures=FIXTURES):
        bootstrap.bootstrap(Language, NavigationBar, default, fixtures)

    def test_fresh_database_registration_language_and_tree_and_rerun(self):
        self.seed()
        self.assertEqual(Language.objects.get(key='CPP17').name, 'C++17')
        about = NavigationBar.objects.get(key='about')
        self.assertEqual(NavigationBar.objects.get(key='status').parent_id, about.pk)
        self.assertEqual(about.get_descendant_count(), 3)
        before = list(Language.objects.values()), list(NavigationBar.objects.values())
        self.seed()
        self.assertEqual(before, (list(Language.objects.values()), list(NavigationBar.objects.values())))
        bootstrap.check_default(Language, 'CPP17')

    def test_preserves_existing_ids_customizations_and_partial_menu(self):
        fields = dict(json.loads((FIXTURES / 'language_small.json').read_text())[0]['fields'])
        fields.update(key='CUSTOM', name='My language')
        existing = Language.objects.create(pk=1, **fields)
        custom_cpp = Language.objects.create(key='CPP17', name='Customized C++', common_name='C++',
                                             ace='c_cpp', pygments='cpp', extension='cc')
        nav = NavigationBar.objects.create(key='home', label='My menu', order=1, path='/', regex='^/$')
        self.seed()
        existing.refresh_from_db()
        custom_cpp.refresh_from_db()
        self.assertEqual(existing.name, 'My language')
        self.assertEqual(custom_cpp.name, 'Customized C++')
        self.assertNotEqual(Language.objects.get(key='CPP03').pk, 1)
        self.assertEqual(list(NavigationBar.objects.values_list('pk', 'label')), [(nav.pk, 'My menu')])

    def test_unknown_default_rejected_without_writes(self):
        with self.assertRaisesRegex(ValueError, 'absent from database'):
            self.seed('UNKNOWN')
        self.assertEqual(Language.objects.count(), 0)
        self.assertEqual(NavigationBar.objects.count(), 0)

    def test_existing_custom_default_accepted(self):
        Language.objects.create(key='CUSTOM', name='Custom runtime')
        self.seed('CUSTOM')
        bootstrap.check_default(Language, 'CUSTOM')

    def test_invalid_navbar_rolls_back_all_bootstrap_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            fixtures = Path(temp)
            shutil.copy(FIXTURES / 'language_small.json', fixtures / 'language_small.json')
            rows = json.loads((FIXTURES / 'navbar.json').read_text())
            rows[0]['fields']['parent'] = 99999
            (fixtures / 'navbar.json').write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, 'unresolved parent'):
                self.seed(fixtures=fixtures)
        self.assertEqual(Language.objects.count(), 0)
        self.assertEqual(NavigationBar.objects.count(), 0)

    def test_check_detects_missing_default(self):
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            bootstrap.check_default(Language, 'CPP17')

    def test_registration_initial_reproduces_error_then_succeeds_after_seed(self):
        file = ROOT / 'dmoj/repo/judge/views/register.py'
        view = next(n for n in ast.parse(file.read_text(encoding='utf-8')).body
                    if isinstance(n, ast.ClassDef) and n.name == 'RegistrationView')
        method = next(n for n in view.body if isinstance(n, ast.FunctionDef) and n.name == 'get_initial')
        test_view = ast.ClassDef(name='RegistrationView', bases=[ast.Name(id='BaseView', ctx=ast.Load())],
                                 keywords=[], body=[method], decorator_list=[])
        settings.DEFAULT_USER_LANGUAGE = 'CPP17'
        settings.DEFAULT_USER_TIME_ZONE = 'Asia/Ho_Chi_Minh'
        context = {'Language': Language, 'settings': settings,
                   'BaseView': type('BaseView', (), {'get_initial': lambda self, *args, **kwargs: {}})}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[test_view], type_ignores=[])), str(file), 'exec'), context)
        view = context['RegistrationView']()
        with self.assertRaises(Language.DoesNotExist):
            view.get_initial()
        self.seed()
        self.assertEqual(view.get_initial()['language'].key, 'CPP17')


if __name__ == '__main__':
    unittest.main(verbosity=2)
