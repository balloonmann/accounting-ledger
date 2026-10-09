#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        "config.settings.test" if len(sys.argv) > 1 and sys.argv[1] == "test" else "config.settings.development",
    )
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
