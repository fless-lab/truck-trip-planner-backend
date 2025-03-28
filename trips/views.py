import os
import polyline
from datetime import datetime, timedelta, time
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from dotenv import load_dotenv
from .models import Trip, LogEntry
from .serializers import TripSerializer
from .constants import (
    AVERAGE_SPEED, MAX_DRIVING_HOURS_PER_WINDOW, MAX_DUTY_HOURS_PER_WINDOW,
    MAX_DRIVING_HOURS_BEFORE_BREAK, MAX_CYCLE_HOURS, FUELING_INTERVAL,
    MINIMUM_REST_HOURS, RESTART_HOURS, CITIES, CITIES_WITH_COORDS
)

load_dotenv()

class TripListView(generics.ListAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer

class TripCreateView(generics.CreateAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer

    def perform_create(self, serializer):
        current_location = self.request.data.get('current_location')
        pickup_location = self.request.data.get('pickup_location')
        dropoff_location = self.request.data.get('dropoff_location')
        current_cycle_hours = float(self.request.data.get('current_cycle_hours', 0))
        start_time = self.request.data.get('start_time')

        if not all([current_location, pickup_location, dropoff_location]):
            raise ValueError("All location fields are required.")
        if not 0 <= current_cycle_hours <= MAX_CYCLE_HOURS:
            raise ValueError(f"current_cycle_hours must be between 0 and {MAX_CYCLE_HOURS}.")

        start_time = (datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                      if start_time else timezone.now())

        distance_to_pickup, distance_to_dropoff = self.calculate_distance(
            current_location, pickup_location, dropoff_location
        )
        total_distance = distance_to_pickup + distance_to_dropoff
        
        # Utilisation des durées calculées par l'API OpenRouteService
        estimated_duration = self.duration_to_pickup + self.duration_to_dropoff

        trip = serializer.save(
            distance=total_distance,
            estimated_duration=estimated_duration,
            current_cycle_hours=current_cycle_hours,
            start_time=start_time,
            current_location=current_location,
            pickup_location=pickup_location,
            dropoff_location=dropoff_location,
            route_geometry_to_pickup=self.route_geometry_to_pickup,
            route_geometry_to_dropoff=self.route_geometry_to_dropoff
        )

        self.generate_eld_logs(trip, distance_to_pickup, distance_to_dropoff, current_cycle_hours)

    def calculate_distance(self, current_location, pickup_location, dropoff_location):
        import os
        import requests
        from .constants import CITIES_WITH_COORDS
        print("here is the details : ")
       
        api_key = os.environ.get('MAP_API_KEY')
        if not api_key:
            raise ValueError("MAP_API_KEY is not set in environment variables")
        
        if current_location not in CITIES_WITH_COORDS:
            raise ValueError(f"Current location '{current_location}' not found in CITIES_WITH_COORDS")
        if pickup_location not in CITIES_WITH_COORDS:
            raise ValueError(f"Pickup location '{pickup_location}' not found in CITIES_WITH_COORDS")
        if dropoff_location not in CITIES_WITH_COORDS:
            raise ValueError(f"Dropoff location '{dropoff_location}' not found in CITIES_WITH_COORDS")
        
        # Initialisation des variables pour stocker les durées
        duration_to_pickup = 0
        
        if current_location == pickup_location:
            distance_to_pickup = 0
            self.route_geometry_to_pickup = None
        else:
            current_coords = CITIES_WITH_COORDS[current_location]
            pickup_coords = CITIES_WITH_COORDS[pickup_location]
            
            # Récupération de la distance, de la durée et de la géométrie de la route
            distance_to_pickup, duration_to_pickup, geometry_to_pickup = self._calculate_route_distance(current_coords, pickup_coords, api_key)
            self.route_geometry_to_pickup = geometry_to_pickup
        
        pickup_coords = CITIES_WITH_COORDS[pickup_location]
        dropoff_coords = CITIES_WITH_COORDS[dropoff_location]
        
        print(f"Pickup coord : {pickup_coords}")
        print(f"Dropoff coord : {dropoff_coords}")
        
        # Récupération de la distance et de la durée
        distance_to_dropoff, duration_to_dropoff, geometry_to_dropoff = self._calculate_route_distance(pickup_coords, dropoff_coords, api_key)
        self.route_geometry_to_dropoff = geometry_to_dropoff
        
        # Stockage des durées dans des attributs de l'instance pour utilisation dans perform_create
        self.duration_to_pickup = duration_to_pickup
        self.duration_to_dropoff = duration_to_dropoff
        
        # Stockage des segments de route pour les deux parties du trajet
        self.segments_to_pickup = self.route_segments if current_location != pickup_location else []
        self.segments_to_dropoff = self.route_segments
        
        return distance_to_pickup, distance_to_dropoff
    
    def _calculate_route_distance(self, start_coords, end_coords, api_key):
        """Calcule la distance et la durée entre deux points en utilisant l'API OpenRouteService.
        
        Utilise le profil 'driving-hgv' pour les camions et prend en compte les restrictions routières.
        En cas d'échec, utilise geodesic comme solution de secours.
        
        Args:
            start_coords (list): Coordonnées [lat, lon] du point de départ
            end_coords (list): Coordonnées [lat, lon] du point d'arrivée
            api_key (str): Clé API OpenRouteService
            
        Returns:
            tuple: (distance_miles, duration_hours) - Distance en miles et durée en heures
                   basées sur les données réelles de l'API OpenRouteService
        """
        import requests
        
        # OpenRouteService attend les coordonnées au format [lon, lat]
        start = [start_coords[1], start_coords[0]]
        end = [end_coords[1], end_coords[0]]
        print("start : ", start)
        print("end : ", end)
        
        # Configuration de l'API OpenRouteService pour les camions (HGV)
        url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
        headers = {
            'Accept': 'application/json, application/geo+json, application/gpx+xml, img/png; charset=utf-8',
            'Authorization': api_key,
            'Content-Type': 'application/json; charset=utf-8'
        }
        
        # Paramètres spécifiques pour les camions
        body = {
            "coordinates": [start, end],
            "profile": "driving-hgv",  # Profil spécifique pour les camions
            "preference": "recommended",  # Itinéraire recommandé
            "units": "mi",  # Unités en miles
            "language": "fr-fr",
            # Paramètres optionnels pour les camions
            "options": {
                "vehicle_type": "hgv",  # Type de véhicule: poids lourd
                "profile_params": {
                    "restrictions": {
                        "height": 4.0,  # Hauteur en mètres
                        "width": 2.55,  # Largeur en mètres
                        "length": 16.5,  # Longueur en mètres
                        "weight": 40.0,  # Poids en tonnes
                        "axleload": 11.5  # Charge par essieu en tonnes
                    }
                }
            }
        }
        
        try:
            # Appel à l'API OpenRouteService
            print("Req : ", url, body, headers)
            response = requests.post(url, json=body, headers=headers)
            print(response.status_code, response.reason)
            print(response.text)
            response.raise_for_status()  # Lève une exception en cas d'erreur HTTP
            
            # Traitement de la réponse
            data = response.json()
            print("response.data : ", data)
            
            # Extraction de la distance (déjà en miles vu que précisé dans le corps de la requête)
            distance_miles = data['routes'][0]['summary']['distance']
            
            # Extraction du temps de trajet en heures (conversion de secondes en heures)
            duration_hours = data['routes'][0]['summary']['duration'] / 3600
            
            # Extraction du polyline encodé
            geometry = data['routes'][0]['geometry']  # Polyline encodé
            
            # Extraction des segments de l'itinéraire pour un traitement plus granulaire
            route_segments = []
            if 'segments' in data['routes'][0]:
                for segment in data['routes'][0]['segments']:
                    # Pour chaque segment, extraire les étapes (steps)
                    steps = []
                    if 'steps' in segment:
                        for step in segment['steps']:
                            steps.append({
                                'distance': step['distance'],  # en miles
                                'duration': step['duration'] / 3600,  # conversion en heures
                                'instruction': step['instruction'],
                                'name': step['name'],
                                'way_points': step.get('way_points', [])
                            })
                    
                    route_segments.append({
                        'distance': segment['distance'],  # en miles
                        'duration': segment['duration'] / 3600,  # conversion en heures
                        'steps': steps
                    })
            
            # Stockage des segments dans des attributs de l'instance pour utilisation dans generate_eld_logs
            self.route_segments = route_segments
            
            return distance_miles, duration_hours, geometry
            
        except requests.exceptions.RequestException as e:
            # En cas d'erreur avec l'API, utiliser geodesic comme solution de secours
            print(f"Error calculating distance with OpenRouteService: {e}")
            
            # Calcul de la distance à vol d'oiseau comme solution de secours
            from geopy.distance import geodesic
            distance_miles = geodesic((start_coords[0], start_coords[1]), (end_coords[0], end_coords[1])).miles
            # Estimation de la durée basée sur la vitesse moyenne en cas d'échec
            from .constants import AVERAGE_SPEED
            duration_hours = distance_miles / AVERAGE_SPEED
            
            return distance_miles, duration_hours, None

    def interpolate_coords(self, route_coords, route_distances, target_distance):
        """Interpole les coordonnées pour une distance donnée le long de la polyline.
        
        Args:
            route_coords (list): Liste de tuples (lat, lon) représentant les points de la polyline.
            route_distances (list): Liste des distances cumulatives le long de la polyline.
            target_distance (float): Distance cible en miles.
            
        Returns:
            tuple: (latitude, longitude) interpolée, ou None si l'interpolation n'est pas possible.
        """
        if not route_coords or not route_distances or len(route_coords) != len(route_distances):
            return None
        
        if target_distance < 0:
            return None
        
        total_distance = route_distances[-1]
        if target_distance >= total_distance:
            return route_coords[-1]  # Retourner le dernier point si la distance dépasse
        
        # Trouver les deux points entre lesquels interpoler
        for i in range(len(route_distances) - 1):
            if route_distances[i] <= target_distance <= route_distances[i + 1]:
                # Calculer la fraction entre les deux points
                fraction = (target_distance - route_distances[i]) / (route_distances[i + 1] - route_distances[i])
                # Interpoler la latitude et la longitude
                lat = route_coords[i][0] + fraction * (route_coords[i + 1][0] - route_coords[i][0])
                lon = route_coords[i][1] + fraction * (route_coords[i + 1][1] - route_coords[i][1])
                return (lat, lon)
        return None

    def calculate_cumulative_distances(self, coords):
        """Calcule les distances cumulatives le long d'une liste de coordonnées (latitude, longitude).
        
        Args:
            coords (list): Liste de tuples (lat, lon) représentant les points de la polyline.
            
        Returns:
            list: Liste des distances cumulatives en miles.
        """
        from geopy.distance import geodesic
        
        if not coords:
            return []
        
        distances = [0.0]  # Distance cumulée commence à 0
        for i in range(1, len(coords)):
            point1 = coords[i-1]  # (lat1, lon1)
            point2 = coords[i]    # (lat2, lon2)
            dist = geodesic(point1, point2).miles  # Distance en miles
            distances.append(distances[-1] + dist)  # Ajouter à la distance cumulée
        return distances

    def generate_eld_logs(self, trip, distance_to_pickup, distance_to_dropoff, current_cycle_hours):
        current_time = trip.start_time
        last_entry_end_time = current_time  # Suivi de la fin de la dernière entrée pour éviter les retours en arrière
        current_distance = 0
        
        # Récupération des segments de route calculés par l'API OpenRouteService
        segments_to_pickup = self.segments_to_pickup
        segments_to_dropoff = self.segments_to_dropoff
        
        # Récupération des durées calculées par l'API OpenRouteService
        duration_to_pickup = self.duration_to_pickup
        duration_to_dropoff = self.duration_to_dropoff
        
        # Décoder les polylines pour obtenir les coordonnées
        coords_to_pickup = polyline.decode(trip.route_geometry_to_pickup) if trip.route_geometry_to_pickup else []
        coords_to_dropoff = polyline.decode(trip.route_geometry_to_dropoff)
        
        # Ajouter un message de débogage pour vérifier le premier point
        if coords_to_pickup:
            print(f"Premier point de coords_to_pickup : {coords_to_pickup[0]} (devrait être proche de {CITIES_WITH_COORDS[trip.current_location]})")
        if coords_to_dropoff:
            print(f"Premier point de coords_to_dropoff : {coords_to_dropoff[0]} (devrait être proche de {CITIES_WITH_COORDS[trip.pickup_location]})")
        
        all_coords = coords_to_pickup + coords_to_dropoff if coords_to_pickup else coords_to_dropoff
        
        # Calculer les distances cumulatives pour chaque partie du trajet
        distances_to_pickup = self.calculate_cumulative_distances(coords_to_pickup)
        distances_to_dropoff = self.calculate_cumulative_distances(coords_to_dropoff)
        
        # Combiner les distances cumulatives
        if distances_to_pickup:
            # Ajuster les distances de la deuxième partie en ajoutant la distance totale de la première partie
            all_distances = distances_to_pickup + [d + distances_to_pickup[-1] for d in distances_to_dropoff]
        else:
            all_distances = distances_to_dropoff
        
        # Création d'une liste combinée de tous les steps du trajet pour une approche plus granulaire
        all_steps = []
        step_index_offset = 0
        
        # Ajout des steps pour aller au point de ramassage
        for segment in segments_to_pickup:
            for step in segment['steps']:
                way_points = step.get('way_points', [0, 0])
                start_idx = way_points[0] + step_index_offset
                end_idx = way_points[1] + step_index_offset
                all_steps.append({
                    'distance': step['distance'],
                    'duration': step['duration'],
                    'instruction': step['instruction'],
                    'name': step['name'],
                    'phase': 'pickup',
                    'description': f"Conduite de {trip.current_location} à {trip.pickup_location}: {step['instruction']} sur {step['name']}",
                    'start_coords': all_coords[start_idx] if start_idx < len(all_coords) else None,
                    'end_coords': all_coords[end_idx] if end_idx < len(all_coords) else None
                })
                
        step_index_offset = len(coords_to_pickup) if coords_to_pickup else 0
        
        # Ajout des steps pour aller du point de ramassage à la destination
        for segment in segments_to_dropoff:
            for step in segment['steps']:
                way_points = step.get('way_points', [0, 0])
                start_idx = way_points[0] + step_index_offset
                end_idx = way_points[1] + step_index_offset
                all_steps.append({
                    'distance': step['distance'],
                    'duration': step['duration'],
                    'instruction': step['instruction'],
                    'name': step['name'],
                    'phase': 'dropoff',
                    'description': f"Conduite de {trip.pickup_location} à {trip.dropoff_location}: {step['instruction']} sur {step['name']}",
                    'start_coords': all_coords[start_idx] if start_idx < len(all_coords) else None,
                    'end_coords': all_coords[end_idx] if end_idx < len(all_coords) else None
                })
        
        # Utilisation des steps pour une approche plus granulaire
        total_on_duty_hours = current_cycle_hours
        fueling_stops_made = set()
        log_entries = []

        # Ajouter un événement initial pour marquer le début du trajet
        initial_end_time = current_time + timedelta(seconds=1)  # 15 minutes pour le départ
        initial_coords = CITIES_WITH_COORDS[trip.current_location]  # Coordonnées de New York, NY
        initial_latitude = initial_coords[0]  # 40.7128
        initial_longitude = initial_coords[1]  # -74.0060
        print(f"Adding initial entry: DRIVING from {current_time} to {initial_end_time} at 0 miles")
        self.add_log_entry(
            log_entries,
            trip,
            current_time,
            initial_end_time,
            'DRIVING',
            f"Départ de {trip.current_location}",
            0,  # Distance = 0 miles
            initial_latitude,
            initial_longitude
        )
        last_entry_end_time = initial_end_time
        current_time = initial_end_time
        # total_on_duty_hours += 0.25  # Ajouter 15 minutes (0.25 heures) au total des heures de service

        trip_state = {"last_duty_start_time": None}
        driving_buffer_start = None
        driving_buffer_minutes = 0

        total_distance = distance_to_pickup + distance_to_dropoff
        in_initial_driving_phase = distance_to_pickup > 0
        pickup_completed = False
        
        # Initialisation du compteur pour suivre la progression dans les steps
        current_step_index = 0
        
        # Boucle principale utilisant les steps granulaires au lieu des segments complets
        while current_distance < total_distance:
            if not trip_state["last_duty_start_time"]:
                trip_state["last_duty_start_time"] = current_time
            
            window_start = trip_state["last_duty_start_time"]
            window_driving_hours = 0
            driving_since_last_break = 0

            while window_driving_hours < MAX_DRIVING_HOURS_PER_WINDOW and current_distance < total_distance:
                time_in_window = (current_time - window_start).total_seconds() / 3600
                if time_in_window >= MAX_DUTY_HOURS_PER_WINDOW:
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        location = (f"Driving from {trip.current_location} to {trip.pickup_location}" if in_initial_driving_phase
                                    else "Driving")
                        # S'assurer que le start_time est >= last_entry_end_time
                        if driving_buffer_start < last_entry_end_time:
                            driving_buffer_start = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance, latitude, longitude)
                        last_entry_end_time = buffer_end_time
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    end_time = current_time + timedelta(hours=MINIMUM_REST_HOURS)
                    # S'assurer que le start_time est >= last_entry_end_time
                    if current_time < last_entry_end_time:
                        current_time = last_entry_end_time
                    # Interpoler les coordonnées pour la distance actuelle
                    coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                    latitude = coords[0] if coords else None
                    longitude = coords[1] if coords else None
                    print(f"Adding entry: SLEEPER_BERTH from {current_time} to {end_time} at {current_distance} miles")
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'SLEEPER_BERTH', "10h Rest after 14h Service", current_distance, latitude, longitude)
                    last_entry_end_time = end_time
                    current_time = end_time
                    trip_state["last_duty_start_time"] = None
                    break

                remaining_cycle_hours = MAX_CYCLE_HOURS - total_on_duty_hours
                if remaining_cycle_hours <= 0:
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        location = (f"Driving from {trip.current_location} to {trip.pickup_location}" if in_initial_driving_phase
                                    else "Driving")
                        if driving_buffer_start < last_entry_end_time:
                            driving_buffer_start = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance, latitude, longitude)
                        last_entry_end_time = buffer_end_time
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    end_time = current_time + timedelta(hours=RESTART_HOURS)
                    if current_time < last_entry_end_time:
                        current_time = last_entry_end_time
                    # Interpoler les coordonnées pour la distance actuelle
                    coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                    latitude = coords[0] if coords else None
                    longitude = coords[1] if coords else None
                    print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                    last_entry_end_time = end_time
                    current_time = end_time
                    total_on_duty_hours = 0
                    trip_state["last_duty_start_time"] = None
                    break

                if in_initial_driving_phase and current_distance >= distance_to_pickup and not pickup_completed:
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        if driving_buffer_start < last_entry_end_time:
                            driving_buffer_start = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', f"Conduite de {trip.current_location} à {trip.pickup_location}", current_distance, latitude, longitude)
                        last_entry_end_time = buffer_end_time
                        driving_buffer_start = None
                        driving_buffer_minutes = 0
                        
                    current_distance = distance_to_pickup

                    pickup_end_time = current_time + timedelta(hours=1)
                    if current_time < last_entry_end_time:
                        current_time = last_entry_end_time
                    # Utiliser les coordonnées exactes de pickup_location (Chicago, IL) au lieu d'interpoler
                    pickup_coords = CITIES_WITH_COORDS[trip.pickup_location]  # (41.8781, -87.6298) pour Chicago, IL
                    latitude = pickup_coords[0]  # 41.8781
                    longitude = pickup_coords[1]  # -87.6298
                    print(f"Adding entry: ON_DUTY_NOT_DRIVING from {current_time} to {pickup_end_time} at {current_distance} miles")
                    self.add_log_entry(log_entries, trip, current_time, pickup_end_time, 'ON_DUTY_NOT_DRIVING', f"Pickup at {trip.pickup_location}", current_distance, latitude, longitude)
                    last_entry_end_time = pickup_end_time
                    current_time = pickup_end_time
                    total_on_duty_hours += 1
                    pickup_completed = True
                    in_initial_driving_phase = False

                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                        last_entry_end_time = end_time
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break

                    time_in_window = (current_time - window_start).total_seconds() / 3600
                    if time_in_window >= MAX_DUTY_HOURS_PER_WINDOW:
                        end_time = current_time + timedelta(hours=MINIMUM_REST_HOURS)
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: SLEEPER_BERTH from {current_time} to {end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'SLEEPER_BERTH', "10h Rest after 14h Service", current_distance, latitude, longitude)
                        last_entry_end_time = end_time
                        current_time = end_time
                        trip_state["last_duty_start_time"] = None
                        break

                    continue

                if driving_since_last_break >= MAX_DRIVING_HOURS_BEFORE_BREAK:
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        location = (f"Driving from {trip.current_location} to {trip.pickup_location}" if in_initial_driving_phase
                                    else "Driving")
                        if driving_buffer_start < last_entry_end_time:
                            driving_buffer_start = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance, latitude, longitude)
                        last_entry_end_time = buffer_end_time
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    end_time = current_time + timedelta(minutes=30)
                    if current_time < last_entry_end_time:
                        current_time = last_entry_end_time
                    # Interpoler les coordonnées pour la distance actuelle
                    coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                    latitude = coords[0] if coords else None
                    longitude = coords[1] if coords else None
                    print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "30min Break", current_distance, latitude, longitude)
                    last_entry_end_time = end_time
                    current_time = end_time
                    driving_since_last_break = 0
                    total_on_duty_hours += 0.5
                    
                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                        last_entry_end_time = end_time
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break
                    
                    continue

                # Calcul du prochain arrêt de ravitaillement
                next_fueling_mile = (int(current_distance // FUELING_INTERVAL) + 1) * FUELING_INTERVAL
                print(f"Distance actuelle: {current_distance}, Prochain ravitaillement: {next_fueling_mile}, Différence: {next_fueling_mile - current_distance}")
                if next_fueling_mile not in fueling_stops_made and current_distance + 60 >= next_fueling_mile:
                    minutes_to_fuel = (next_fueling_mile - current_distance) / (AVERAGE_SPEED / 60)
                    hours_to_fuel = minutes_to_fuel / 60
                    
                    if total_on_duty_hours + hours_to_fuel >= MAX_CYCLE_HOURS:
                        minutes_to_cycle_limit = (MAX_CYCLE_HOURS - total_on_duty_hours) * 60
                        if minutes_to_cycle_limit <= 0:
                            if driving_buffer_minutes > 0:
                                buffer_end_time = current_time
                                location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                            else "Conduite")
                                if driving_buffer_start < last_entry_end_time:
                                    driving_buffer_start = last_entry_end_time
                                # Interpoler les coordonnées pour la distance actuelle
                                coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                                latitude = coords[0] if coords else None
                                longitude = coords[1] if coords else None
                                print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                                self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance, latitude, longitude)
                                last_entry_end_time = buffer_end_time
                                driving_buffer_start = None
                                driving_buffer_minutes = 0

                            end_time = current_time + timedelta(hours=RESTART_HOURS)
                            if current_time < last_entry_end_time:
                                current_time = last_entry_end_time
                            # Interpoler les coordonnées pour la distance actuelle
                            coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                            latitude = coords[0] if coords else None
                            longitude = coords[1] if coords else None
                            print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                            self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                            last_entry_end_time = end_time
                            current_time = end_time
                            total_on_duty_hours = 0
                            trip_state["last_duty_start_time"] = None
                            break
                        
                        if driving_buffer_minutes > 0:
                            buffer_end_time = current_time
                            location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                        else "Conduite")
                            if driving_buffer_start < last_entry_end_time:
                                driving_buffer_start = last_entry_end_time
                            # Interpoler les coordonnées pour la distance actuelle
                            coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                            latitude = coords[0] if coords else None
                            longitude = coords[1] if coords else None
                            print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                            self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance, latitude, longitude)
                            last_entry_end_time = buffer_end_time
                            driving_buffer_start = None
                            driving_buffer_minutes = 0
                            
                        cycle_limit_time = current_time + timedelta(minutes=minutes_to_cycle_limit)
                        location = (f"Conduite de {trip.current_location} à {trip.pickup_location} jusqu'à limite du cycle" if in_initial_driving_phase
                                    else "Conduite jusqu'à limite du cycle")
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: DRIVING from {current_time} to {cycle_limit_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time, cycle_limit_time, 'DRIVING', location, current_distance, latitude, longitude)
                        last_entry_end_time = cycle_limit_time
                        current_time = cycle_limit_time
                        current_distance += minutes_to_cycle_limit * (AVERAGE_SPEED / 60)
                        window_driving_hours += minutes_to_cycle_limit / 60
                        driving_since_last_break += minutes_to_cycle_limit / 60
                        total_on_duty_hours = MAX_CYCLE_HOURS
                        
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                        last_entry_end_time = end_time
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break
                    
                    if window_driving_hours + hours_to_fuel > MAX_DRIVING_HOURS_PER_WINDOW:
                        hours_to_fuel = MAX_DRIVING_HOURS_PER_WINDOW - window_driving_hours
                        minutes_to_fuel = hours_to_fuel * 60

                    if driving_since_last_break + (minutes_to_fuel / 60) > MAX_DRIVING_HOURS_BEFORE_BREAK:
                        minutes_to_break = (MAX_DRIVING_HOURS_BEFORE_BREAK - driving_since_last_break) * 60
                        hours_to_break = minutes_to_break / 60
                        end_time = current_time + timedelta(minutes=minutes_to_break)
                        
                        if driving_buffer_minutes > 0:
                            buffer_end_time = current_time
                            location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                        else "Conduite")
                            if driving_buffer_start < last_entry_end_time:
                                driving_buffer_start = last_entry_end_time
                            # Interpoler les coordonnées pour la distance actuelle
                            coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                            latitude = coords[0] if coords else None
                            longitude = coords[1] if coords else None
                            print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                            self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance, latitude, longitude)
                            last_entry_end_time = buffer_end_time
                            driving_buffer_start = None
                            driving_buffer_minutes = 0

                        location = (f"Conduite de {trip.current_location} à {trip.pickup_location} jusqu'à la pause" if in_initial_driving_phase
                                    else "Conduite jusqu'à la pause")
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: DRIVING from {current_time} to {end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'DRIVING', location, current_distance, latitude, longitude)
                        last_entry_end_time = end_time
                        current_time = end_time
                        current_distance += minutes_to_break * (AVERAGE_SPEED / 60)
                        window_driving_hours += hours_to_break
                        driving_since_last_break += hours_to_break
                        total_on_duty_hours += hours_to_break
                        
                        if total_on_duty_hours >= MAX_CYCLE_HOURS:
                            end_time = current_time + timedelta(hours=RESTART_HOURS)
                            if current_time < last_entry_end_time:
                                current_time = last_entry_end_time
                            # Interpoler les coordonnées pour la distance actuelle
                            coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                            latitude = coords[0] if coords else None
                            longitude = coords[1] if coords else None
                            print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                            self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                            last_entry_end_time = end_time
                            current_time = end_time
                            total_on_duty_hours = 0
                            trip_state["last_duty_start_time"] = None
                            break

                        end_time = current_time + timedelta(minutes=30)
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "30min Break", current_distance, latitude, longitude)
                        last_entry_end_time = end_time
                        current_time = end_time
                        driving_since_last_break = 0
                        total_on_duty_hours += 0.5
                        
                        if total_on_duty_hours >= MAX_CYCLE_HOURS:
                            end_time = current_time + timedelta(hours=RESTART_HOURS)
                            if current_time < last_entry_end_time:
                                current_time = last_entry_end_time
                            # Interpoler les coordonnées pour la distance actuelle
                            coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                            latitude = coords[0] if coords else None
                            longitude = coords[1] if coords else None
                            print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                            self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                            last_entry_end_time = end_time
                            current_time = end_time
                            total_on_duty_hours = 0
                            trip_state["last_duty_start_time"] = None
                            break
                            
                        continue

                    end_time = current_time + timedelta(minutes=minutes_to_fuel)
                    
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        location = (f"Driving from {trip.current_location} to {trip.pickup_location}" if in_initial_driving_phase
                                    else "Driving")
                        if driving_buffer_start < last_entry_end_time:
                            driving_buffer_start = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance, latitude, longitude)
                        last_entry_end_time = buffer_end_time
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    location = (f"Driving from {trip.current_location} to {trip.pickup_location} until fuel stop" if in_initial_driving_phase
                                else "Driving until fuel stop")
                    if current_time < last_entry_end_time:
                        current_time = last_entry_end_time
                    # Interpoler les coordonnées pour la distance actuelle
                    coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                    latitude = coords[0] if coords else None
                    longitude = coords[1] if coords else None
                    print(f"Adding entry: DRIVING from {current_time} to {end_time} at {current_distance} miles")
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'DRIVING', location, current_distance, latitude, longitude)
                    last_entry_end_time = end_time
                    current_time = end_time
                    current_distance += minutes_to_fuel * (AVERAGE_SPEED / 60)
                    window_driving_hours += hours_to_fuel
                    driving_since_last_break += hours_to_fuel
                    total_on_duty_hours += hours_to_fuel
                    
                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                        last_entry_end_time = end_time
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break

                    fueling_stops_made.add(next_fueling_mile)
                    end_time = current_time + timedelta(minutes=15)
                    fueling_location = f"Fuel Stop at {next_fueling_mile:.1f} miles"
                    print(f"Adding fuel stop at {next_fueling_mile:.1f} miles")
                    if current_time < last_entry_end_time:
                        current_time = last_entry_end_time
                    # Interpoler les coordonnées pour la distance actuelle
                    coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                    latitude = coords[0] if coords else None
                    longitude = coords[1] if coords else None
                    print(f"Adding entry: ON_DUTY_NOT_DRIVING from {current_time} to {end_time} at {current_distance} miles")
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'ON_DUTY_NOT_DRIVING', fueling_location, current_distance, latitude, longitude)
                    last_entry_end_time = end_time
                    current_time = end_time
                    total_on_duty_hours += 0.25
                    
                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                        last_entry_end_time = end_time
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break

                    driving_buffer_start = None
                    driving_buffer_minutes = 0
                    continue

                next_fueling_mile = (int(current_distance // FUELING_INTERVAL) + 1) * FUELING_INTERVAL
                if next_fueling_mile not in fueling_stops_made and current_distance >= next_fueling_mile - 5:
                    print(f"Fuel stop required at {next_fueling_mile} miles (current distance: {current_distance})")
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        location = (f"Driving from {trip.current_location} to {trip.pickup_location}" if in_initial_driving_phase
                                    else "Driving")
                        if driving_buffer_start < last_entry_end_time:
                            driving_buffer_start = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance, latitude, longitude)
                        last_entry_end_time = buffer_end_time
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    fueling_stops_made.add(next_fueling_mile)
                    end_time = current_time + timedelta(minutes=15)
                    fueling_location = f"Fuel Stop at {next_fueling_mile:.1f} miles"
                    if current_time < last_entry_end_time:
                        current_time = last_entry_end_time
                    # Interpoler les coordonnées pour la distance actuelle
                    coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                    latitude = coords[0] if coords else None
                    longitude = coords[1] if coords else None
                    print(f"Adding entry: ON_DUTY_NOT_DRIVING from {current_time} to {end_time} at {current_distance} miles")
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'ON_DUTY_NOT_DRIVING', fueling_location, current_distance, latitude, longitude)
                    last_entry_end_time = end_time
                    current_time = end_time
                    total_on_duty_hours += 0.25
                    
                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                        last_entry_end_time = end_time
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break
                    continue
                
                if current_step_index < len(all_steps):
                    current_step = all_steps[current_step_index]
                    
                    max_driving_minutes = min(
                        (MAX_DRIVING_HOURS_PER_WINDOW - window_driving_hours) * 60,
                        (MAX_DUTY_HOURS_PER_WINDOW - time_in_window) * 60,
                        (MAX_CYCLE_HOURS - total_on_duty_hours) * 60,
                        (MAX_DRIVING_HOURS_BEFORE_BREAK - driving_since_last_break) * 60
                    )
                    
                    step_duration_minutes = current_step['duration'] * 60
                    driving_minutes = min(max_driving_minutes, step_duration_minutes, 60)
                    
                    if driving_minutes <= 0:
                        break
                    
                    proportion = driving_minutes / step_duration_minutes if step_duration_minutes > 0 else 0
                    distance_covered = current_step['distance'] * proportion
                    
                    end_time = current_time + timedelta(minutes=driving_minutes)
                    current_distance += distance_covered
                    window_driving_hours += driving_minutes / 60
                    driving_since_last_break += driving_minutes / 60
                    total_on_duty_hours += driving_minutes / 60
                    
                    if proportion >= 1 or abs(proportion - 1) < 0.001:
                        current_step_index += 1
                else:
                    remaining_distance = total_distance - current_distance
                    remaining_minutes = min(
                        (MAX_DRIVING_HOURS_PER_WINDOW - window_driving_hours) * 60,
                        (MAX_DUTY_HOURS_PER_WINDOW - time_in_window) * 60,
                        remaining_distance / (AVERAGE_SPEED / 60),
                        (MAX_CYCLE_HOURS - total_on_duty_hours) * 60,
                        60
                    )
                    
                    if remaining_minutes <= 0:
                        break
                    
                    end_time = current_time + timedelta(minutes=remaining_minutes)
                    current_distance += (AVERAGE_SPEED / 60) * remaining_minutes
                    window_driving_hours += remaining_minutes / 60
                    driving_since_last_break += remaining_minutes / 60
                    total_on_duty_hours += remaining_minutes / 60

                if total_on_duty_hours >= MAX_CYCLE_HOURS:
                    if round(total_on_duty_hours, 2) >= MAX_CYCLE_HOURS:
                        if driving_buffer_minutes > 0:
                            buffer_end_time = current_time + timedelta(minutes=1)
                            location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                        else "Conduite")
                            if driving_buffer_start < last_entry_end_time:
                                driving_buffer_start = last_entry_end_time
                            # Interpoler les coordonnées pour la distance actuelle
                            coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                            latitude = coords[0] if coords else None
                            longitude = coords[1] if coords else None
                            print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                            self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance, latitude, longitude)
                            last_entry_end_time = buffer_end_time
                            driving_buffer_start = None
                            driving_buffer_minutes = 0

                        end_time = current_time + timedelta(minutes=1) + timedelta(hours=RESTART_HOURS)
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: OFF_DUTY from {current_time + timedelta(minutes=1)} to {end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time + timedelta(minutes=1), end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance, latitude, longitude)
                        last_entry_end_time = end_time
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break

                if driving_buffer_start is None:
                    driving_buffer_start = current_time
                
                if current_step_index < len(all_steps):
                    driving_buffer_minutes += driving_minutes
                else:
                    driving_buffer_minutes += remaining_minutes
                
                if driving_buffer_minutes >= 60:
                    buffer_end_time = end_time
                    
                    if current_step_index > 0 and current_step_index <= len(all_steps):
                        step_info = all_steps[current_step_index - 1]
                        road_name = step_info['name'] if step_info['name'] and step_info['name'] != '-' else 'route non nommée'
                        instruction = step_info['instruction']
                        
                        if in_initial_driving_phase and not pickup_completed:
                            location = f"Driving from {trip.current_location} to {trip.pickup_location}: {instruction} on {road_name}"
                        else:
                            location = f"Driving from {trip.pickup_location} to {trip.dropoff_location}: {instruction} on {road_name}"
                    else:
                        location = (f"Driving from {trip.current_location} to {trip.pickup_location}" if in_initial_driving_phase and not pickup_completed
                                    else f"Driving from {trip.pickup_location} to {trip.dropoff_location}")
                    
                    if driving_buffer_start < last_entry_end_time:
                        driving_buffer_start = last_entry_end_time
                    # Interpoler les coordonnées pour la distance actuelle
                    coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                    latitude = coords[0] if coords else None
                    longitude = coords[1] if coords else None
                    print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                    self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance, latitude, longitude)
                    last_entry_end_time = buffer_end_time
                    driving_buffer_start = buffer_end_time
                    driving_buffer_minutes = 0

                current_time = end_time

                if window_driving_hours >= MAX_DRIVING_HOURS_PER_WINDOW:
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        location = (f"Driving from {trip.current_location} to {trip.pickup_location}" if in_initial_driving_phase
                                    else "Driving")
                        if driving_buffer_start < last_entry_end_time:
                            driving_buffer_start = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance, latitude, longitude)
                        last_entry_end_time = buffer_end_time
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    time_to_window_end = MAX_DUTY_HOURS_PER_WINDOW - (current_time - window_start).total_seconds() / 3600
                    if time_to_window_end > 0:
                        end_time = current_time + timedelta(hours=time_to_window_end)
                        if current_time < last_entry_end_time:
                            current_time = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: ON_DUTY_NOT_DRIVING from {current_time} to {end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'ON_DUTY_NOT_DRIVING', "14h Window End", current_distance, latitude, longitude)
                        last_entry_end_time = end_time
                        current_time = end_time
                        total_on_duty_hours += time_to_window_end
                        
                        if total_on_duty_hours >= MAX_CYCLE_HOURS:
                            end_time = current_time + timedelta(hours=RESTART_HOURS)
                            if current_time < last_entry_end_time:
                                current_time = last_entry_end_time
                            # Interpoler les coordonnées pour la distance actuelle
                            coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                            latitude = coords[0] if coords else None
                            longitude = coords[1] if coords else None
                            print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                            self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                            last_entry_end_time = end_time
                            current_time = end_time
                            total_on_duty_hours = 0
                            trip_state["last_duty_start_time"] = None
                            break
                    
                    end_time = current_time + timedelta(hours=MINIMUM_REST_HOURS)
                    if current_time < last_entry_end_time:
                        current_time = last_entry_end_time
                    # Interpoler les coordonnées pour la distance actuelle
                    coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                    latitude = coords[0] if coords else None
                    longitude = coords[1] if coords else None
                    print(f"Adding entry: SLEEPER_BERTH from {current_time} to {end_time} at {current_distance} miles")
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'SLEEPER_BERTH', "10h Rest after 11h Driving", current_distance, latitude, longitude)
                    last_entry_end_time = end_time
                    current_time = end_time
                    trip_state["last_duty_start_time"] = None
                    break

        if current_distance >= total_distance:
            if total_on_duty_hours + 1 > MAX_CYCLE_HOURS:
                if driving_buffer_minutes > 0:
                    buffer_end_time = current_time
                    if driving_buffer_start < last_entry_end_time:
                        driving_buffer_start = last_entry_end_time
                    # Interpoler les coordonnées pour la distance actuelle
                    coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                    latitude = coords[0] if coords else None
                    longitude = coords[1] if coords else None
                    print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                    self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', "Conduite", current_distance, latitude, longitude)
                    last_entry_end_time = buffer_end_time
                    driving_buffer_start = None
                    driving_buffer_minutes = 0

                end_time = current_time + timedelta(hours=RESTART_HOURS)
                if current_time < last_entry_end_time:
                    current_time = last_entry_end_time
                # Interpoler les coordonnées pour la distance actuelle
                coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                latitude = coords[0] if coords else None
                longitude = coords[1] if coords else None
                print(f"Adding entry: OFF_DUTY from {current_time} to {end_time} at {current_distance} miles")
                self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "34h Restart", current_distance, latitude, longitude)
                last_entry_end_time = end_time
                current_time = end_time
                total_on_duty_hours = 0
                trip_state["last_duty_start_time"] = None
            
            if trip_state["last_duty_start_time"]:
                time_in_window = (current_time - trip_state["last_duty_start_time"]).total_seconds() / 3600
                if time_in_window + 1 > MAX_DUTY_HOURS_PER_WINDOW:
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        if driving_buffer_start < last_entry_end_time:
                            driving_buffer_start = last_entry_end_time
                        # Interpoler les coordonnées pour la distance actuelle
                        coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                        latitude = coords[0] if coords else None
                        longitude = coords[1] if coords else None
                        print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', "Conduite", current_distance, latitude, longitude)
                        last_entry_end_time = buffer_end_time
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    end_time = current_time + timedelta(hours=MINIMUM_REST_HOURS)
                    if current_time < last_entry_end_time:
                        current_time = last_entry_end_time
                    # Interpoler les coordonnées pour la distance actuelle
                    coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                    latitude = coords[0] if coords else None
                    longitude = coords[1] if coords else None
                    print(f"Adding entry: SLEEPER_BERTH from {current_time} to {end_time} at {current_distance} miles")
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'SLEEPER_BERTH', "Repos de 10h avant dépôt", current_distance, latitude, longitude)
                    last_entry_end_time = end_time
                    current_time = end_time
                    trip_state["last_duty_start_time"] = None

            if driving_buffer_minutes > 0:
                buffer_end_time = current_time
                if driving_buffer_start < last_entry_end_time:
                    driving_buffer_start = last_entry_end_time
                # Interpoler les coordonnées pour la distance actuelle
                coords = self.interpolate_coords(all_coords, all_distances, current_distance)
                latitude = coords[0] if coords else None
                longitude = coords[1] if coords else None
                print(f"Adding entry: DRIVING from {driving_buffer_start} to {buffer_end_time} at {current_distance} miles")
                self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', "Conduite", current_distance, latitude, longitude)
                last_entry_end_time = buffer_end_time
                driving_buffer_start = None
                driving_buffer_minutes = 0

            dropoff_end_time = current_time + timedelta(hours=1)
            if current_time < last_entry_end_time:
                current_time = last_entry_end_time
            # Interpoler les coordonnées pour la distance actuelle
            coords = self.interpolate_coords(all_coords, all_distances, current_distance)
            latitude = coords[0] if coords else None
            longitude = coords[1] if coords else None
            print(f"Adding entry: ON_DUTY_NOT_DRIVING from {current_time} to {dropoff_end_time} at {current_distance} miles")
            self.add_log_entry(log_entries, trip, current_time, dropoff_end_time, 'ON_DUTY_NOT_DRIVING', f"Dropoff at {trip.dropoff_location}", current_distance, latitude, longitude)
            last_entry_end_time = dropoff_end_time
            total_on_duty_hours += 1

        # Trier les entrées par date et heure de début pour garantir un ordre chronologique
        log_entries.sort(key=lambda x: (x.date, x.start_time))
        LogEntry.objects.bulk_create(log_entries)


    def add_log_entry(self, log_entries, trip, start_time, end_time, duty_status, location, distance, latitude=None, longitude=None):
        if start_time >= end_time:
            return

        # S'assurer que start_time et end_time sont offset-aware
        if start_time.tzinfo is None:
            # Si start_time est offset-naive, utiliser le fuseau horaire par défaut (UTC)
            start_time = timezone.make_aware(start_time, timezone=timezone.utc)
        if end_time.tzinfo is None:
            # Si end_time est offset-naive, utiliser le fuseau horaire par défaut (UTC)
            end_time = timezone.make_aware(end_time, timezone=timezone.utc)

        location_with_distance = f"{location} ({distance:.1f} miles)"
        current_start = start_time

        while current_start < end_time:
            # Déterminer la fin de l'entrée actuelle (minuit ou end_time)
            next_midnight = datetime.combine(current_start.date() + timedelta(days=1), time.min, tzinfo=current_start.tzinfo)
            current_end = min(end_time, next_midnight)

            # Créer des datetime pour la nouvelle entrée, déjà offset-aware
            new_start_dt = datetime.combine(current_start.date(), current_start.time(), tzinfo=current_start.tzinfo)
            new_end_dt = datetime.combine(current_start.date(), current_end.time(), tzinfo=current_start.tzinfo)

            # Vérifier les chevauchements
            for entry in log_entries:
                if entry.date == current_start.date():
                    # Rendre les datetime des entrées existantes offset-aware en utilisant le même tzinfo
                    entry_start_dt = datetime.combine(entry.date, entry.start_time, tzinfo=current_start.tzinfo)
                    entry_end_dt = datetime.combine(entry.date, entry.end_time, tzinfo=current_start.tzinfo)
                    
                    # Vérifier que tous les datetimes sont offset-aware avant de les comparer
                    if new_start_dt.tzinfo is None:
                        new_start_dt = timezone.make_aware(new_start_dt, timezone=timezone.utc)
                    if new_end_dt.tzinfo is None:
                        new_end_dt = timezone.make_aware(new_end_dt, timezone=timezone.utc)
                    if entry_start_dt.tzinfo is None:
                        entry_start_dt = timezone.make_aware(entry_start_dt, timezone=timezone.utc)
                    if entry_end_dt.tzinfo is None:
                        entry_end_dt = timezone.make_aware(entry_end_dt, timezone=timezone.utc)
                        
                    if not (new_end_dt <= entry_start_dt or new_start_dt >= entry_end_dt):
                        print(f"Chevauchement détecté : {duty_status} ({new_start_dt} - {new_end_dt}) vs {entry.duty_status} ({entry_start_dt} - {entry_end_dt})")
                        return  # Ignorer l'ajout en cas de chevauchement
                    
            # Ajuster end_time uniquement pour la sauvegarde dans la base de données
            adjusted_end_time = current_end.time()
            if adjusted_end_time == time.min and current_end != end_time:
                adjusted_end_time = time(23, 59, 59, 999999)

            log_entries.append(LogEntry(
                trip=trip,
                date=current_start.date(),
                duty_status=duty_status,
                start_time=current_start.time(),
                end_time=adjusted_end_time,
                location=location_with_distance,
                latitude=latitude,
                longitude=longitude
            ))

            current_start = current_end

    
class TripDetailView(generics.RetrieveAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer