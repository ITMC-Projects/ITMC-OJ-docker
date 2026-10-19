"""Initialize missing deployment data without loading fixture primary keys."""
import json
import os
from pathlib import Path
import sys


def check_default(Language, default_key):
    if Language.objects.filter(key=default_key).count() != 1:
        raise ValueError('DEFAULT_USER_LANGUAGE=%s must match exactly one database language. '
                         'Run make prod; for a custom key, create that language in Admin first.' % default_key)


def bootstrap(Language, NavigationBar, default_key, fixture_dir):
    from django.db import transaction

    languages = json.loads((fixture_dir / 'language_small.json').read_text(encoding='utf-8'))
    language_fields = [row['fields'] for row in languages if row['model'] == 'judge.language']
    # Fail before any write if a custom default cannot be initialized from source.
    if not Language.objects.filter(key=default_key).exists() and not any(
            fields['key'] == default_key for fields in language_fields):
        raise ValueError('DEFAULT_USER_LANGUAGE=%s is absent from database and language_small.json. '
                         'Create the custom language in Admin or configure a fixture language.' % default_key)

    language_count = navbar_count = 0
    with transaction.atomic():
        for fields in language_fields:
            defaults = dict(fields)
            key = defaults.pop('key')
            _, created = Language.objects.get_or_create(key=key, defaults=defaults)
            language_count += int(created)

        # Existing menus, including intentionally removed items, belong to the admin.
        if not NavigationBar.objects.exists():
            pending = json.loads((fixture_dir / 'navbar.json').read_text(encoding='utf-8'))
            parents = {}
            while pending:
                remaining = []
                for row in pending:
                    fields = dict(row['fields'])
                    parent_id = fields.pop('parent')
                    if parent_id is not None and parent_id not in parents:
                        remaining.append(row)
                        continue
                    key = fields.pop('key')
                    # Let MPTT calculate the tree; never reuse fixture IDs/tree metadata.
                    for name in ('lft', 'rght', 'tree_id', 'level'):
                        fields.pop(name, None)
                    fields['parent'] = parents.get(parent_id)
                    item, created = NavigationBar.objects.get_or_create(key=key, defaults=fields)
                    parents[row['pk']] = item
                    navbar_count += int(created)
                if len(remaining) == len(pending):
                    raise ValueError('Invalid navbar fixture: unresolved parent references')
                pending = remaining
        check_default(Language, default_key)
    print('Production bootstrap: added %d languages, %d navigation items; existing data preserved.'
          % (language_count, navbar_count))


def main():
    sys.path.insert(0, '/site')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dmoj.settings')
    import django
    django.setup()
    from django.conf import settings
    from judge.models import Language, NavigationBar

    if sys.argv[1:] == ['--check']:
        check_default(Language, settings.DEFAULT_USER_LANGUAGE)
        print('Default registration language exists.')
    elif not sys.argv[1:]:
        bootstrap(Language, NavigationBar, settings.DEFAULT_USER_LANGUAGE, Path('/site/judge/fixtures'))
    else:
        raise ValueError('Usage: production-bootstrap.py [--check]')


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        sys.exit('ERROR: ' + str(error))
