# TRUCK TRIP PLANNER (BACKEND)

## Description

This is a simple web application (MVP) that allows users to plan their truck trips. It uses a database to store the trips and provides an API for the frontend to interact with the backend. The application is designed for property-carrying truck drivers and ensures compliance with Hours of Service (HOS) regulations, including driving limits, duty hours, mandatory breaks, and fueling stops. The backend generates detailed electronic logging device (ELD) logs for each trip, tracking the driver's duty status, location, and distance traveled.

### Key Features
- **Trip Planning**: Create and retrieve truck trips with details such as current location, pickup location, dropoff location, start time, and current cycle hours.
- **HOS Compliance**: Automatically generates ELD logs that comply with HOS regulations for property-carrying drivers (70 hours/8 days).
- **Fueling Stops**: Plans fueling stops at least every 1,000 miles, with each stop lasting 15 minutes.
- **Pickup and Dropoff**: Allocates 1 hour for both pickup and dropoff activities.
- **Distance Tracking**: Logs include the cumulative distance traveled at each step.
- **REST API**: Provides endpoints to create and retrieve trips, integrated with a Django REST Framework backend.

## Assumptions

The application operates under the following assumptions:
- **Driver Type**: Property-carrying driver.
- **HOS Rules**: 70 hours of service over 8 days, with the following limits:
  - Maximum 11 hours of driving per 14-hour duty window.
  - Maximum 14 hours of on-duty time per window (including driving and non-driving activities).
  - Mandatory 30-minute break after 8 hours of cumulative driving.
  - Minimum 10-hour rest period after a 14-hour duty window or 11 hours of driving.
  - 34-hour restart period if the 70-hour cycle limit is reached.
- **No Adverse Driving Conditions**: Assumes constant driving speed of 60 mph with no delays or adverse conditions (e.g., weather, traffic).
- **Fueling**: Fueling stops are required at least once every 1,000 miles, with each stop taking 15 minutes (on-duty, not driving).
- **Pickup and Dropoff**: Each takes exactly 1 hour (on-duty, not driving).
- **Distance Calculation**: For simplicity, distances are simulated (e.g., 200 miles from current location to pickup, 2,800 miles from pickup to dropoff for a total of 3,000 miles in the example trip). In a production environment, this should be replaced with a real distance calculation API (e.g., Google Maps API).

## Requirements

- **Python**: 3.9 or higher (tested with Python 3.9)
- **Django**: 4.x (or compatible version)
- **Django REST Framework**: For API functionality
- **python-dotenv**: For environment variable management
- **Database**: SQLite (default for development; can be replaced with PostgreSQL or another database for production)

## Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-username/truck-trip-planner-backend.git
   cd truck-trip-planner-backend
   ```

2. **Create a Virtual Environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**:
   Create a `requirements.txt` file with the following content:
   ```
   django==4.2
   djangorestframework==3.14
   python-dotenv==1.0.0
   ```
   Then install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set Up Environment Variables**:
   Create a `.env` file in the project root (or simply duplicate the `.env.example` file and rename it `.env`) with the following content:
   ```
   SECRET_KEY=your-django-secret-key
   DEBUG=True
   ```
   Replace `your-django-secret-key` with a secure key (you can generate one using Django's `get_random_secret_key()`).

5. **Run Migrations**:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

6. **Run the Development Server**:
   ```bash
   python manage.py runserver
   ```
   The server will be available at `http://127.0.0.1:8000/`.

## Usage

### API Endpoints
The backend provides the following REST API endpoints using Django REST Framework:

- **Create a Trip**:
  - **Endpoint**: `POST /api/trips/`
  - **Request Body**:
    ```json
    {
      "current_location": "New York, NY",
      "pickup_location": "Chicago, IL",
      "dropoff_location": "Los Angeles, CA",
      "current_cycle_hours": 0.0,
      "start_time": "2025-03-22T06:00:00Z"
    }
    ```
  - **Response**:
    A JSON object representing the created trip, including the estimated duration, total distance, and ELD logs.

- **Retrieve a Trip**:
  - **Endpoint**: `GET /api/trips/<id>/`
  - **Response**:
    A JSON object with the trip details and associated ELD logs, e.g.:
    ```json
    {
      "id": 1,
      "current_location": "New York, NY",
      "pickup_location": "Chicago, IL",
      "dropoff_location": "Los Angeles, CA",
      "current_cycle_hours": 0.0,
      "start_time": "2025-03-22T06:00:00Z",
      "distance": 3000.0,
      "estimated_duration": 50.0,
      "logs": [
        {
          "date": "2025-03-22",
          "duty_status": "DRIVING",
          "start_time": "06:00:00",
          "end_time": "07:00:00",
          "location": "Conduite de New York, NY à Chicago, IL (60.0 miles)"
        },
        ...
      ]
    }
    ```

### Example Workflow
1. Send a `POST` request to `/api/trips/` with the trip details.
2. The backend calculates the total distance, estimated duration, and generates ELD logs based on HOS rules.
3. Retrieve the trip details and logs using a `GET` request to `/api/trips/<id>/`.
4. Use the logs to display the trip timeline on the frontend.

## Project Structure

```
truck-trip-planner-backend/
│
├── manage.py               # Django management script
├── requirements.txt        # Project dependencies
├── .env                    # Environment variables
├── trips/                  # Main Django app
│   ├── __init__.py
│   ├── admin.py            # Django admin configuration
│   ├── apps.py             # App configuration
│   ├── migrations/         # Database migrations
│   ├── models.py           # Trip and LogEntry models
│   ├── serializers.py      # Serializers for API
│   ├── urls.py             # App-specific URLs
│   └── views.py            # API views for trip creation and retrieval
└── truck_trip_planner/     # Project settings
    ├── __init__.py
    ├── settings.py         # Django settings
    ├── urls.py             # Project URLs
    └── wsgi.py             # WSGI entry point
```

## Models

- **Trip**:
  - `current_location`: Starting location of the driver (string).
  - `pickup_location`: Pickup location (string).
  - `dropoff_location`: Dropoff location (string).
  - `current_cycle_hours`: Current hours in the 70-hour cycle (float).
  - `start_time`: Start time of the trip (datetime).
  - `distance`: Total distance of the trip (float, in miles).
  - `estimated_duration`: Estimated duration of the trip (float, in hours).

- **LogEntry**:
  - `trip`: Foreign key to the associated Trip.
  - `date`: Date of the log entry.
  - `duty_status`: Status of the driver (e.g., DRIVING, ON_DUTY_NOT_DRIVING, OFF_DUTY, SLEEPER_BERTH).
  - `start_time`: Start time of the log entry (time).
  - `end_time`: End time of the log entry (time).
  - `location`: Description of the activity and cumulative distance (e.g., "Conduite (660.0 miles)").

## License

This project is licensed under the MIT License. See the `LICENSE` file for details. [THIS IS SPOTTER.AI ASSESSMENT CODE by Abdou-Raouf ATARMLA]

## Future Improvements

- **Real Distance Calculation**: Replace the simulated distance calculation with an API (e.g., Google Maps API or OpenRouteService) for accurate distances.
- **Adverse Conditions**: Add support for adverse driving conditions (e.g., weather, traffic) that may affect speed or require additional stops.
- **Optimization**: Explore grouping fueling stops with mandatory 30-minute breaks to optimize the driver's schedule.
- **Frontend Integration**: Develop a frontend interface to visualize the trip timeline and ELD logs.
- **Testing**: Add unit tests for the API endpoints and HOS compliance logic.

## Contact

For questions or support, please contact [achilleatarmla@gmail.com].
