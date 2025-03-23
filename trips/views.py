import os
from datetime import datetime, timedelta, time
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from dotenv import load_dotenv
from .models import Trip, LogEntry
from .serializers import TripSerializer

load_dotenv()

# HOS Constants
AVERAGE_SPEED = 60  # We assume an average speed of 60 mph
MAX_DRIVING_HOURS_PER_WINDOW = 11
MAX_DUTY_HOURS_PER_WINDOW = 14
MAX_DRIVING_HOURS_BEFORE_BREAK = 8
MAX_CYCLE_HOURS = 70
FUELING_INTERVAL = 1000
MINIMUM_REST_HOURS = 10
RESTART_HOURS = 34

class TripCreateView(generics.CreateAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer

    def perform_create(self, serializer):
        current_location = self.request.data.get('current_location')
        pickup_location = self.request.data.get('pickup_location')
        dropoff_location = self.request.data.get('dropoff_location')
        current_cycle_hours = float(self.request.data.get('current_cycle_hours', 0))
        start_time = self.request.data.get('start_time')

        # Validating the inputs
        if not all([current_location, pickup_location, dropoff_location]):
            raise ValueError("All location fields are required.")
        if not 0 <= current_cycle_hours <= MAX_CYCLE_HOURS:
            raise ValueError(f"current_cycle_hours must be between 0 and {MAX_CYCLE_HOURS}.")

        start_time = (datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                      if start_time else timezone.now())

        # Calculate distances (returns two values: distance to pickup and distance to dropoff)
        distance_to_pickup, distance_to_dropoff = self.calculate_distance(
            current_location, pickup_location, dropoff_location
        )
        total_distance = distance_to_pickup + distance_to_dropoff
        estimated_duration = total_distance / AVERAGE_SPEED

        # Save the trip
        trip = serializer.save(
            distance=total_distance,
            estimated_duration=estimated_duration,
            current_cycle_hours=current_cycle_hours,
            start_time=start_time,
            current_location=current_location,
            pickup_location=pickup_location,
            dropoff_location=dropoff_location
        )

        # Generate ELD logs
        self.generate_eld_logs(trip, distance_to_pickup, distance_to_dropoff, current_cycle_hours)

    def calculate_distance(self, current_location, pickup_location, dropoff_location):
        # TODO: Replace with a real API call 
        # For now, simulating distances based on locations
        distance_to_pickup = 0 if current_location == pickup_location else 200  
        distance_to_dropoff = 1200 if dropoff_location == "Denver, CO" else 2800
        return distance_to_pickup, distance_to_dropoff

    def generate_eld_logs(self, trip, distance_to_pickup, distance_to_dropoff, current_cycle_hours):
        current_time = trip.start_time
        current_distance = 0
        total_on_duty_hours = current_cycle_hours
        fueling_stops_made = set()
        log_entries = []

        # Local state for this trip
        trip_state = {
            "last_duty_start_time": None,
        }

        # Buffer for accumulating driving minutes before logging
        driving_buffer_start = None
        driving_buffer_minutes = 0

        # Total distance to cover (including both segments)
        total_distance = distance_to_pickup + distance_to_dropoff

        # Flag to track if we are in the initial driving phase (Current location to Pickup location)
        in_initial_driving_phase = distance_to_pickup > 0
        pickup_completed = False

        # Step 1: Simulation of the trip (including initial driving phase)
        while current_distance < total_distance:
            # Here we add a new window of 14 hours if necessary
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
                        location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                    else "Conduite")
                        # Ajouter la distance cumulée au log
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    end_time = current_time + timedelta(hours=MINIMUM_REST_HOURS)
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'SLEEPER_BERTH', "Repos de 10h après 14h de service", current_distance)
                    current_time = end_time
                    trip_state["last_duty_start_time"] = None
                    break

                # Let's check the cycle of 70 hours before any other action
                remaining_cycle_hours = MAX_CYCLE_HOURS - total_on_duty_hours
                if remaining_cycle_hours <= 0:
                    # Let's save the buffer if it exists
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                    else "Conduite")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    end_time = current_time + timedelta(hours=RESTART_HOURS)
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                    current_time = end_time
                    total_on_duty_hours = 0
                    trip_state["last_duty_start_time"] = None
                    break

                # If we are in the initial driving phase and we have reached the distance of pickup
                if in_initial_driving_phase and current_distance >= distance_to_pickup and not pickup_completed:
                    # Saving the buffer if it exists
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', f"Conduite de {trip.current_location} à {trip.pickup_location}", current_distance)
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    # Pickup (1h in service, no driving)
                    pickup_end_time = current_time + timedelta(hours=1)
                    self.add_log_entry(log_entries, trip, current_time, pickup_end_time, 'ON_DUTY_NOT_DRIVING', f"Ramassage à {trip.pickup_location}", current_distance)
                    current_time = pickup_end_time
                    total_on_duty_hours += 1
                    pickup_completed = True
                    in_initial_driving_phase = False

                    # Let's check the cycle after pickup
                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break

                    # We need to check if the window of 14 hours is exceeded after pickup
                    time_in_window = (current_time - window_start).total_seconds() / 3600
                    if time_in_window >= MAX_DUTY_HOURS_PER_WINDOW:
                        end_time = current_time + timedelta(hours=MINIMUM_REST_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'SLEEPER_BERTH', "Repos de 10h après 14h de service", current_distance)
                        current_time = end_time
                        trip_state["last_duty_start_time"] = None
                        break

                    continue

                # Pause of 30 minutes after 8 hours of driving
                if driving_since_last_break >= MAX_DRIVING_HOURS_BEFORE_BREAK:
                    # Saving driving buffer if it exists
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                    else "Conduite")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    end_time = current_time + timedelta(minutes=30)
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Pause de 30 minutes", current_distance)
                    current_time = end_time
                    driving_since_last_break = 0
                    total_on_duty_hours += 0.5
                    
                    # Verifying the cycle after the break
                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break
                    
                    continue

                # Arrêt de ravitaillement tous les 1000 miles
                next_fueling_mile = (int(current_distance // FUELING_INTERVAL) + 1) * FUELING_INTERVAL
                if next_fueling_mile not in fueling_stops_made and current_distance + (AVERAGE_SPEED / 60) >= next_fueling_mile:
                    minutes_to_fuel = (next_fueling_mile - current_distance) / (AVERAGE_SPEED / 60)
                    hours_to_fuel = minutes_to_fuel / 60
                    
                    # Vérifier si on a suffisamment d'heures dans le cycle
                    if total_on_duty_hours + hours_to_fuel >= MAX_CYCLE_HOURS:
                        minutes_to_cycle_limit = (MAX_CYCLE_HOURS - total_on_duty_hours) * 60
                        if minutes_to_cycle_limit <= 0:
                            # Enregistrer le buffer de conduite s'il existe
                            if driving_buffer_minutes > 0:
                                buffer_end_time = current_time
                                location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                            else "Conduite")
                                self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                                driving_buffer_start = None
                                driving_buffer_minutes = 0

                            end_time = current_time + timedelta(hours=RESTART_HOURS)
                            self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                            current_time = end_time
                            total_on_duty_hours = 0
                            trip_state["last_duty_start_time"] = None
                            break
                        
                        # Conduite jusqu'à la limite du cycle
                        if driving_buffer_minutes > 0:
                            buffer_end_time = current_time
                            location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                        else "Conduite")
                            self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                            driving_buffer_start = None
                            driving_buffer_minutes = 0
                            
                        cycle_limit_time = current_time + timedelta(minutes=minutes_to_cycle_limit)
                        location = (f"Conduite de {trip.current_location} à {trip.pickup_location} jusqu'à limite du cycle" if in_initial_driving_phase
                                    else "Conduite jusqu'à limite du cycle")
                        self.add_log_entry(log_entries, trip, current_time, cycle_limit_time, 'DRIVING', location, current_distance)
                        current_time = cycle_limit_time
                        current_distance += minutes_to_cycle_limit * (AVERAGE_SPEED / 60)
                        window_driving_hours += minutes_to_cycle_limit / 60
                        driving_since_last_break += minutes_to_cycle_limit / 60
                        total_on_duty_hours = MAX_CYCLE_HOURS
                        
                        # Redémarrage du cycle
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break
                    
                    if window_driving_hours + hours_to_fuel > MAX_DRIVING_HOURS_PER_WINDOW:
                        hours_to_fuel = MAX_DRIVING_HOURS_PER_WINDOW - window_driving_hours
                        minutes_to_fuel = hours_to_fuel * 60

                    # Vérifier si on dépasse les 8 heures de conduite avant le ravitaillement
                    if driving_since_last_break + (minutes_to_fuel / 60) > MAX_DRIVING_HOURS_BEFORE_BREAK:
                        minutes_to_break = (MAX_DRIVING_HOURS_BEFORE_BREAK - driving_since_last_break) * 60
                        hours_to_break = minutes_to_break / 60
                        end_time = current_time + timedelta(minutes=minutes_to_break)
                        
                        # Enregistrer le buffer de conduite jusqu'à la pause
                        if driving_buffer_minutes > 0:
                            buffer_end_time = current_time
                            location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                        else "Conduite")
                            self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                            driving_buffer_start = None
                            driving_buffer_minutes = 0

                        location = (f"Conduite de {trip.current_location} à {trip.pickup_location} jusqu'à la pause" if in_initial_driving_phase
                                    else "Conduite jusqu'à la pause")
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'DRIVING', location, current_distance)
                        current_time = end_time
                        current_distance += minutes_to_break * (AVERAGE_SPEED / 60)
                        window_driving_hours += hours_to_break
                        driving_since_last_break += hours_to_break
                        total_on_duty_hours += hours_to_break
                        
                        # Vérification du cycle après cette période de conduite
                        if total_on_duty_hours >= MAX_CYCLE_HOURS:
                            end_time = current_time + timedelta(hours=RESTART_HOURS)
                            self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                            current_time = end_time
                            total_on_duty_hours = 0
                            trip_state["last_duty_start_time"] = None
                            break

                        # Pause de 30 minutes
                        end_time = current_time + timedelta(minutes=30)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Pause de 30 minutes", current_distance)
                        current_time = end_time
                        driving_since_last_break = 0
                        total_on_duty_hours += 0.5
                        
                        # Vérification du cycle après la pause
                        if total_on_duty_hours >= MAX_CYCLE_HOURS:
                            end_time = current_time + timedelta(hours=RESTART_HOURS)
                            self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                            current_time = end_time
                            total_on_duty_hours = 0
                            trip_state["last_duty_start_time"] = None
                            break
                            
                        continue

                    # Conduite jusqu'au ravitaillement
                    end_time = current_time + timedelta(minutes=minutes_to_fuel)
                    
                    # Enregistrer le buffer de conduite jusqu'au ravitaillement
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                    else "Conduite")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    location = (f"Conduite de {trip.current_location} à {trip.pickup_location} jusqu'au ravitaillement" if in_initial_driving_phase
                                else "Conduite jusqu'au ravitaillement")
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'DRIVING', location, current_distance)
                    current_time = end_time
                    current_distance += minutes_to_fuel * (AVERAGE_SPEED / 60)
                    window_driving_hours += hours_to_fuel
                    driving_since_last_break += hours_to_fuel
                    total_on_duty_hours += hours_to_fuel
                    
                    # Vérification du cycle après cette période de conduite
                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break

                    fueling_stops_made.add(next_fueling_mile)
                    # Changement : Réduire l'arrêt de ravitaillement à 15 minutes
                    end_time = current_time + timedelta(minutes=15)
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'ON_DUTY_NOT_DRIVING', "Arrêt de ravitaillement", current_distance)
                    current_time = end_time
                    # Changement : Ajuster le temps en service (15 minutes = 0.25 heure)
                    total_on_duty_hours += 0.25
                    
                    # Vérification du cycle après le ravitaillement
                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break

                    # Réinitialiser le buffer après le ravitaillement
                    driving_buffer_start = None
                    driving_buffer_minutes = 0
                    continue

                # Conduite normale (par minute)
                remaining_minutes = min(
                    (MAX_DRIVING_HOURS_PER_WINDOW - window_driving_hours) * 60,
                    (MAX_DUTY_HOURS_PER_WINDOW - time_in_window) * 60,
                    (total_distance - current_distance) / (AVERAGE_SPEED / 60),
                    (MAX_CYCLE_HOURS - total_on_duty_hours) * 60
                )
                
                if remaining_minutes <= 0:
                    break

                # Avancer d'une minute
                end_time = current_time + timedelta(minutes=1)
                current_distance += AVERAGE_SPEED / 60  # Distance parcourue en 1 minute
                window_driving_hours += 1 / 60  # 1 minute de conduite
                driving_since_last_break += 1 / 60
                total_on_duty_hours += 1 / 60

                # Vérification du cycle après chaque minute
                if total_on_duty_hours >= MAX_CYCLE_HOURS:
                    # Arrondir pour éviter les erreurs de précision flottante
                    if round(total_on_duty_hours, 2) >= MAX_CYCLE_HOURS:
                        # Enregistrer le buffer de conduite s'il existe
                        if driving_buffer_minutes > 0:
                            buffer_end_time = current_time + timedelta(minutes=1)
                            location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                        else "Conduite")
                            self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                            driving_buffer_start = None
                            driving_buffer_minutes = 0

                        end_time = current_time + timedelta(minutes=1) + timedelta(hours=RESTART_HOURS)
                        self.add_log_entry(log_entries, trip, current_time + timedelta(minutes=1), end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break

                # Gestion du buffer de conduite
                if driving_buffer_start is None:
                    driving_buffer_start = current_time
                driving_buffer_minutes += 1

                # Si le buffer atteint 1 heure (60 minutes), enregistrer le log
                if driving_buffer_minutes >= 60:
                    buffer_end_time = current_time + timedelta(minutes=1)
                    location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                else "Conduite")
                    self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                    driving_buffer_start = buffer_end_time
                    driving_buffer_minutes = 0

                current_time = end_time

                if window_driving_hours >= MAX_DRIVING_HOURS_PER_WINDOW:
                    # Enregistrer le buffer de conduite s'il existe
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                    else "Conduite")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    time_to_window_end = MAX_DUTY_HOURS_PER_WINDOW - (current_time - window_start).total_seconds() / 3600
                    if time_to_window_end > 0:
                        end_time = current_time + timedelta(hours=time_to_window_end)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'ON_DUTY_NOT_DRIVING', "Fin de fenêtre de 14h", current_distance)
                        current_time = end_time
                        total_on_duty_hours += time_to_window_end
                        
                        # Vérification du cycle après cette période de service
                        if total_on_duty_hours >= MAX_CYCLE_HOURS:
                            end_time = current_time + timedelta(hours=RESTART_HOURS)
                            self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                            current_time = end_time
                            total_on_duty_hours = 0
                            trip_state["last_duty_start_time"] = None
                            break
                    
                    end_time = current_time + timedelta(hours=MINIMUM_REST_HOURS)
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'SLEEPER_BERTH', "Repos de 10h après 11h de conduite", current_distance)
                    current_time = end_time
                    trip_state["last_duty_start_time"] = None
                    break

        # Étape 2 : Dépôt (1h en service, pas de conduite)
        if current_distance >= total_distance:
            # Vérification du cycle de 70 heures avant le dépôt
            if total_on_duty_hours + 1 > MAX_CYCLE_HOURS:
                # Enregistrer le buffer de conduite s'il existe
                if driving_buffer_minutes > 0:
                    buffer_end_time = current_time
                    self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', "Conduite", current_distance)
                    driving_buffer_start = None
                    driving_buffer_minutes = 0

                end_time = current_time + timedelta(hours=RESTART_HOURS)
                self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                current_time = end_time
                total_on_duty_hours = 0
                trip_state["last_duty_start_time"] = None
            
            # Vérification de la fenêtre de 14 heures
            if trip_state["last_duty_start_time"]:
                time_in_window = (current_time - trip_state["last_duty_start_time"]).total_seconds() / 3600
                if time_in_window + 1 > MAX_DUTY_HOURS_PER_WINDOW:
                    # Enregistrer le buffer de conduite s'il existe
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', "Conduite", current_distance)
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    end_time = current_time + timedelta(hours=MINIMUM_REST_HOURS)
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'SLEEPER_BERTH', "Repos de 10h avant dépôt", current_distance)
                    current_time = end_time
                    trip_state["last_duty_start_time"] = None

            # Enregistrer le buffer de conduite restant avant le dépôt
            if driving_buffer_minutes > 0:
                buffer_end_time = current_time
                self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', "Conduite", current_distance)
                driving_buffer_start = None
                driving_buffer_minutes = 0

            dropoff_end_time = current_time + timedelta(hours=1)
            self.add_log_entry(log_entries, trip, current_time, dropoff_end_time, 'ON_DUTY_NOT_DRIVING', f"Dépôt à {trip.dropoff_location}", current_distance)
            total_on_duty_hours += 1

        # Sauvegarde des logs
        LogEntry.objects.bulk_create(log_entries)

    def add_log_entry(self, log_entries, trip, start_time, end_time, duty_status, location, distance):
        """Ajoute une entrée de log, gérant les cas où elle traverse minuit, et inclut la distance cumulée."""
        if start_time >= end_time:
            return

        # Ajouter la distance cumulée à la description de la localisation
        location_with_distance = f"{location} ({distance:.1f} miles)"

        if start_time.date() == end_time.date():
            log_entries.append(LogEntry(
                trip=trip,
                date=start_time.date(),
                duty_status=duty_status,
                start_time=start_time.time(),
                end_time=end_time.time(),
                location=location_with_distance
            ))
        else:
            midnight = datetime.combine(start_time.date() + timedelta(days=1), time.min, tzinfo=start_time.tzinfo)
            log_entries.append(LogEntry(
                trip=trip,
                date=start_time.date(),
                duty_status=duty_status,
                start_time=start_time.time(),
                end_time=time(23, 59, 59),
                location=location_with_distance
            ))
            
            # Gestion des logs pour les jours intermédiaires si nécessaire
            current_date = start_time.date() + timedelta(days=1)
            while current_date < end_time.date():
                log_entries.append(LogEntry(
                    trip=trip,
                    date=current_date,
                    duty_status=duty_status,
                    start_time=time(0, 0, 0),
                    end_time=time(23, 59, 59),
                    location=location_with_distance
                ))
                current_date += timedelta(days=1)
                
            log_entries.append(LogEntry(
                trip=trip,
                date=end_time.date(),
                duty_status=duty_status,
                start_time=time(0, 0, 0),
                end_time=end_time.time(),
                location=location_with_distance
            ))

class TripDetailView(generics.RetrieveAPIView):
    """Vue pour récupérer les détails d'un voyage."""
    queryset = Trip.objects.all()
    serializer_class = TripSerializer