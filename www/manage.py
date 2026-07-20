#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main():
    """Run administrative tasks."""
    import dotenv

    project_dir = os.path.dirname(os.path.abspath(__file__))
    env_file = os.path.join(os.path.dirname(project_dir), ".env")
    dotenv.load_dotenv(env_file)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "penhorzap.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
