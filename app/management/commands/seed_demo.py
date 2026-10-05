from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from app.models import Grade
from users.models import User

DEMO_PASSWORD = "school-demo-pass"  # noqa: S105 -- default only with DEBUG on

TEACHERS = [
    {"username": "teacher", "first_name": "Anna", "last_name": "Ivanova"},
]
STUDENTS = [
    {"username": "student1", "first_name": "Petr", "last_name": "Petrov"},
    {"username": "student2", "first_name": "Maria", "last_name": "Sidorova"},
]
GRADES = [
    ("student1", "Math", 5),
    ("student1", "Physics", 4),
    ("student2", "Math", 3),
]


class Command(BaseCommand):
    help = "Create a demo teacher, students and a few grades. Existing users are left untouched."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            help=f"Password for created users. Required with DEBUG off; defaults to {DEMO_PASSWORD!r} with DEBUG on.",
        )

    @transaction.atomic
    def handle(self, *args, password=None, **options):
        if password is None:
            if not settings.DEBUG:
                raise CommandError("Pass --password: the built-in demo password is only allowed with DJANGO_DEBUG=1.")
            password = DEMO_PASSWORD
        else:
            try:
                validate_password(password)
            except ValidationError as exc:
                raise CommandError(" ".join(exc.messages)) from exc

        users = {}
        for role, people in ((User.Role.TEACHER, TEACHERS), (User.Role.STUDENT, STUDENTS)):
            for person in people:
                user, created = User.objects.get_or_create(
                    username=person["username"], defaults={**person, "role": role}
                )
                if created:
                    user.set_password(password)
                    user.save(update_fields=["password"])
                users[user.username] = user
                self.stdout.write(f"{'created' if created else 'exists '}  {role:<8} {user.username}")

        teacher = users["teacher"]
        for username, subject, value in GRADES:
            Grade.objects.get_or_create(
                student=users[username], subject=subject, teacher=teacher, defaults={"value": value}
            )

        self.stdout.write(self.style.SUCCESS("Done. Created users share the same password."))
