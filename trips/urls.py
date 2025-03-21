from django.urls import path
from . import views

urlpatterns = [
    path('trips/', views.TripCreateView.as_view(), name='trip-create'),  # Create a trip
    path('trips/<int:pk>/', views.TripDetailView.as_view(), name='trip-detail'),  # Retrieve a trip
]