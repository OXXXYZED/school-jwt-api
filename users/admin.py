from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from users.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    fieldsets = (*DjangoUserAdmin.fieldsets, ("School", {"fields": ("role",)}))
    add_fieldsets = (*DjangoUserAdmin.add_fieldsets, ("School", {"fields": ("role",)}))
