from rest_framework import serializers
from .models import Trip, LogEntry

class LogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LogEntry
        fields = ['date', 'duty_status', 'start_time', 'end_time', 'location']

class TripSerializer(serializers.ModelSerializer):
    logs = LogEntrySerializer(many=True, read_only=True)

    class Meta:
        model = Trip
        fields = ['id', 'current_location', 'pickup_location', 'dropoff_location', 'current_cycle_hours', 'start_time', 'distance', 'estimated_duration', 'logs']