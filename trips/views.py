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
AVERAGE_SPEED = 60 #Here we suppose the 
MAX_DRIVING_HOURS_PER_WINDOW = 11
MAX_DUTY_HOURS_PER_WINDOW = 14
MAX_DRIVING_HOURS_BEFORE_BREAK = 8
MAX_CYCLE_HOURS = 70
FUELING_INTERVAL = 1000
MINIMUM_REST_HOURS = 10
RESTART_HOURS = 34

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
        estimated_duration = total_distance / AVERAGE_SPEED

        trip = serializer.save(
            distance=total_distance,
            estimated_duration=estimated_duration,
            current_cycle_hours=current_cycle_hours,
            start_time=start_time,
            current_location=current_location,
            pickup_location=pickup_location,
            dropoff_location=dropoff_location
        )

        self.generate_eld_logs(trip, distance_to_pickup, distance_to_dropoff, current_cycle_hours)

    def calculate_distance(self, current_location, pickup_location, dropoff_location):
        distance_to_pickup = 0 if current_location == pickup_location else 200
        distance_to_dropoff = 1200 if dropoff_location == "Denver, CO" else 2800
        return distance_to_pickup, distance_to_dropoff

    def generate_eld_logs(self, trip, distance_to_pickup, distance_to_dropoff, current_cycle_hours):
        current_time = trip.start_time
        current_distance = 0
        total_on_duty_hours = current_cycle_hours
        fueling_stops_made = set()
        log_entries = []

        trip_state = {"last_duty_start_time": None}
        driving_buffer_start = None
        driving_buffer_minutes = 0

        total_distance = distance_to_pickup + distance_to_dropoff
        in_initial_driving_phase = distance_to_pickup > 0
        pickup_completed = False

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
                        location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                    else "Conduite")
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    end_time = current_time + timedelta(hours=MINIMUM_REST_HOURS)
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'SLEEPER_BERTH', "Repos de 10h après 14h de service", current_distance)
                    current_time = end_time
                    trip_state["last_duty_start_time"] = None
                    break

                remaining_cycle_hours = MAX_CYCLE_HOURS - total_on_duty_hours
                if remaining_cycle_hours <= 0:
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

                if in_initial_driving_phase and current_distance >= distance_to_pickup and not pickup_completed:
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', f"Conduite de {trip.current_location} à {trip.pickup_location}", current_distance)
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    pickup_end_time = current_time + timedelta(hours=1)
                    self.add_log_entry(log_entries, trip, current_time, pickup_end_time, 'ON_DUTY_NOT_DRIVING', f"Ramassage à {trip.pickup_location}", current_distance)
                    current_time = pickup_end_time
                    total_on_duty_hours += 1
                    pickup_completed = True
                    in_initial_driving_phase = False

                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break

                    time_in_window = (current_time - window_start).total_seconds() / 3600
                    if time_in_window >= MAX_DUTY_HOURS_PER_WINDOW:
                        end_time = current_time + timedelta(hours=MINIMUM_REST_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'SLEEPER_BERTH', "Repos de 10h après 14h de service", current_distance)
                        current_time = end_time
                        trip_state["last_duty_start_time"] = None
                        break

                    continue

                if driving_since_last_break >= MAX_DRIVING_HOURS_BEFORE_BREAK:
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
                    
                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break
                    
                    continue

                next_fueling_mile = (int(current_distance // FUELING_INTERVAL) + 1) * FUELING_INTERVAL
                if next_fueling_mile not in fueling_stops_made and current_distance + (AVERAGE_SPEED / 60) >= next_fueling_mile:
                    minutes_to_fuel = (next_fueling_mile - current_distance) / (AVERAGE_SPEED / 60)
                    hours_to_fuel = minutes_to_fuel / 60
                    
                    if total_on_duty_hours + hours_to_fuel >= MAX_CYCLE_HOURS:
                        minutes_to_cycle_limit = (MAX_CYCLE_HOURS - total_on_duty_hours) * 60
                        if minutes_to_cycle_limit <= 0:
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
                        
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
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
                        
                        if total_on_duty_hours >= MAX_CYCLE_HOURS:
                            end_time = current_time + timedelta(hours=RESTART_HOURS)
                            self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                            current_time = end_time
                            total_on_duty_hours = 0
                            trip_state["last_duty_start_time"] = None
                            break

                        end_time = current_time + timedelta(minutes=30)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Pause de 30 minutes", current_distance)
                        current_time = end_time
                        driving_since_last_break = 0
                        total_on_duty_hours += 0.5
                        
                        if total_on_duty_hours >= MAX_CYCLE_HOURS:
                            end_time = current_time + timedelta(hours=RESTART_HOURS)
                            self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                            current_time = end_time
                            total_on_duty_hours = 0
                            trip_state["last_duty_start_time"] = None
                            break
                            
                        continue

                    end_time = current_time + timedelta(minutes=minutes_to_fuel)
                    
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
                    
                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break

                    fueling_stops_made.add(next_fueling_mile)
                    end_time = current_time + timedelta(minutes=15)
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'ON_DUTY_NOT_DRIVING', "Arrêt de ravitaillement", current_distance)
                    current_time = end_time
                    total_on_duty_hours += 0.25
                    
                    if total_on_duty_hours >= MAX_CYCLE_HOURS:
                        end_time = current_time + timedelta(hours=RESTART_HOURS)
                        self.add_log_entry(log_entries, trip, current_time, end_time, 'OFF_DUTY', "Redémarrage de 34 heures", current_distance)
                        current_time = end_time
                        total_on_duty_hours = 0
                        trip_state["last_duty_start_time"] = None
                        break

                    driving_buffer_start = None
                    driving_buffer_minutes = 0
                    continue

                remaining_minutes = min(
                    (MAX_DRIVING_HOURS_PER_WINDOW - window_driving_hours) * 60,
                    (MAX_DUTY_HOURS_PER_WINDOW - time_in_window) * 60,
                    (total_distance - current_distance) / (AVERAGE_SPEED / 60),
                    (MAX_CYCLE_HOURS - total_on_duty_hours) * 60
                )
                
                if remaining_minutes <= 0:
                    break

                end_time = current_time + timedelta(minutes=1)
                current_distance += AVERAGE_SPEED / 60
                window_driving_hours += 1 / 60
                driving_since_last_break += 1 / 60
                total_on_duty_hours += 1 / 60

                if total_on_duty_hours >= MAX_CYCLE_HOURS:
                    if round(total_on_duty_hours, 2) >= MAX_CYCLE_HOURS:
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

                if driving_buffer_start is None:
                    driving_buffer_start = current_time
                driving_buffer_minutes += 1

                if driving_buffer_minutes >= 60:
                    buffer_end_time = current_time + timedelta(minutes=1)
                    location = (f"Conduite de {trip.current_location} à {trip.pickup_location}" if in_initial_driving_phase
                                else "Conduite")
                    self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', location, current_distance)
                    driving_buffer_start = buffer_end_time
                    driving_buffer_minutes = 0

                current_time = end_time

                if window_driving_hours >= MAX_DRIVING_HOURS_PER_WINDOW:
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

        if current_distance >= total_distance:
            if total_on_duty_hours + 1 > MAX_CYCLE_HOURS:
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
            
            if trip_state["last_duty_start_time"]:
                time_in_window = (current_time - trip_state["last_duty_start_time"]).total_seconds() / 3600
                if time_in_window + 1 > MAX_DUTY_HOURS_PER_WINDOW:
                    if driving_buffer_minutes > 0:
                        buffer_end_time = current_time
                        self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', "Conduite", current_distance)
                        driving_buffer_start = None
                        driving_buffer_minutes = 0

                    end_time = current_time + timedelta(hours=MINIMUM_REST_HOURS)
                    self.add_log_entry(log_entries, trip, current_time, end_time, 'SLEEPER_BERTH', "Repos de 10h avant dépôt", current_distance)
                    current_time = end_time
                    trip_state["last_duty_start_time"] = None

            if driving_buffer_minutes > 0:
                buffer_end_time = current_time
                self.add_log_entry(log_entries, trip, driving_buffer_start, buffer_end_time, 'DRIVING', "Conduite", current_distance)
                driving_buffer_start = None
                driving_buffer_minutes = 0

            dropoff_end_time = current_time + timedelta(hours=1)
            self.add_log_entry(log_entries, trip, current_time, dropoff_end_time, 'ON_DUTY_NOT_DRIVING', f"Dépôt à {trip.dropoff_location}", current_distance)
            total_on_duty_hours += 1

        LogEntry.objects.bulk_create(log_entries)

    def add_log_entry(self, log_entries, trip, start_time, end_time, duty_status, location, distance):
        if start_time >= end_time:
            return

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
    queryset = Trip.objects.all()
    serializer_class = TripSerializer