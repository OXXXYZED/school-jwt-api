import base64
from datetime import timedelta

import jwt
from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from users.basic_auth import InvalidBasicCredentials, decode_basic_credentials, parse_basic_authorization
from users.models import User

PASSWORD = "Str0ng-pass-for-tests"
FAST_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def basic_header(username: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode("ascii")


class BasicCredentialsParsingTests(SimpleTestCase):
    def test_decodes_username_and_password(self):
        encoded = base64.b64encode(b"ivan:secret").decode()
        self.assertEqual(decode_basic_credentials(encoded), ("ivan", "secret"))

    def test_password_may_contain_colons(self):
        encoded = base64.b64encode(b"ivan:a:b:c").decode()
        self.assertEqual(decode_basic_credentials(encoded), ("ivan", "a:b:c"))

    def test_utf8_credentials(self):
        encoded = base64.b64encode("иван:пароль".encode()).decode()
        self.assertEqual(decode_basic_credentials(encoded), ("иван", "пароль"))

    def test_rejects_invalid_input(self):
        cases = {
            "not base64": "%%%",
            "garbage after valid base64": base64.b64encode(b"ivan:secret").decode() + "!!",
            "no colon": base64.b64encode(b"ivan").decode(),
            "empty username": base64.b64encode(b":secret").decode(),
            "not utf-8": base64.b64encode(b"\xff\xfe:secret").decode(),
            "non-ascii input": "иван",
            "empty": "",
        }
        for name, value in cases.items():
            with self.subTest(name), self.assertRaises(InvalidBasicCredentials):
                decode_basic_credentials(value)

    def test_parse_header_ignores_other_schemes(self):
        self.assertIsNone(parse_basic_authorization(""))
        self.assertIsNone(parse_basic_authorization("Bearer abc.def.ghi"))
        self.assertEqual(parse_basic_authorization(basic_header("ivan", "pw")), ("ivan", "pw"))
        self.assertEqual(
            parse_basic_authorization(basic_header("ivan", "pw").replace("Basic", "basic")), ("ivan", "pw")
        )


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class AuthAPITestCase(APITestCase):
    def setUp(self):
        cache.clear()  # throttle counters live in the cache
        self.student = User.objects.create_user(
            username="student", password=PASSWORD, role=User.Role.STUDENT, first_name="Petr"
        )
        self.teacher = User.objects.create_user(username="teacher", password=PASSWORD, role=User.Role.TEACHER)

    def login(self, username: str, password: str = PASSWORD):
        return self.client.post(reverse("users:login"), HTTP_AUTHORIZATION=basic_header(username, password))

    def authorize(self, access: str):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")


class LoginTests(AuthAPITestCase):
    def test_login_returns_token_pair_and_user(self):
        response = self.login("teacher")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["username"], "teacher")
        self.assertEqual(response.data["user"]["role"], User.Role.TEACHER)

        payload = jwt.decode(response.data["access"], settings.SIMPLE_JWT["SIGNING_KEY"], algorithms=["HS256"])
        self.assertEqual(payload["token_type"], "access")
        self.assertEqual(payload["user_id"], str(self.teacher.pk))
        self.assertEqual(payload["role"], User.Role.TEACHER)
        self.assertEqual(payload["username"], "teacher")

        self.teacher.refresh_from_db()
        self.assertIsNotNone(self.teacher.last_login)

    def test_access_token_authenticates_requests(self):
        self.authorize(self.login("student").data["access"])

        response = self.client.get(reverse("users:me"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "student")

    def test_utf8_password(self):
        User.objects.create_user(username="olga", password="пароль-ученицы-2024")
        self.assertEqual(self.login("olga", "пароль-ученицы-2024").status_code, status.HTTP_200_OK)

    def test_wrong_password(self):
        response = self.login("teacher", "wrong")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(response["WWW-Authenticate"].startswith("Basic"))
        self.assertNotIn("access", response.data)

    def test_unknown_and_inactive_users_get_the_same_error(self):
        User.objects.create_user(username="expelled", password=PASSWORD, is_active=False)
        wrong_password = self.login("teacher", "wrong").data
        for username in ("nobody", "expelled"):
            with self.subTest(username):
                response = self.login(username)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
                self.assertEqual(response.data, wrong_password)

    def test_missing_or_non_basic_header(self):
        for headers in ({}, {"HTTP_AUTHORIZATION": "Bearer something"}):
            with self.subTest(headers):
                response = self.client.post(reverse("users:login"), **headers)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
                self.assertIn("WWW-Authenticate", response)

    def test_malformed_base64(self):
        response = self.client.post(reverse("users:login"), HTTP_AUTHORIZATION="Basic not-base64!")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_credentials_in_body_are_not_accepted(self):
        response = self.client.post(reverse("users:login"), {"username": "teacher", "password": PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_failed_attempts_are_throttled(self):
        limit = int(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"].split("/")[0])
        for _ in range(limit):
            self.assertEqual(self.login("teacher", "wrong").status_code, status.HTTP_401_UNAUTHORIZED)
        # Even the correct password is rejected once the limit is hit.
        self.assertEqual(self.login("teacher").status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_spoofed_forwarded_for_does_not_bypass_throttling(self):
        limit = int(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"].split("/")[0])
        for attempt in range(limit + 1):
            response = self.client.post(
                reverse("users:login"),
                HTTP_AUTHORIZATION=basic_header("teacher", "wrong"),
                HTTP_X_FORWARDED_FOR=f"10.0.0.{attempt}",
            )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class TokenLifecycleTests(AuthAPITestCase):
    def test_invalid_or_missing_token(self):
        for header in (None, "Bearer not-a-jwt", basic_header("student", PASSWORD)):
            with self.subTest(header):
                self.client.credentials(**({"HTTP_AUTHORIZATION": header} if header else {}))
                self.assertEqual(self.client.get(reverse("users:me")).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_token(self):
        token = AccessToken.for_user(self.student)
        token.set_exp(lifetime=-timedelta(seconds=1))
        self.authorize(str(token))

        self.assertEqual(self.client.get(reverse("users:me")).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_signed_with_another_key(self):
        forged = jwt.encode(
            {"token_type": "access", "user_id": str(self.teacher.pk), "exp": 4102444800, "jti": "x"},
            "attacker-controlled-signing-key-32b+",
            algorithm="HS256",
        )
        self.authorize(forged)

        self.assertEqual(self.client.get(reverse("users:me")).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_deactivated_user_token_is_rejected(self):
        self.authorize(self.login("student").data["access"])
        User.objects.filter(pk=self.student.pk).update(is_active=False)

        self.assertEqual(self.client.get(reverse("users:me")).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_rotates_and_blacklists_old_refresh_token(self):
        refresh = self.login("student").data["refresh"]

        response = self.client.post(reverse("users:token-refresh"), {"refresh": refresh})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertNotEqual(response.data["refresh"], refresh)

        reused = self.client.post(reverse("users:token-refresh"), {"refresh": refresh})
        self.assertEqual(reused.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_access_token_cannot_be_used_as_refresh(self):
        access = self.login("student").data["access"]
        response = self.client.post(reverse("users:token-refresh"), {"refresh": access})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_blacklists_refresh_token(self):
        refresh = self.login("student").data["refresh"]

        self.assertEqual(self.client.post(reverse("users:logout"), {"refresh": refresh}).status_code, 200)
        response = self.client.post(reverse("users:token-refresh"), {"refresh": refresh})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_verify(self):
        access = self.login("student").data["access"]
        self.assertEqual(self.client.post(reverse("users:token-verify"), {"token": access}).status_code, 200)
        self.assertEqual(self.client.post(reverse("users:token-verify"), {"token": "bad"}).status_code, 401)


class RegisterTests(AuthAPITestCase):
    url = reverse("users:register")

    def test_registers_student_even_if_teacher_role_requested(self):
        response = self.client.post(
            self.url, {"username": "new", "password": PASSWORD, "first_name": "Ivan", "role": "teacher"}
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["role"], User.Role.STUDENT)
        self.assertNotIn("password", response.data)
        user = User.objects.get(username="new")
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(self.login("new").status_code, status.HTTP_200_OK)

    def test_weak_password_rejected(self):
        response = self.client.post(self.url, {"username": "new", "password": "12345"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)
        self.assertFalse(User.objects.filter(username="new").exists())

    def test_password_similar_to_username_rejected(self):
        response = self.client.post(self.url, {"username": "verylongusername", "password": "verylongusername1"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_username_rejected(self):
        response = self.client.post(self.url, {"username": "student", "password": PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", response.data)

    def test_stale_bearer_token_does_not_block_registration(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer expired-or-garbage")
        response = self.client.post(self.url, {"username": "new", "password": PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class ProfileTests(AuthAPITestCase):
    def test_update_profile_but_not_role_or_username(self):
        self.authorize(self.login("student").data["access"])

        response = self.client.patch(
            reverse("users:me"), {"first_name": "Pavel", "role": "teacher", "username": "hacker"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, "Pavel")
        self.assertEqual(self.student.role, User.Role.STUDENT)
        self.assertEqual(self.student.username, "student")

    def test_put_not_allowed(self):
        self.authorize(self.login("student").data["access"])
        response = self.client.put(reverse("users:me"), {"first_name": "Pavel"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class StudentListTests(AuthAPITestCase):
    url = reverse("users:student-list")

    def test_teacher_sees_active_students_only(self):
        User.objects.create_user(username="expelled", password=PASSWORD, is_active=False)
        self.authorize(self.login("teacher").data["access"])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([u["username"] for u in response.data["results"]], ["student"])

    def test_search(self):
        User.objects.create_user(username="maria", password=PASSWORD, last_name="Sidorova")
        self.authorize(self.login("teacher").data["access"])

        response = self.client.get(self.url, {"search": "sidor"})

        self.assertEqual([u["username"] for u in response.data["results"]], ["maria"])

    def test_student_forbidden(self):
        self.authorize(self.login("student").data["access"])
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_unauthorized(self):
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_role_change_applies_without_relogin(self):
        access = self.login("student").data["access"]  # token claim says "student"
        User.objects.filter(pk=self.student.pk).update(role=User.Role.TEACHER)
        self.authorize(access)

        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)
