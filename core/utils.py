from geopy.distance import geodesic

def is_within_geofence(user_lat, user_lon, hospital):
    user_coords = (user_lat, user_lon)
    hospital_coords = (hospital.latitude, hospital.longitude)
    
    # Calculate distance in meters
    distance = geodesic(hospital_coords, user_coords).meters
    
    if distance <= hospital.radius_meters:
        return True, distance
    return False, distance