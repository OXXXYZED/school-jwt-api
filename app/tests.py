from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from app.models import Grade
from users.models import User


class GradeAPITests(APITestCase):
    list_url = reverse("school:grade-list")

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="teacher", role=User.Role.TEACHER, last_name="Ivanova")
        cls.other_teacher = User.objects.create_user(username="teacher2", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="student", role=User.Role.STUDENT)
        cls.other_student = User.objects.create_user(username="student2", role=User.Role.STUDENT)

        cls.own_grade = Grade.objects.create(student=cls.student, teacher=cls.teacher, subject="Math", value=5)
        cls.other_grade = Grade.objects.create(
            student=cls.other_student, teacher=cls.other_teacher, subject="Physics", value=3
        )

    @staticmethod
    def detail_url(grade: Grade) -> str:
        return reverse("school:grade-detail", args=[grade.pk])

    def ids(self, response) -> set[int]:
        return {item["id"] for item in response.data["results"]}

    # --- students -----------------------------------------------------------

    def test_student_sees_only_own_grades(self):
        self.client.force_authenticate(self.student)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.ids(response), {self.own_grade.pk})
        self.assertEqual(response.data["results"][0]["teacher_name"], "Ivanova")

    def test_student_cannot_filter_into_other_students_grades(self):
        self.client.force_authenticate(self.student)
        response = self.client.get(self.list_url, {"student": self.other_student.pk})
        self.assertEqual(self.ids(response), set())

    def test_student_cannot_read_other_students_grade(self):
        self.client.force_authenticate(self.student)
        response = self.client.get(self.detail_url(self.other_grade))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_student_cannot_write(self):
        self.client.force_authenticate(self.student)
        payload = {"student": self.student.pk, "subject": "Math", "value": 5}

        self.assertEqual(self.client.post(self.list_url, payload).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.patch(self.detail_url(self.own_grade), {"value": 1}).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(self.client.delete(self.detail_url(self.own_grade)).status_code, status.HTTP_403_FORBIDDEN)

    # --- teachers -----------------------------------------------------------

    def test_teacher_sees_all_grades_and_can_filter(self):
        self.client.force_authenticate(self.teacher)

        self.assertEqual(self.ids(self.client.get(self.list_url)), {self.own_grade.pk, self.other_grade.pk})
        self.assertEqual(
            self.ids(self.client.get(self.list_url, {"student": self.other_student.pk})), {self.other_grade.pk}
        )
        self.assertEqual(self.ids(self.client.get(self.list_url, {"subject": "math"})), {self.own_grade.pk})

    def test_invalid_student_filter(self):
        self.client.force_authenticate(self.teacher)
        response = self.client.get(self.list_url, {"student": "abc"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_teacher_creates_grade_as_author(self):
        self.client.force_authenticate(self.teacher)

        response = self.client.post(
            self.list_url,
            {"student": self.student.pk, "subject": "History", "value": 4, "teacher": self.other_teacher.pk},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["teacher"], self.teacher.pk)
        self.assertEqual(response.data["teacher_name"], "Ivanova")
        self.assertEqual(Grade.objects.get(pk=response.data["id"]).teacher, self.teacher)

    def test_grade_validation(self):
        self.client.force_authenticate(self.teacher)
        inactive = User.objects.create_user(username="expelled", is_active=False)
        cases = {
            "value too high": {"student": self.student.pk, "subject": "Math", "value": 6},
            "value too low": {"student": self.student.pk, "subject": "Math", "value": 0},
            "grade for a teacher": {"student": self.other_teacher.pk, "subject": "Math", "value": 5},
            "inactive student": {"student": inactive.pk, "subject": "Math", "value": 5},
            "missing subject": {"student": self.student.pk, "value": 5},
        }
        for name, payload in cases.items():
            with self.subTest(name):
                self.assertEqual(self.client.post(self.list_url, payload).status_code, status.HTTP_400_BAD_REQUEST)

    def test_teacher_updates_and_deletes_own_grade(self):
        self.client.force_authenticate(self.teacher)

        response = self.client.patch(self.detail_url(self.own_grade), {"value": 4, "comment": "Retake"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.own_grade.refresh_from_db()
        self.assertEqual((self.own_grade.value, self.own_grade.comment), (4, "Retake"))

        self.assertEqual(self.client.delete(self.detail_url(self.own_grade)).status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Grade.objects.filter(pk=self.own_grade.pk).exists())

    def test_teacher_cannot_modify_another_teachers_grade(self):
        self.client.force_authenticate(self.teacher)

        self.assertEqual(self.client.get(self.detail_url(self.other_grade)).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.patch(self.detail_url(self.other_grade), {"value": 5}).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(self.client.delete(self.detail_url(self.other_grade)).status_code, status.HTTP_403_FORBIDDEN)
        self.other_grade.refresh_from_db()
        self.assertEqual(self.other_grade.value, 3)

    # --- anonymous ----------------------------------------------------------

    def test_anonymous_unauthorized(self):
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            self.client.post(self.list_url, {"student": self.student.pk, "subject": "Math", "value": 5}).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )


class SeedDemoCommandTests(TestCase):
    def test_requires_explicit_password_without_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
        self.assertFalse(User.objects.exists())

    def test_rejects_weak_password(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", password="123", stdout=StringIO())

    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
    def test_creates_demo_data_idempotently(self):
        for _ in range(2):
            call_command("seed_demo", password="Demo-pass-for-reviewers", stdout=StringIO())

        teacher = User.objects.get(username="teacher")
        self.assertTrue(teacher.is_teacher)
        self.assertTrue(teacher.check_password("Demo-pass-for-reviewers"))
        self.assertEqual(User.objects.filter(role=User.Role.STUDENT).count(), 2)
        self.assertEqual(Grade.objects.count(), 3)
