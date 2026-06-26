from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_redirect, name='login_redirect'),

    # Admin views
    path('dashboard/', views.dashboard, name='dashboard'),
    path('attendance/', views.attendance_view, name='attendance'),
    path('attendance/export/daily/', views.attendance_export_daily, name='attendance_export_daily'),
    path('attendance/export/weekly/', views.attendance_export_weekly, name='attendance_export_weekly'),
    path('staff/', views.staff_list, name='staff_list'),
    path('staff/create/', views.create_staff, name='create_staff'),

    # Notification API
    path('api/notifications/', views.notifications_api, name='notifications_api'),
    path('api/notifications/mark-read/', views.notifications_mark_read, name='notifications_mark_read'),
    path('api/notifications/<int:pk>/dismiss/', views.notification_dismiss, name='notification_dismiss'),

    # Staff views
    path('clock-in/', views.mark_attendance, name='mark_attendance'),
    path('my-records/', views.my_records, name='my_records'),
]
