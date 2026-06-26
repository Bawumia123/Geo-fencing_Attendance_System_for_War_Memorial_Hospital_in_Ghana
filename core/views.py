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


# ── Helpers ────────────────────────────────────────────────────────────────────

def is_admin(user):
    return user.is_staff


def _create_notification(title, message, level='info', related_user=None):
    Notification.objects.create(
        title=title, message=message, level=level, related_user=related_user
    )


def _parse_date(request, param='date', fallback=None):
    """Parse a YYYY-MM-DD query param; fall back to provided date or today."""
    raw = request.GET.get(param, '')
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return fallback or date.today()


def _stats_for_date(target_date):
    total_staff = User.objects.filter(is_active=True, is_staff=False).count()
    qs = AttendanceRecord.objects.filter(timestamp__date=target_date)
    present = qs.filter(status='Present').values('staff').distinct().count()
    out_of_bounds = qs.filter(status='Out of Bounds').count()
    absent = max(total_staff - present, 0)
    rate = round(present / total_staff * 100) if total_staff else 0
    return total_staff, qs, present, out_of_bounds, absent, rate


def _get_week_data(anchor_date=None):
    """Return (week_days, weekly_data) for the week containing anchor_date."""
    anchor = anchor_date or date.today()
    monday = anchor - timedelta(days=anchor.weekday())
    week_days = [monday + timedelta(days=i) for i in range(7)]

    staff_qs = User.objects.filter(is_active=True, is_staff=False).select_related('profile')
    records = AttendanceRecord.objects.filter(
        timestamp__date__range=(week_days[0], week_days[-1])
    ).select_related('staff')

    lookup = {}
    for rec in records:
        uid = rec.staff_id
        day_str = rec.timestamp.date().strftime('%Y-%m-%d')
        lookup.setdefault(uid, {})
        if day_str not in lookup[uid]:
            lookup[uid][day_str] = rec.status

    weekly_data = [{'staff': s, 'records': lookup.get(s.id, {})} for s in staff_qs]
    return week_days, weekly_data


def _write_csv_records(writer, records):
    writer.writerow(['Name', 'Username', 'Department', 'Status', 'Date', 'Time', 'Distance (m)'])
    for r in records:
        writer.writerow([
            r.staff.get_full_name() or r.staff.username,
            r.staff.username,
            r.staff.profile.get_department_display() if hasattr(r.staff, 'profile') else '',
            r.status,
            r.timestamp.strftime('%Y-%m-%d'),
            r.timestamp.strftime('%H:%M'),
            round(r.distance_from_center),
        ])


# ── Auth redirect ──────────────────────────────────────────────────────────────

def login_redirect(request):
    if request.user.is_authenticated:
        return redirect('dashboard' if request.user.is_staff else 'mark_attendance')
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
            return JsonResponse(
                {'message': 'Hospital location not configured. Contact admin.', 'status': 'Error'}, status=500
            )

        allowed, distance = is_within_geofence(user_lat, user_lon, hospital)
        status_text = "Present" if allowed else "Out of Bounds"
        AttendanceRecord.objects.create(
            staff=request.user, status=status_text, distance_from_center=distance
        )

        name = request.user.get_full_name() or request.user.username
        if allowed:
            msg = f'Attendance recorded. You are {round(distance, 1)}m from the hospital center.'
        else:
            msg = f'Outside hospital perimeter. You are {round(distance, 1)}m away (limit: {hospital.radius_meters}m).'
            _create_notification(
                title='Out of Bounds Clock-in',
                message=f'{name} attempted to clock in from {round(distance, 1)}m away '
                        f'(limit: {hospital.radius_meters}m).',
                level='error',
                related_user=request.user,
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


# ── Notification API ───────────────────────────────────────────────────────────

@login_required
@user_passes_test(is_admin)
def notifications_api(request):
    notifs = Notification.objects.filter(is_read=False).select_related('related_user')[:20]
    data = [
        {
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'level': n.level,
            'time': n.created_at.strftime('%b %d, %H:%M'),
        }
        for n in notifs
    ]
    return JsonResponse({
        'notifications': data,
        'unread_count': Notification.objects.filter(is_read=False).count(),
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def notifications_mark_read(request):
    Notification.objects.filter(is_read=False).update(is_read=True)
    return JsonResponse({'status': 'ok'})


@login_required
@user_passes_test(is_admin)
@require_POST
def notification_dismiss(request, pk):
    Notification.objects.filter(pk=pk).update(is_read=True)
    return JsonResponse({'status': 'ok'})


# ── Admin views ────────────────────────────────────────────────────────────────

@login_required
@user_passes_test(is_admin)
def dashboard(request):
    today = date.today()
    total_staff, today_qs, present_today, out_of_bounds, absent_today, rate = _stats_for_date(today)

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
    # --- Date selection (calendar picker) ---
    selected_date = _parse_date(request, 'date')

    # --- Week navigation ---
    week_anchor = _parse_date(request, 'week', selected_date)
    monday = week_anchor - timedelta(days=week_anchor.weekday())
    prev_week = (monday - timedelta(days=7)).isoformat()
    next_week = (monday + timedelta(days=7)).isoformat()

    total_staff, day_qs, present, out_of_bounds, absent, rate = _stats_for_date(selected_date)
    day_records = day_qs.select_related('staff', 'staff__profile').order_by('-timestamp')
    week_days, weekly_data = _get_week_data(week_anchor)
    unread_count = Notification.objects.filter(is_read=False).count()

    is_today = selected_date == date.today()

    return render(request, 'core/attendance.html', {
        'selected_date': selected_date,
        'is_today': is_today,
        'today': date.today(),
        'total_staff': total_staff,
        'present_today': present,
        'absent_today': absent,
        'attendance_rate': rate,
        'out_of_bounds_today': out_of_bounds,
        'day_records': day_records,
        'week_days': week_days,
        'weekly_data': weekly_data,
        'week_anchor': week_anchor.isoformat(),
        'prev_week': prev_week,
        'next_week': next_week,
        'departments': Profile.DEPARTMENTS,
        'unread_count': unread_count,
    })


@login_required
@user_passes_test(is_admin)
def attendance_export_daily(request):
    """Export a single day's attendance as CSV. Uses ?date= param, defaults to today."""
    target = _parse_date(request, 'date')
    records = AttendanceRecord.objects.filter(
        timestamp__date=target
    ).select_related('staff', 'staff__profile').order_by('-timestamp')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="attendance_daily_{target}.csv"'
    writer = csv.writer(response)
    _write_csv_records(writer, records)
    return response


@login_required
@user_passes_test(is_admin)
def attendance_export_weekly(request):
    """Export a full week's attendance as CSV. Uses ?week= param (any day in the week)."""
    anchor = _parse_date(request, 'week')
    monday = anchor - timedelta(days=anchor.weekday())
    sunday = monday + timedelta(days=6)

    records = AttendanceRecord.objects.filter(
        timestamp__date__range=(monday, sunday)
    ).select_related('staff', 'staff__profile').order_by('timestamp__date', 'staff__last_name')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="attendance_week_{monday}_to_{sunday}.csv"'
    )
    writer = csv.writer(response)
    _write_csv_records(writer, records)
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
        elif password1 != password2:
            messages.error(request, 'Passwords do not match.')
        elif len(password1) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, f'Username "{username}" is already taken.')
        else:
            dept_display = dict(Profile.DEPARTMENTS).get(department, department)
            user = User.objects.create_user(
                username=username, email=email, password=password1,
                first_name=first_name, last_name=last_name, is_staff=False,
            )
            Profile.objects.create(user=user, department=department)
            _create_notification(
                title='New Staff Account Created',
                message=f'{first_name} {last_name} was added to the {dept_display} department.',
                level='success',
                related_user=user,
            )
            messages.success(request, f'Account created for {first_name} {last_name}.')
            return redirect('staff_list')

        return render(request, 'core/create_staff.html', {
            'departments': Profile.DEPARTMENTS,
            'form_data': form_data,
            'unread_count': Notification.objects.filter(is_read=False).count(),
        })

    return render(request, 'core/create_staff.html', {
        'departments': Profile.DEPARTMENTS,
        'unread_count': Notification.objects.filter(is_read=False).count(),
    })
