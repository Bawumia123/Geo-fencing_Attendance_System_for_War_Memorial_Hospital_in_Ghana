from django.contrib import admin
from .models import HospitalBranch, AttendanceRecord, Profile, Notification


@admin.register(HospitalBranch)
class HospitalBranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'latitude', 'longitude', 'radius_meters')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('staff', 'timestamp', 'status', 'distance_from_center')
    list_filter = ('status', 'timestamp', 'staff')
    search_fields = ('staff__username', 'staff__first_name', 'staff__last_name')
    ordering = ('-timestamp',)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'department')
    list_filter = ('department',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'level', 'is_read', 'created_at', 'related_user')
    list_filter = ('level', 'is_read')
    ordering = ('-created_at',)