from django.contrib import admin

from app.models import Grade


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("student", "subject", "value", "teacher", "created_at")
    list_filter = ("subject", "value")
    search_fields = ("student__username", "student__last_name", "teacher__username", "subject")
    list_select_related = ("student", "teacher")
    raw_id_fields = ("student", "teacher")
