import requests
from datetime import datetime, timedelta, time
from django.utils import timezone
from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status
from .models import Trip, LogEntry
from .serializers import TripSerializer
import os
from dotenv import load_dotenv

load_dotenv()

# Let's suppose the average speed is 60 mph
AVERAGE_SPEED = 60  # 60 mph

class TripCreateView(generics.CreateAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer

    def perform_create(self, serializer):
        # Here we retrieve the trip data from the request
        current_location = self.request.data.get('current_location')
        pickup_location = self.request.data.get('pickup_location')
        dropoff_location = self.request.data.get('dropoff_location')
        current_cycle_hours = float(self.request.data.get('current_cycle_hours', 0))

        # Calculate the distance and estimated duration (simulated here, We will replace it later with a real API call)
        distance = self.calculate_distance(current_location, pickup_location, dropoff_location)
        estimated_duration = distance / AVERAGE_SPEED  # Time in hours

        # Save the trip with the calculated distance and estimated duration
        trip = serializer.save(
            distance=distance,
            estimated_duration=estimated_duration,
            current_cycle_hours=current_cycle_hours
        )

        # Générer les logs ELD en appliquant les règles HOS
        self.generate_eld_logs(trip, distance, estimated_duration, current_cycle_hours)

    def calculate_distance(self, current_location, pickup_location, dropoff_location):
        # Example : New York to Los Angeles via pickup point
        return 2800

    def generate_eld_logs(self, trip, distance, estimated_duration, current_cycle_hours):
        # Starting hour (Here we suppose the trip is starting now)
        current_time = trip.start_time
        total_driving_hours = 0
        total_on_duty_hours = current_cycle_hours
        current_distance = 0
        day = current_time.date()

        # Simulate the trip hour by hour
        while current_distance < distance:
            # Verifying the 70 hour limit
            if total_on_duty_hours >= 70:
                # Inserting a 34 hour restart
                self.add_log_entry(trip, day, 'OFF_DUTY', current_time.time(), (current_time + timedelta(hours=34)).time(), "34-hour restart")
                current_time += timedelta(hours=34)
                total_on_duty_hours = 0
                day = current_time.date()
                continue

            # 14 hour window
            window_start = current_time
            window_driving_hours = 0
            window_on_duty_hours = 0

            while window_driving_hours < 11 and window_on_duty_hours < 14 and current_distance < distance:
                # Lets check the 30 minute break after 8 hours of driving
                if window_driving_hours >= 8:
                    self.add_log_entry(trip, day, 'OFF_DUTY', current_time.time(), (current_time + timedelta(minutes=30)).time(), "Mandatory 30-minute break")
                    current_time += timedelta(minutes=30)
                    window_on_duty_hours += 0.5
                    total_on_duty_hours += 0.5
                    if current_time.date() != day:
                        day = current_time.date()
                    continue

                # Checking fueling stops (every 1000 miles)
                if current_distance > 0 and current_distance % 1000 <= (AVERAGE_SPEED / 2):
                    self.add_log_entry(trip, day, 'ON_DUTY_NOT_DRIVING', current_time.time(), (current_time + timedelta(minutes=30)).time(), "Fueling stop")
                    current_time += timedelta(minutes=30)
                    window_on_duty_hours += 0.5
                    total_on_duty_hours += 0.5
                    if current_time.date() != day:
                        day = current_time.date()
                    continue

                # Drive for 1 hour (or until the end of the trip)
                hours_to_drive = min(1, (distance - current_distance) / AVERAGE_SPEED)
                self.add_log_entry(trip, day, 'DRIVING', current_time.time(), (current_time + timedelta(hours=hours_to_drive)).time(), "Driving")
                current_time += timedelta(hours=hours_to_drive)
                current_distance += hours_to_drive * AVERAGE_SPEED
                window_driving_hours += hours_to_drive
                window_on_duty_hours += hours_to_drive
                total_on_duty_hours += hours_to_drive
                total_driving_hours += hours_to_drive
                if current_time.date() != day:
                    day = current_time.date()

            # End of the 14 hour window : We will insert a rest
            if current_distance < distance:
                # Using the sleeper berth provision : 7 hours in the sleeper berth + 2 hours off duty
                self.add_log_entry(trip, day, 'SLEEPER_BERTH', current_time.time(), (current_time + timedelta(hours=7)).time(), "Sleeper berth rest")
                current_time += timedelta(hours=7)
                if current_time.date() != day:
                    day = current_time.date()
                self.add_log_entry(trip, day, 'OFF_DUTY', current_time.time(), (current_time + timedelta(hours=2)).time(), "Off duty rest")
                current_time += timedelta(hours=2)
                if current_time.date() != day:
                    day = current_time.date()

        #  Adding the pickup and dropoff
        self.add_log_entry(trip, trip.start_time.date(), 'ON_DUTY_NOT_DRIVING', trip.start_time.time(), (trip.start_time + timedelta(hours=1)).time(), f"Pickup at {trip.pickup_location}")
        self.add_log_entry(trip, day, 'ON_DUTY_NOT_DRIVING', current_time.time(), (current_time + timedelta(hours=1)).time(), f"Dropoff at {trip.dropoff_location}")

    def add_log_entry(self, trip, date, status, start_time, end_time, location):
        LogEntry.objects.create(
            trip=trip,
            date=date,
            duty_status=status,
            start_time=start_time,
            end_time=end_time,
            location=location
        )

class TripDetailView(generics.RetrieveAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer