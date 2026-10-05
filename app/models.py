from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from users.models import User

GRADE_MIN, GRADE_MAX = 1, 5


class Grade(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="grades",
        limit_choices_to={"role": User.Role.STUDENT},
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="given_grades",
        limit_choices_to={"role": User.Role.TEACHER},
    )
    subject = models.CharField(max_length=100)
    value = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(GRADE_MIN), MaxValueValidator(GRADE_MAX)],
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(value__gte=GRADE_MIN, value__lte=GRADE_MAX),
                name="grade_value_in_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student} — {self.subject}: {self.value}"
