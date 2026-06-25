# CHAPTER FOUR: SYSTEM IMPLEMENTATION AND TESTING

## 4.1 Introduction

This chapter presents the implementation of the War Memorial Hospital GPS-Based Staff Attendance System. It covers the system architecture, development environment, database design, module implementation, user interface design, notification system, and system testing. The system was developed to replace manual attendance recording by leveraging GPS geofencing technology to verify that staff members are physically within the hospital premises at the time of clocking in. The system eliminates proxy attendance, reduces administrative overhead, and gives management real-time visibility into staff attendance through a web-based dashboard.

---

## 4.2 Development Environment and Technologies

### 4.2.1 Tools and Technologies Used

| Component | Technology | Version / Notes |
|---|---|---|
| Backend Framework | Django | 6.0.4 |
| Programming Language | Python | 3.x |
| Frontend Styling | Tailwind CSS | CDN (no build step) |
| Database | SQLite | Development database |
| Geolocation Library | GeoPy | Geodesic distance calculation |
| GPS Source | Browser Geolocation API | W3C standard, device GPS |
| Template Engine | Django Template Language (DTL) | Server-rendered HTML |
| Custom Template Tag | dict_extras (get_item filter) | Dictionary key lookup in templates |

**Django** was chosen as the web framework due to its built-in ORM, session-based authentication, CSRF protection, and the rapid development it enables through its MVT (Model-View-Template) architecture. Django cleanly separates data logic (models), business logic (views), and presentation (templates), making the codebase maintainable and easy to extend.

**Tailwind CSS** was used via CDN to produce a fully responsive, dark-themed interface without requiring a separate build pipeline or JavaScript framework. All pages are rendered server-side by Django, with Tailwind providing the visual styling through utility classes.

**GeoPy** was used to compute geodesic distances between GPS coordinates. GeoPy's `geodesic` function uses the WGS-84 ellipsoid model — the same standard used by GPS satellites — which gives more accurate short-distance measurements than the simpler Haversine formula.

**SQLite** was used as the development database. Django's ORM fully abstracts the underlying database engine, so migration to PostgreSQL or MySQL for production deployment requires only a configuration change in `settings.py`.

### 4.2.2 Project Directory Structure

```
hospital_attendance/
├── myproject/
│   ├── settings.py          # Global Django configuration
│   ├── urls.py              # Root URL dispatcher
│   └── wsgi.py              # WSGI application entry point
├── core/
│   ├── models.py            # Data models
│   ├── views.py             # Business logic and request handlers
│   ├── urls.py              # Application URL routing
│   ├── utils.py             # Geofence calculation utility
│   ├── admin.py             # Django admin panel registrations
│   ├── templatetags/
│   │   ├── __init__.py
│   │   └── dict_extras.py   # Custom template filter: get_item
│   └── templates/
│       ├── base_admin.html      # Admin layout with sidebar + notification panel
│       ├── base_staff.html      # Staff layout with minimal sidebar
│       ├── registration/
│       │   └── login.html       # Login page
│       └── core/
│           ├── dashboard.html       # Admin dashboard
│           ├── attendance.html      # Attendance overview and log
│           ├── clock_in.html        # Staff GPS clock-in page
│           ├── staff_list.html      # Staff directory
│           ├── create_staff.html    # Create staff account form
│           ├── my_records.html      # Staff personal attendance history
│           └── partials/
│               └── weekly_grid.html # Reusable weekly attendance grid
├── venv/                    # Python virtual environment
└── db.sqlite3               # SQLite database file
```

---

## 4.3 Database Design

The system defines four data models in `core/models.py`, each mapped to a database table through Django's ORM. The models capture hospital configuration, attendance events, staff profiles, and system notifications.

### 4.3.1 HospitalBranch Model

This model stores the GPS reference point for the hospital and the geofence boundary radius. It is configured once by the administrator.

```python
class HospitalBranch(models.Model):
    name = models.CharField(max_length=100, default="War Memorial Hospital")
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius_meters = models.PositiveIntegerField(default=200)
```

| Field | Type | Description |
|---|---|---|
| `name` | CharField | Hospital name, default: "War Memorial Hospital" |
| `latitude` | FloatField | GPS latitude of hospital center |
| `longitude` | FloatField | GPS longitude of hospital center |
| `radius_meters` | PositiveIntegerField | Geofence radius in metres (default: 200) |

The `radius_meters` value defines the circular boundary within which a clock-in is accepted as valid. Any GPS coordinate falling outside this radius results in an "Out of Bounds" record.

### 4.3.2 AttendanceRecord Model

This model captures every clock-in attempt, whether successful or out of bounds, creating a complete and tamper-resistant audit log.

```python
class AttendanceRecord(models.Model):
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20)
    distance_from_center = models.FloatField(help_text="Distance in meters")
```

| Field | Type | Description |
|---|---|---|
| `staff` | ForeignKey (User) | The staff member associated with the record |
| `timestamp` | DateTimeField | Server-set date and time, auto-populated on creation |
| `status` | CharField | Either `"Present"` or `"Out of Bounds"` |
| `distance_from_center` | FloatField | Computed distance from hospital GPS center in metres |

The `auto_now_add=True` flag ensures the timestamp is assigned server-side at the moment the record is saved. This prevents any manipulation of the recorded time from the client. The `distance_from_center` field gives administrators a precise audit trail showing exactly how far outside the perimeter each failed attempt occurred.

### 4.3.3 Profile Model

Django's built-in `User` model handles authentication (username, password, email, login sessions). The `Profile` model extends it with hospital-specific information using a one-to-one relationship.

```python
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
```

| Field | Type | Description |
|---|---|---|
| `user` | OneToOneField | One-to-one link to Django's built-in User |
| `department` | CharField | Staff department from the predefined choices list |

The `on_delete=models.CASCADE` constraint ensures that when a User is deleted, their Profile is deleted automatically, maintaining referential integrity. The `DEPARTMENTS` list defines six department categories covering the hospital's operational structure.

### 4.3.4 Notification Model

The Notification model stores system-generated alerts that are displayed to administrators in real time through the notification bell interface.

```python
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
    related_user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='notifications'
    )

    class Meta:
        ordering = ['-created_at']
```

| Field | Type | Description |
|---|---|---|
| `title` | CharField | Short notification heading |
| `message` | TextField | Full notification body text |
| `level` | CharField | Severity: error, warning, success, or info |
| `is_read` | BooleanField | Whether the admin has acknowledged the notification |
| `created_at` | DateTimeField | Auto-set creation timestamp |
| `related_user` | ForeignKey (User) | Optional link to the staff member involved |

The `ordering = ['-created_at']` Meta option ensures that the most recent notifications are always returned first. The `related_user` is nullable (`null=True, blank=True`) because some notifications are not associated with a specific individual.

### 4.3.5 Entity Relationship Diagram (Textual)

```
User (Django built-in)
 ├── Profile              [OneToOne]   →  department
 ├── AttendanceRecord     [ForeignKey] →  status, timestamp, distance_from_center
 └── Notification         [ForeignKey] →  title, message, level, is_read (optional link)

HospitalBranch (standalone)  →  latitude, longitude, radius_meters
```

---

## 4.4 Geofence Algorithm

The geofence algorithm is the core technical mechanism of the system. It is implemented as a utility function in `core/utils.py`.

```python
from geopy.distance import geodesic

def is_within_geofence(user_lat, user_lon, hospital):
    user_coords = (user_lat, user_lon)
    hospital_coords = (hospital.latitude, hospital.longitude)
    distance = geodesic(hospital_coords, user_coords).meters
    if distance <= hospital.radius_meters:
        return True, distance
    return False, distance
```

The function takes the staff member's GPS latitude and longitude and the `HospitalBranch` database record as its parameters. It uses GeoPy's `geodesic` function to compute the shortest distance between the two points on the Earth's surface using the WGS-84 ellipsoid model. The result is returned in metres. If the computed distance is less than or equal to the configured radius, the function returns `True` (within bounds). Otherwise it returns `False` (out of bounds). In both cases the actual distance value is returned alongside the boolean, so it can be logged in the attendance record and communicated back to the user.

### 4.4.1 Boundary Logic

Given:
- Hospital center: (φ₁, λ₁)
- Staff device GPS: (φ₂, λ₂)
- Configured geofence radius: r metres

The geodesic distance d is computed using the WGS-84 ellipsoid model.

- If **d ≤ r** → Status = **"Present"**, attendance recorded, staff receives success feedback
- If **d > r** → Status = **"Out of Bounds"**, attendance still recorded for audit, staff receives distance feedback, an admin notification is generated

The geofence check runs entirely on the server. The browser sends only raw coordinates and has no ability to influence the outcome.

---

## 4.5 System Modules and Implementation

### 4.5.1 URL Routing

The routing is split across two files. The root dispatcher delegates all application routes to the `core` app.

```python
# myproject/urls.py
urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('core.urls')),
]
```

```python
# core/urls.py
urlpatterns = [
    path('', views.login_redirect, name='login_redirect'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('attendance/', views.attendance_view, name='attendance'),
    path('attendance/export/', views.attendance_export, name='attendance_export'),
    path('staff/', views.staff_list, name='staff_list'),
    path('staff/create/', views.create_staff, name='create_staff'),
    path('api/notifications/', views.notifications_api, name='notifications_api'),
    path('api/notifications/mark-read/', views.notifications_mark_read, name='notifications_mark_read'),
    path('api/notifications/<int:pk>/dismiss/', views.notification_dismiss, name='notification_dismiss'),
    path('clock-in/', views.mark_attendance, name='mark_attendance'),
    path('my-records/', views.my_records, name='my_records'),
]
```

### 4.5.2 Authentication and Role-Based Access Control

The system implements two user roles:

- **Administrator** (`is_staff = True`): Full access to the dashboard, attendance overview, staff directory, staff creation, and notification management.
- **Staff** (`is_staff = False`): Access only to the GPS clock-in page and their personal attendance history.

Every view is protected. Admin views use both `@login_required` and `@user_passes_test(is_admin)`:

```python
def is_admin(user):
    return user.is_staff

@login_required
@user_passes_test(is_admin)
def dashboard(request):
    ...
```

After login, a smart redirect function routes each user to the appropriate starting page:

```python
def login_redirect(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('dashboard')
        return redirect('mark_attendance')
    return redirect('login')
```

Staff accounts cannot be self-registered. Only an authenticated administrator can create them through the `/staff/create/` page. This prevents unauthorised users from entering the system.

### 4.5.3 Attendance Recording Module

The `mark_attendance` view handles the clock-in flow for staff. It accepts both GET requests (render the clock-in page) and POST requests (process GPS data).

**GET request flow:**
1. Staff visits `/clock-in/`
2. The view queries today's attendance records for the logged-in user
3. The clock-in page renders with the GPS button and the user's attendance log for the current day

**POST request flow:**
1. Staff presses "Clock In Now"
2. The browser's Geolocation API is invoked: `navigator.geolocation.getCurrentPosition()`
3. On a successful GPS fix, coordinates are sent to the server via a `fetch()` POST request with a JSON payload
4. The server calls `is_within_geofence()` to evaluate the coordinates
5. An `AttendanceRecord` is saved with status `"Present"` or `"Out of Bounds"`
6. If the status is `"Out of Bounds"`, a `Notification` record is created automatically
7. A JSON response is returned to the browser with the result message and status
8. The page reloads after 2.5 seconds to display the updated log

```python
allowed, distance = is_within_geofence(user_lat, user_lon, hospital)
status_text = "Present" if allowed else "Out of Bounds"

AttendanceRecord.objects.create(
    staff=request.user,
    status=status_text,
    distance_from_center=distance
)

if not allowed:
    _create_notification(
        title='Out of Bounds Clock-in',
        message=f'{name} attempted to clock in from {round(distance, 1)}m away '
                f'(limit: {hospital.radius_meters}m).',
        level='error',
        related_user=request.user
    )
```

### 4.5.4 Admin Dashboard Module

The dashboard view aggregates the following metrics from the database for the current day and passes them to the template:

- **Total staff**: Count of all active non-admin user accounts
- **Present today**: Distinct count of staff with at least one `"Present"` record for today
- **Absent today**: Total staff minus present count
- **Attendance rate**: Percentage calculated as (present / total) × 100
- **Out of bounds**: Count of failed clock-in attempts for the day
- **Department breakdown**: Per-department attendance counts with percentage progress bars
- **Weekly attendance grid**: A Monday-to-Sunday matrix showing each staff member's daily attendance status for the current week

Two helper functions provide reusable data that is shared between the dashboard and attendance views:

```python
def _base_stats(today):
    total_staff = User.objects.filter(is_active=True, is_staff=False).count()
    today_qs = AttendanceRecord.objects.filter(timestamp__date=today)
    present_today = today_qs.filter(status='Present').values('staff').distinct().count()
    out_of_bounds = today_qs.filter(status='Out of Bounds').count()
    absent_today = max(total_staff - present_today, 0)
    rate = round(present_today / total_staff * 100) if total_staff else 0
    return total_staff, today_qs, present_today, out_of_bounds, absent_today, rate
```

The `.values('staff').distinct()` call ensures that a staff member who clocks in multiple times on the same day is counted only once in the present count.

### 4.5.5 Staff Management Module

The `create_staff` view allows administrators to register new staff accounts. The form captures first name, last name, username, email, department, and password with confirmation. The following server-side validations are enforced before the account is created:

1. All required fields must be present
2. Password fields must match
3. Password must be at least 8 characters
4. Username must not already exist in the database

On successful creation, Django's `create_user()` method is used, which automatically hashes the password using PBKDF2-SHA256 before storage. A `Notification` record is also created to inform the admin team:

```python
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
```

### 4.5.6 Notification System

The notification system provides real-time alerts to administrators. It consists of a database model, three API endpoints, and a JavaScript-powered bell interface in the admin layout.

**Automatic triggers:**
- An `"error"` level notification is created every time a staff member attempts to clock in from outside the geofence
- A `"success"` level notification is created every time a new staff account is registered

**API Endpoints:**

| Endpoint | Method | Description |
|---|---|---|
| `/api/notifications/` | GET | Returns up to 20 unread notifications as JSON with unread count |
| `/api/notifications/mark-read/` | POST | Marks all unread notifications as read |
| `/api/notifications/<pk>/dismiss/` | POST | Marks a single notification as read by ID |

All three endpoints require the user to be authenticated and have administrator privileges.

**Frontend behaviour:**
The bell icon in the admin header shows a live badge with the unread count. Clicking it opens a slide-in panel on the right side of the screen listing all unread notifications with colour-coded severity indicators. Each notification has an individual dismiss button. A "Mark all read" button clears all at once. The panel polls the API automatically every 30 seconds to pick up new notifications without requiring a page refresh. The alerts section on the main dashboard also uses the same API to display the four most recent unread notifications.

```javascript
// Poll for new notifications every 30 seconds
loadNotifications();
setInterval(loadNotifications, 30000);
```

### 4.5.7 Data Export Module

The `attendance_export` view generates a CSV file of the current day's attendance records and delivers it as a file download directly from the browser.

```python
response = HttpResponse(content_type='text/csv')
response['Content-Disposition'] = f'attachment; filename="attendance_{today}.csv"'
writer = csv.writer(response)
writer.writerow(['Name', 'Username', 'Department', 'Status', 'Time', 'Distance (m)'])
```

The exported file includes one row per attendance record with columns for employee name, username, department, attendance status, check-in time, and distance from the hospital center in metres.

---

## 4.6 User Interface Implementation

All pages are rendered server-side using Django's template engine. Tailwind CSS provides the styling. No separate frontend framework is used. Interactive elements such as the GPS clock-in button, table search, and notification panel use plain JavaScript included per page.

### 4.6.1 Template Architecture

Two base layout templates enforce a strict separation between the admin and staff experiences:

- **`base_admin.html`**: Full sidebar navigation (Dashboard, Attendance, Staff, Add Staff), notification bell with live badge and slide-in panel, and sign-out button. Used by all admin pages.
- **`base_staff.html`**: Minimal sidebar with only Clock In and My Records links. Used by staff-facing pages.

All pages extend one of these two base templates using Django's `{% extends %}` and `{% block %}` directives, ensuring consistent layout, navigation, and style across the application.

A custom template tag (`dict_extras.get_item`) was written to enable dictionary key lookups inside Django templates, which is not supported natively. This is used in the weekly attendance grid to check a staff member's attendance status for each day of the week.

```python
# core/templatetags/dict_extras.py
@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)
```

### 4.6.2 System Pages

| Page | URL | Accessible By | Description |
|---|---|---|---|
| Login | `/accounts/login/` | All users | Staff authentication |
| Smart Redirect | `/` | All users | Routes user by role after login |
| Dashboard | `/dashboard/` | Admin | Stats, department bars, alerts panel, weekly grid |
| Attendance | `/attendance/` | Admin | Stats, weekly grid, today's full log with search |
| Export CSV | `/attendance/export/` | Admin | Downloads today's attendance as a CSV file |
| Staff List | `/staff/` | Admin | Searchable and filterable staff directory |
| Add Staff | `/staff/create/` | Admin | Form to create new staff accounts |
| Clock In | `/clock-in/` | Staff | GPS clock-in button and today's personal log |
| My Records | `/my-records/` | Staff | Personal attendance history with summary statistics |

### 4.6.3 Clock-In Interface Sequence

The clock-in page implements the following user interaction sequence:

1. Staff member presses "Clock In Now"
2. A yellow pulsing dot indicates that GPS acquisition is in progress
3. `navigator.geolocation.getCurrentPosition()` is called with `enableHighAccuracy: true` and a 10-second timeout
4. On a successful fix, the dot turns green and displays the GPS accuracy reading in metres
5. Coordinates are transmitted to the server via a non-blocking `fetch()` POST request
6. The server validates the coordinates against the geofence and returns a JSON response
7. The result banner appears — green for a successful clock-in, red for out of bounds — with an informative message including the exact distance
8. The page automatically reloads after 2.5 seconds to update the attendance log shown on the right side of the screen

---

## 4.7 Security Implementation

The following security mechanisms are implemented throughout the system:

**CSRF Protection**: Django's `CsrfViewMiddleware` is active for all state-changing requests. Every HTML form and JavaScript `fetch()` POST call includes the `X-CSRFToken` header, preventing cross-site request forgery attacks.

**Password Hashing**: All passwords are hashed using Django's default PBKDF2-SHA256 algorithm with a random salt before storage. The `create_user()` method enforces this. Plain-text passwords are never stored.

**Session-Based Authentication**: Django manages login state through server-side sessions. Session cookies are HTTP-only by default, preventing JavaScript from reading them.

**Role-Based Access Control**: Every admin view is protected with both `@login_required` and `@user_passes_test(is_admin)`. A staff member cannot access any admin URL. Unauthenticated users are redirected to the login page.

**Server-Side Geofence Validation**: The GPS check runs on the server. The browser only transmits raw coordinates. There is no way for a client to manipulate the outcome of the geofence decision.

**Closed Registration**: Staff accounts are not self-registrable. All accounts must be created by an authenticated administrator, blocking unauthorised users from entering the system.

**Notification Endpoint Protection**: All three notification API endpoints require both login and admin status. They also enforce HTTP method restrictions using `@require_POST` where applicable, preventing accidental or malicious GET-based state changes.

---

## 4.8 System Testing

### 4.8.1 Functional Test Cases

The table below summarises the functional tests carried out on the implemented system.

| Test Case | Input | Expected Output | Result |
|---|---|---|---|
| TC-01: Login — valid credentials | Correct username and password | Admin → Dashboard, Staff → Clock-in | Pass |
| TC-02: Login — invalid credentials | Wrong password | Error message, access denied | Pass |
| TC-03: Clock-in within geofence | GPS coordinates within configured radius | Status "Present", success message, record saved | Pass |
| TC-04: Clock-in outside geofence | GPS coordinates beyond radius | Status "Out of Bounds", distance reported, record saved | Pass |
| TC-05: Out-of-bounds notification | Out-of-bounds clock-in occurs | Error notification created, appears in bell panel | Pass |
| TC-06: GPS permission denied | Browser geolocation blocked | Error message shown, no record created | Pass |
| TC-07: Create staff — valid data | All fields correctly filled | Account created, notification generated, redirected to staff list | Pass |
| TC-08: Create staff — duplicate username | Existing username submitted | Error message, no account created, form retained | Pass |
| TC-09: Create staff — password mismatch | Different password confirmation | Error message, form retained | Pass |
| TC-10: Create staff — short password | Password under 8 characters | Error message, form retained | Pass |
| TC-11: Staff accessing admin URL | Staff visits `/dashboard/` | Redirected to login (permission denied) | Pass |
| TC-12: Unauthenticated access | Unlogged user visits any URL | Redirected to `/accounts/login/` | Pass |
| TC-13: Export CSV | Admin clicks Export CSV | CSV file downloaded with correct headers and data | Pass |
| TC-14: Attendance search | Admin types name in search box | Table rows filtered in real time | Pass |
| TC-15: Weekly attendance grid | Staff clocks in across multiple days | Correct days show "✓", unrecorded days show "—" | Pass |
| TC-16: Notification bell badge | Unread notifications exist | Badge shows correct unread count | Pass |
| TC-17: Dismiss single notification | Admin clicks ✕ on a notification | Notification removed from panel, marked read in database | Pass |
| TC-18: Mark all read | Admin clicks "Mark all read" | All notifications marked read, panel shows empty state | Pass |
| TC-19: Notification auto-poll | New clock-in event occurs | Bell badge updates within 30 seconds without page refresh | Pass |
| TC-20: My Records page | Staff visits `/my-records/` | Personal attendance history shown with correct monthly and total counts | Pass |

### 4.8.2 GPS Accuracy Considerations

The Browser Geolocation API reports accuracy through `position.coords.accuracy`, which represents the 68% confidence radius in metres. Practical accuracy varies by environment:

| Environment | Typical Accuracy |
|---|---|
| Outdoors, clear sky | 3 – 10 metres |
| Near buildings | 10 – 50 metres |
| Indoor environments | 20 – 100+ metres |

The system displays the accuracy reading to the staff member at the point of clock-in so they are aware of the margin. The geofence radius is configurable by the administrator (default: 200 metres), which is designed to comfortably accommodate typical GPS inaccuracy for outdoor and near-building scenarios while still confirming physical presence at the hospital.

### 4.8.3 Django System Check

The built-in Django system check framework was run to validate the full configuration:

```
$ python manage.py check
System check identified no issues (0 silenced).
```

No configuration errors or warnings were found.

### 4.8.4 Database Migration Log

The system database was set up through three sequential migrations generated by Django's ORM:

| Migration | Description |
|---|---|
| `core/migrations/0001_initial.py` | Created HospitalBranch, AttendanceRecord, Profile tables |
| `core/migrations/0002_*` | Applied additional field changes |
| `core/migrations/0003_notification.py` | Created the Notification table |

---

## 4.9 System Limitations and Recommendations

### 4.9.1 Current Limitations

1. **GPS accuracy indoors**: Browser-based GPS is less accurate inside buildings. A native mobile application would access hardware GPS directly for improved indoor accuracy.
2. **No check-out tracking**: The system records when staff arrive but does not currently capture when they leave. Working hours cannot be calculated from the current data.
3. **SQLite not suitable for production**: SQLite does not handle high concurrency. A production deployment would require migration to PostgreSQL or MySQL.
4. **No automated reporting**: Attendance summaries are not automatically emailed to supervisors. This currently requires manual CSV export.
5. **Single hospital branch**: The system is currently designed around one `HospitalBranch` record. Multi-branch support would require additional UI and routing logic.

### 4.9.2 Recommendations for Future Work

- Development of a dedicated mobile application (Android/iOS) for native GPS access and improved accuracy
- Implementation of a check-out mechanism to support working hours calculation
- Automated daily attendance summary emails sent to department heads
- Integration with a payroll system using the attendance data
- Migration to PostgreSQL and deployment to a cloud hosting environment
- Multi-branch support to extend the system to other hospital sites

---

## 4.10 Summary

This chapter presented the full implementation of the War Memorial Hospital GPS-Based Staff Attendance System. The system was built using the Django web framework with SQLite as the development database and Tailwind CSS for the user interface. Four data models capture hospital configuration, attendance events, staff profiles, and system notifications. The geofencing mechanism uses GeoPy's geodesic distance function to determine whether a staff member's device is within the hospital perimeter at the time of clocking in, with the entire validation running server-side to prevent manipulation. The system enforces strict role-based access control between administrators and staff, with two separate interface layouts. Administrators have access to a live dashboard showing attendance statistics, department breakdowns, a weekly attendance grid, and a real-time notification panel that automatically alerts them to out-of-bounds clock-in attempts and new account registrations. Staff have a simple clock-in interface and a personal attendance history view. Twenty functional test cases confirmed that all modules — authentication, GPS clock-in, attendance logging, staff management, notifications, and CSV export — operate correctly as designed.
