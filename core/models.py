from django.db import models
from django.contrib.auth.models import User


class HospitalBranch(models.Model):
    name = models.CharField(max_length=100, default="War Memorial Hospital")
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius_meters = models.PositiveIntegerField(default=200)

    def __str__(self):
        return self.name


class AttendanceRecord(models.Model):
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20)  # "Present" or "Out of Bounds"
    distance_from_center = models.FloatField(help_text="Distance in meters")

    def __str__(self):
        return f"{self.staff.username} - {self.timestamp.strftime('%Y-%m-%d %H:%M')}"


class Profile(models.Model):
    DEPARTMENTS = [
        ('ADMIN', 'Administration'),
        ('NURSING', 'Nursing'),
        ('MEDICAL', 'Medical/Doctors'),
        ('LAB', 'Laboratory'),
        ('PHARMACY', 'Pharmacy'),
        ('OTHER', 'Support Staff'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    department = models.CharField(max_length=20, choices=DEPARTMENTS)

    def __str__(self):
        return f"{self.user.username} - {self.get_department_display()}"


class Notification(models.Model):
    LEVELS = [
        ('error', 'Error'),
        ('warning', 'Warning'),
        ('success', 'Success'),
        ('info', 'Info'),
    ]
    title = models.CharField(max_length=100)
    message = models.TextField()
    level = models.CharField(max_length=10, choices=LEVELS, default='info')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # Optional link to the related staff member
    related_user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='notifications'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.level.upper()}] {self.title}"
