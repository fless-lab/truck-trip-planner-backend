from django.urls import path
from .views import TripCreateView, TripDetailView, TripListView

urlpatterns = [
    path('trips/', TripListView.as_view(), name='trip-list'),
    path('trips/create/', TripCreateView.as_view(), name='trip-create'),
    path('trips/<int:pk>/', TripDetailView.as_view(), name='trip-detail'),
]