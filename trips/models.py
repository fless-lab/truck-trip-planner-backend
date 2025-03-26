from django.db import models
from django.utils import timezone

class Trip(models.Model):
    current_location = models.CharField(max_length=255)
    pickup_location = models.CharField(max_length=255)
    dropoff_location = models.CharField(max_length=255)
    current_cycle_hours = models.FloatField() # Estimated number of hours spent in the current location
    start_time = models.DateTimeField(default=timezone.now)  # Trip start time
    distance = models.FloatField(null=True, blank=True)  # Total distance traveled in miles
    estimated_duration = models.FloatField(null=True, blank=True)  # Estimated duration in hours
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Trip from {self.current_location} to {self.dropoff_location}"

class LogEntry(models.Model):
    STATUS_CHOICES = [
        ('OFF_DUTY', 'Off Duty'),
        ('SLEEPER_BERTH', 'Sleeper Berth'),
        ('DRIVING', 'Driving'),
        ('ON_DUTY_NOT_DRIVING', 'On Duty Not Driving'),
    ]

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='logs')
    date = models.DateField()
    duty_status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    location = models.CharField(max_length=255)
    # To track driver status positions (for map visualization)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"{self.duty_status} on {self.date} from {self.start_time} to {self.end_time}"