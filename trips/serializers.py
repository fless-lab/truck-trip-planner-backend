from rest_framework import serializers
from .models import Trip, LogEntry
from datetime import datetime, timedelta

class LogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LogEntry
        fields = ['date', 'duty_status', 'start_time', 'end_time', 'location', 'latitude', 'longitude']

class TripSerializer(serializers.ModelSerializer):
    logs = LogEntrySerializer(many=True, read_only=True)
    summary = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = [
            'id', 'current_location', 'pickup_location', 'dropoff_location',
            'current_cycle_hours', 'start_time', 'distance', 'estimated_duration',
            'logs', 'summary'
        ]

    def get_summary(self, obj):

        logs = obj.logs.all().order_by('date', 'start_time')
        if not logs:
            return []


        timeline = []
        current_period = None

        for log in logs:
    
            start_datetime = datetime.combine(log.date, log.start_time, tzinfo=obj.start_time.tzinfo)
            end_datetime = datetime.combine(log.date, log.end_time, tzinfo=obj.start_time.tzinfo)
            if end_datetime < start_datetime:
                end_datetime += timedelta(days=1)

    
            try:
                distance_str = log.location.split('(')[-1].replace(' miles)', '')
                distance = float(distance_str)
            except (IndexError, ValueError):
                distance = 0.0

    
            if not current_period or current_period['duty_status'] != log.duty_status or current_period['end'] != start_datetime:
                if current_period:
            
                    start_str = current_period['start'].strftime('%Hh%M').replace('h00', 'h')
                    end_str = current_period['end'].strftime('%Hh%M').replace('h00', 'h')
                    timeline.append({
                        "duty_status": current_period['duty_status'],
                        "start_time": start_str,
                        "end_time": end_str,
                        "distance": current_period['distance']
                    })

        
                current_period = {
                    'duty_status': log.duty_status,
                    'start': start_datetime,
                    'end': end_datetime,
                    'distance': distance
                }
            else:
        
                current_period['end'] = end_datetime
                current_period['distance'] = distance


        if current_period:
            start_str = current_period['start'].strftime('%Hh%M').replace('h00', 'h')
            end_str = current_period['end'].strftime('%Hh%M').replace('h00', 'h')
            timeline.append({
                "duty_status": current_period['duty_status'],
                "start_time": start_str,
                "end_time": end_str,
                "distance": current_period['distance']
            })

        return timeline