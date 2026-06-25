import json
import csv
from datetime import date, timedelta
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.views.decorators.http import require_POST
from .models import HospitalBranch, AttendanceRecord, Profile, Notification
from .utils import is_within_geofence


def is_admin(user):
    return user.is_staff


def login_redirect(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('dashboard')
        return redirect('mark_attendance')
    return redirect('login')


# ── Notification helpers ───────────────────────────────────────────────────────

def _create_notification(title, message, level='info', related_user=None):
    Notification.objects.create(
        title=title, message=message, level=level, related_user=related_user
    )


# ── Staff views ────────────────────────────────────────────────────────────────

@login_required
def mark_attendance(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_lat = data.get('latitude')
            user_lon = data.get('longitude')
        except (json.JSONDecodeError, KeyError):
            return JsonResponse({'message': 'Invalid request data.', 'status': 'Error'}, status=400)

        hospital = HospitalBranch.objects.first()
        if not hospital:
            return JsonResponse({'message': 'Hospital location not configured. Contact admin.', 'status': 'Error'}, status=500)

        allowed, distance = is_within_geofence(user_lat, user_lon, hospital)
        status_text = "Present" if allowed else "Out of Bounds"

        AttendanceRecord.objects.create(
            staff=request.user,
            status=status_text,
            distance_from_center=distance
        )

        name = request.user.get_full_name() or request.user.username

        if allowed:
            msg = f'Attendance recorded. You are {round(distance, 1)}m from the hospital center.'
        else:
            msg = f'Outside hospital perimeter. You are {round(distance, 1)}m away (limit: {hospital.radius_meters}m).'
            _create_notification(
                title='Out of Bounds Clock-in',
                message=f'{name} attempted to clock in from {round(distance, 1)}m away (limit: {hospital.radius_meters}m).',
                level='error',
                related_user=request.user
            )

        return JsonResponse({'message': msg, 'status': status_text})

    today = date.today()
    today_records = AttendanceRecord.objects.filter(
        staff=request.user, timestamp__date=today
    ).order_by('-timestamp')

    return render(request, 'core/clock_in.html', {
        'today': today,
        'today_records': today_records,
        'hospital': HospitalBranch.objects.first(),
    })


@login_required
def my_records(request):
    records = AttendanceRecord.objects.filter(staff=request.user).order_by('-timestamp')
    today = date.today()
    month_start = today.replace(day=1)

    return render(request, 'core/my_records.html', {
        'records': records,
        'total_records': records.filter(status='Present').count(),
        'this_month': records.filter(status='Present', timestamp__date__gte=month_start).count(),
        'out_of_bounds': records.filter(status='Out of Bounds').count(),
    })


# ── Notification views ─────────────────────────────────────────────────────────

@login_required
@user_passes_test(is_admin)
def notifications_api(request):
    """Return unread notifications as JSON for the bell dropdown."""
    notifs = Notification.objects.filter(is_read=False).select_related('related_user')[:20]
    data = []
    for n in notifs:
        data.append({
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'level': n.level,
            'time': n.created_at.strftime('%b %d, %H:%M'),
        })
    unread_count = Notification.objects.filter(is_read=False).count()
    return JsonResponse({'notifications': data, 'unread_count': unread_count})


@login_required
@user_passes_test(is_admin)
@require_POST
def notifications_mark_read(request):
    """Mark all notifications as read."""
    Notification.objects.filter(is_read=False).update(is_read=True)
    return JsonResponse({'status': 'ok'})


@login_required
@user_passes_test(is_admin)
@require_POST
def notification_dismiss(request, pk):
    """Mark a single notification as read."""
    Notification.objects.filter(pk=pk).update(is_read=True)
    return JsonResponse({'status': 'ok'})


# ── Admin helpers ──────────────────────────────────────────────────────────────

def _get_week_data():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_days = [monday + timedelta(days=i) for i in range(7)]

    staff_qs = User.objects.filter(is_active=True, is_staff=False).select_related('profile')
    records_this_week = AttendanceRecord.objects.filter(
        timestamp__date__range=(week_days[0], week_days[-1])
    ).select_related('staff')

    lookup = {}
    for rec in records_this_week:
        uid = rec.staff_id
        day_str = rec.timestamp.date().strftime('%Y-%m-%d')
        if uid not in lookup:
            lookup[uid] = {}
        if day_str not in lookup[uid]:
            lookup[uid][day_str] = rec.status

    weekly_data = [{'staff': s, 'records': lookup.get(s.id, {})} for s in staff_qs]
    return week_days, weekly_data


def _base_stats(today):
    total_staff = User.objects.filter(is_active=True, is_staff=False).count()
    today_qs = AttendanceRecord.objects.filter(timestamp__date=today)
    present_today = today_qs.filter(status='Present').values('staff').distinct().count()
    out_of_bounds = today_qs.filter(status='Out of Bounds').count()
    absent_today = max(total_staff - present_today, 0)
    rate = round(present_today / total_staff * 100) if total_staff else 0
    return total_staff, today_qs, present_today, out_of_bounds, absent_today, rate


# ── Admin views ────────────────────────────────────────────────────────────────

@login_required
@user_passes_test(is_admin)
def dashboard(request):
    today = date.today()
    total_staff, today_qs, present_today, out_of_bounds, absent_today, rate = _base_stats(today)

    dept_stats = []
    for code, name in Profile.DEPARTMENTS:
        dept_total = Profile.objects.filter(department=code).count()
        dept_present = today_qs.filter(
            status='Present', staff__profile__department=code
        ).values('staff').distinct().count()
        if dept_total > 0:
            dept_stats.append({
                'name': name, 'total': dept_total, 'present': dept_present,
                'pct': round(dept_present / dept_total * 100),
            })

    week_days, weekly_data = _get_week_data()
    unread_count = Notification.objects.filter(is_read=False).count()

    return render(request, 'core/dashboard.html', {
        'today': today,
        'total_staff': total_staff,
        'present_today': present_today,
        'absent_today': absent_today,
        'attendance_rate': rate,
        'out_of_bounds_today': out_of_bounds,
        'dept_count': len(Profile.DEPARTMENTS),
        'dept_stats': dept_stats,
        'week_days': week_days,
        'weekly_data': weekly_data,
        'unread_count': unread_count,
    })


@login_required
@user_passes_test(is_admin)
def attendance_view(request):
    today = date.today()
    total_staff, today_qs, present_today, out_of_bounds, absent_today, rate = _base_stats(today)

    today_records = today_qs.select_related('staff', 'staff__profile').order_by('-timestamp')
    week_days, weekly_data = _get_week_data()
    unread_count = Notification.objects.filter(is_read=False).count()

    return render(request, 'core/attendance.html', {
        'today': today,
        'total_staff': total_staff,
        'present_today': present_today,
        'absent_today': absent_today,
        'attendance_rate': rate,
        'out_of_bounds_today': out_of_bounds,
        'today_records': today_records,
        'week_days': week_days,
        'weekly_data': weekly_data,
        'departments': Profile.DEPARTMENTS,
        'unread_count': unread_count,
    })


@login_required
@user_passes_test(is_admin)
def attendance_export(request):
    today = date.today()
    records = AttendanceRecord.objects.filter(
        timestamp__date=today
    ).select_related('staff', 'staff__profile').order_by('-timestamp')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="attendance_{today}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Name', 'Username', 'Department', 'Status', 'Time', 'Distance (m)'])
    for r in records:
        writer.writerow([
            r.staff.get_full_name() or r.staff.username,
            r.staff.username,
            r.staff.profile.get_department_display() if hasattr(r.staff, 'profile') else '',
            r.status,
            r.timestamp.strftime('%H:%M'),
            round(r.distance_from_center),
        ])
    return response


@login_required
@user_passes_test(is_admin)
def staff_list(request):
    today = date.today()
    today_present_ids = set(
        AttendanceRecord.objects.filter(timestamp__date=today, status='Present')
        .values_list('staff_id', flat=True)
    )

    profiles = Profile.objects.select_related('user').order_by('user__last_name', 'user__first_name')
    staff_data = []
    for profile in profiles:
        last_record = AttendanceRecord.objects.filter(staff=profile.user).order_by('-timestamp').first()
        profile.last_seen = last_record.timestamp if last_record else None
        profile.clocked_in_today = profile.user_id in today_present_ids
        profile.total_records = AttendanceRecord.objects.filter(staff=profile.user).count()
        staff_data.append(profile)

    return render(request, 'core/staff_list.html', {
        'staff_data': staff_data,
        'total_staff': len(staff_data),
        'departments': Profile.DEPARTMENTS,
        'unread_count': Notification.objects.filter(is_read=False).count(),
    })


@login_required
@user_passes_test(is_admin)
def create_staff(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        department = request.POST.get('department', '').strip()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')

        form_data = {
            'first_name': first_name, 'last_name': last_name,
            'username': username, 'email': email, 'department': department,
        }

        if not all([first_name, last_name, username, department, password1, password2]):
            messages.error(request, 'All fields except email are required.')
            return render(request, 'core/create_staff.html', {'departments': Profile.DEPARTMENTS, 'form_data': form_data})

        if password1 != password2:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'core/create_staff.html', {'departments': Profile.DEPARTMENTS, 'form_data': form_data})

        if len(password1) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
            return render(request, 'core/create_staff.html', {'departments': Profile.DEPARTMENTS, 'form_data': form_data})

        if User.objects.filter(username=username).exists():
            messages.error(request, f'Username "{username}" is already taken.')
            return render(request, 'core/create_staff.html', {'departments': Profile.DEPARTMENTS, 'form_data': form_data})

        dept_display = dict(Profile.DEPARTMENTS).get(department, department)
        user = User.objects.create_user(
            username=username, email=email,
            password=password1, first_name=first_name, last_name=last_name,
            is_staff=False
        )
        Profile.objects.create(user=user, department=department)

        _create_notification(
            title='New Staff Account Created',
            message=f'{first_name} {last_name} was added to the {dept_display} department.',
            level='success',
            related_user=user
        )

        messages.success(request, f'Account created for {first_name} {last_name}.')
        return redirect('staff_list')

    return render(request, 'core/create_staff.html', {
        'departments': Profile.DEPARTMENTS,
        'unread_count': Notification.objects.filter(is_read=False).count(),
    })


def is_admin(user):
    return user.is_staff


def login_redirect(request):
    """After login, send admins to dashboard, staff to clock-in."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('dashboard')
        return redirect('mark_attendance')
    return redirect('login')


# ── Staff views ────────────────────────────────────────────────────────────────

@login_required
def mark_attendance(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_lat = data.get('latitude')
            user_lon = data.get('longitude')
        except (json.JSONDecodeError, KeyError):
            return JsonResponse({'message': 'Invalid request data.', 'status': 'Error'}, status=400)

        hospital = HospitalBranch.objects.first()
        if not hospital:
            return JsonResponse({'message': 'Hospital location not configured. Contact admin.', 'status': 'Error'}, status=500)

        allowed, distance = is_within_geofence(user_lat, user_lon, hospital)
        status_text = "Present" if allowed else "Out of Bounds"

        AttendanceRecord.objects.create(
            staff=request.user,
            status=status_text,
            distance_from_center=distance
        )

        if allowed:
            msg = f'Attendance recorded. You are {round(distance, 1)}m from the hospital center.'
        else:
            msg = f'Outside hospital perimeter. You are {round(distance, 1)}m away (limit: {hospital.radius_meters}m).'

        return JsonResponse({'message': msg, 'status': status_text})

    today = date.today()
    today_records = AttendanceRecord.objects.filter(
        staff=request.user, timestamp__date=today
    ).order_by('-timestamp')

    return render(request, 'core/clock_in.html', {
        'today': today,
        'today_records': today_records,
        'hospital': HospitalBranch.objects.first(),
    })


@login_required
def my_records(request):
    records = AttendanceRecord.objects.filter(staff=request.user).order_by('-timestamp')
    today = date.today()
    month_start = today.replace(day=1)

    return render(request, 'core/my_records.html', {
        'records': records,
        'total_records': records.filter(status='Present').count(),
        'this_month': records.filter(status='Present', timestamp__date__gte=month_start).count(),
        'out_of_bounds': records.filter(status='Out of Bounds').count(),
    })


# ── Admin helpers ──────────────────────────────────────────────────────────────

def _get_week_data():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_days = [monday + timedelta(days=i) for i in range(7)]

    staff_qs = User.objects.filter(is_active=True, is_staff=False).select_related('profile')
    records_this_week = AttendanceRecord.objects.filter(
        timestamp__date__range=(week_days[0], week_days[-1])
    ).select_related('staff')

    lookup = {}
    for rec in records_this_week:
        uid = rec.staff_id
        day_str = rec.timestamp.date().strftime('%Y-%m-%d')
        if uid not in lookup:
            lookup[uid] = {}
        if day_str not in lookup[uid]:
            lookup[uid][day_str] = rec.status

    weekly_data = [{'staff': s, 'records': lookup.get(s.id, {})} for s in staff_qs]
    return week_days, weekly_data


def _base_stats(today):
    total_staff = User.objects.filter(is_active=True, is_staff=False).count()
    today_qs = AttendanceRecord.objects.filter(timestamp__date=today)
    present_today = today_qs.filter(status='Present').values('staff').distinct().count()
    out_of_bounds = today_qs.filter(status='Out of Bounds').count()
    absent_today = max(total_staff - present_today, 0)
    rate = round(present_today / total_staff * 100) if total_staff else 0
    return total_staff, today_qs, present_today, out_of_bounds, absent_today, rate


# ── Admin views ────────────────────────────────────────────────────────────────

@login_required
@user_passes_test(is_admin)
def dashboard(request):
    today = date.today()
    total_staff, today_qs, present_today, out_of_bounds, absent_today, rate = _base_stats(today)

    dept_stats = []
    for code, name in Profile.DEPARTMENTS:
        dept_total = Profile.objects.filter(department=code).count()
        dept_present = today_qs.filter(
            status='Present', staff__profile__department=code
        ).values('staff').distinct().count()
        if dept_total > 0:
            dept_stats.append({
                'name': name, 'total': dept_total, 'present': dept_present,
                'pct': round(dept_present / dept_total * 100),
            })

    week_days, weekly_data = _get_week_data()

    return render(request, 'core/dashboard.html', {
        'today': today,
        'total_staff': total_staff,
        'present_today': present_today,
        'absent_today': absent_today,
        'attendance_rate': rate,
        'out_of_bounds_today': out_of_bounds,
        'dept_count': len(Profile.DEPARTMENTS),
        'dept_stats': dept_stats,
        'week_days': week_days,
        'weekly_data': weekly_data,
        'alert_count': 1 if out_of_bounds > 0 else 0,
    })


@login_required
@user_passes_test(is_admin)
def attendance_view(request):
    today = date.today()
    total_staff, today_qs, present_today, out_of_bounds, absent_today, rate = _base_stats(today)

    today_records = today_qs.select_related('staff', 'staff__profile').order_by('-timestamp')
    week_days, weekly_data = _get_week_data()

    return render(request, 'core/attendance.html', {
        'today': today,
        'total_staff': total_staff,
        'present_today': present_today,
        'absent_today': absent_today,
        'attendance_rate': rate,
        'out_of_bounds_today': out_of_bounds,
        'today_records': today_records,
        'week_days': week_days,
        'weekly_data': weekly_data,
        'departments': Profile.DEPARTMENTS,
    })


@login_required
@user_passes_test(is_admin)
def attendance_export(request):
    """Export today's attendance log as CSV."""
    today = date.today()
    records = AttendanceRecord.objects.filter(
        timestamp__date=today
    ).select_related('staff', 'staff__profile').order_by('-timestamp')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="attendance_{today}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Name', 'Username', 'Department', 'Status', 'Time', 'Distance (m)'])
    for r in records:
        writer.writerow([
            r.staff.get_full_name() or r.staff.username,
            r.staff.username,
            r.staff.profile.get_department_display() if hasattr(r.staff, 'profile') else '',
            r.status,
            r.timestamp.strftime('%H:%M'),
            round(r.distance_from_center),
        ])
    return response


@login_required
@user_passes_test(is_admin)
def staff_list(request):
    today = date.today()
    today_present_ids = set(
        AttendanceRecord.objects.filter(timestamp__date=today, status='Present')
        .values_list('staff_id', flat=True)
    )

    profiles = Profile.objects.select_related('user').order_by('user__last_name', 'user__first_name')
    staff_data = []
    for profile in profiles:
        last_record = AttendanceRecord.objects.filter(staff=profile.user).order_by('-timestamp').first()
        profile.last_seen = last_record.timestamp if last_record else None
        profile.clocked_in_today = profile.user_id in today_present_ids
        profile.total_records = AttendanceRecord.objects.filter(staff=profile.user).count()
        staff_data.append(profile)

    return render(request, 'core/staff_list.html', {
        'staff_data': staff_data,
        'total_staff': len(staff_data),
        'departments': Profile.DEPARTMENTS,
    })


@login_required
@user_passes_test(is_admin)
def create_staff(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        department = request.POST.get('department', '').strip()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')

        form_data = {
            'first_name': first_name, 'last_name': last_name,
            'username': username, 'email': email, 'department': department,
        }

        if not all([first_name, last_name, username, department, password1, password2]):
            messages.error(request, 'All fields except email are required.')
            return render(request, 'core/create_staff.html', {'departments': Profile.DEPARTMENTS, 'form_data': form_data})

        if password1 != password2:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'core/create_staff.html', {'departments': Profile.DEPARTMENTS, 'form_data': form_data})

        if len(password1) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
            return render(request, 'core/create_staff.html', {'departments': Profile.DEPARTMENTS, 'form_data': form_data})

        if User.objects.filter(username=username).exists():
            messages.error(request, f'Username "{username}" is already taken.')
            return render(request, 'core/create_staff.html', {'departments': Profile.DEPARTMENTS, 'form_data': form_data})

        user = User.objects.create_user(
            username=username, email=email,
            password=password1, first_name=first_name, last_name=last_name,
            is_staff=False
        )
        Profile.objects.create(user=user, department=department)
        messages.success(request, f'Account created for {first_name} {last_name}.')
        return redirect('staff_list')

    return render(request, 'core/create_staff.html', {'departments': Profile.DEPARTMENTS})
