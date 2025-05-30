

AVERAGE_SPEED = 60  
MAX_DRIVING_HOURS_PER_WINDOW = 11  
MAX_DUTY_HOURS_PER_WINDOW = 14  
MAX_DRIVING_HOURS_BEFORE_BREAK = 8  
MAX_CYCLE_HOURS = 70  
FUELING_INTERVAL = 1000
MINIMUM_REST_HOURS = 10  
RESTART_HOURS = 34  

# Coordinate format: [latitude, longitude]
# Note: The OpenRouteService API expects [longitude, latitude], but the conversion is done in _calculate_route_distance (view.py file)
CITIES_WITH_COORDS = {
    "New York, NY": [40.7128, -74.0060],
    "Los Angeles, CA": [34.0522, -118.2437],
    "Chicago, IL": [41.8781, -87.6298],
    "Houston, TX": [29.7604, -95.3698],
    "Phoenix, AZ": [33.4484, -112.0740],
    "Philadelphia, PA": [39.9526, -75.1652],
    "San Antonio, TX": [29.4241, -98.4936],
    "San Diego, CA": [32.7157, -117.1611],
    "Dallas, TX": [32.7767, -96.7970],
    "San Jose, CA": [37.3382, -121.8863],
    "Austin, TX": [30.2672, -97.7431],
    "Jacksonville, FL": [30.3322, -81.6557],
    "San Francisco, CA": [37.7749, -122.4194],
    "Columbus, OH": [39.9612, -82.9988],
    "Seattle, WA": [47.6062, -122.3321],
    "Denver, CO": [39.7392, -104.9903],
    "Boston, MA": [42.3601, -71.0589],
    "Miami, FL": [25.7617, -80.1918],
    "Atlanta, GA": [33.7490, -84.3880],
    "Portland, OR": [45.5152, -122.6784],
    "Las Vegas, NV": [36.1699, -115.1398],
    "Minneapolis, MN": [44.9778, -93.2650],
    "Richmond, VA": [37.5407, -77.4360],
    "Fredericksburg, VA": [38.3032, -77.4605],
    "Baltimore, MD": [39.2904, -76.6122],
    "Cherry Hill, NJ": [39.9268, -75.0246],
    "Newark, NJ": [40.7357, -74.1724],
    "Charlotte, NC": [35.2271, -80.8431],
    "Indianapolis, IN": [39.7684, -86.1581],
    "Fort Worth, TX": [32.7555, -97.3308],
    "Tucson, AZ": [32.2226, -110.9747],
    "Mesa, AZ": [33.4152, -111.8315],
    "Sacramento, CA": [38.5816, -121.4944],
    "Kansas City, MO": [39.0997, -94.5786],
    "Raleigh, NC": [35.7796, -78.6382],
    "Omaha, NE": [41.2565, -95.9345],
    "Tampa, FL": [27.9506, -82.4572],
    "Orlando, FL": [28.5383, -81.3792],
    "St. Louis, MO": [38.6270, -90.1994],
    "Pittsburgh, PA": [40.4406, -79.9959],
    "Cincinnati, OH": [39.1031, -84.5120],
    "Cleveland, OH": [41.4993, -81.6944],
    "Nashville, TN": [36.1627, -86.7816],
    "Memphis, TN": [35.1495, -90.0490],
    "Louisville, KY": [38.2527, -85.7585],
    "Milwaukee, WI": [43.0389, -87.9065],
    "Albuquerque, NM": [35.0844, -106.6504],
    "Oklahoma City, OK": [35.4676, -97.5164],
    "Tulsa, OK": [36.1540, -95.9928],
    "Bakersfield, CA": [35.3733, -119.0187],
    "Fresno, CA": [36.7378, -119.7871],
    "Anaheim, CA": [33.8366, -117.9143],
    "Santa Ana, CA": [33.7455, -117.8677],
    "Riverside, CA": [33.9806, -117.3755],
    "Stockton, CA": [37.9577, -121.2908],
    "Corpus Christi, TX": [27.8006, -97.3964],
    "Lexington, KY": [38.0406, -84.5037],
    "Buffalo, NY": [42.8864, -78.8784],
    "Rochester, NY": [43.1566, -77.6088],
    "Albany, NY": [42.6526, -73.7562],
    "Syracuse, NY": [43.0481, -76.1474],
    "Greensboro, NC": [36.0726, -79.7920],
    "Winston-Salem, NC": [36.0999, -80.2442],
    "Durham, NC": [35.9940, -78.8986],
    "Birmingham, AL": [33.5207, -86.8025],
    "Montgomery, AL": [32.3668, -86.3000],
    "Mobile, AL": [30.6954, -88.0399],
    "Huntsville, AL": [34.7304, -86.5861],
    "Little Rock, AR": [34.7465, -92.2896],
    "Fayetteville, AR": [36.0626, -94.1574],
    "Boise, ID": [43.6150, -116.2023],
    "Spokane, WA": [47.6588, -117.4260],
    "Tacoma, WA": [47.2529, -122.4443],
    "Salt Lake City, UT": [40.7608, -111.8910],
    "Provo, UT": [40.2338, -111.6585],
    "Des Moines, IA": [41.5868, -93.6250],
    "Cedar Rapids, IA": [41.9779, -91.6656],
    "Wichita, KS": [37.6872, -97.3301],
    "Topeka, KS": [39.0558, -95.6890],
    "Shreveport, LA": [32.5252, -93.7502],
    "Baton Rouge, LA": [30.4515, -91.1871],
    "New Orleans, LA": [29.9511, -90.0715],
    "Lafayette, LA": [30.2241, -92.0198],
    "Jackson, MS": [32.2988, -90.1848],
    "Gulfport, MS": [30.3674, -89.0928],
    "Billings, MT": [45.7833, -108.5007],
    "Missoula, MT": [46.8721, -113.9940],
    "Fargo, ND": [46.8772, -96.7898],
    "Bismarck, ND": [46.8083, -100.7837],
    "Sioux Falls, SD": [43.5446, -96.7311],
    "Rapid City, SD": [44.0805, -103.2310],
    "Charleston, SC": [32.7765, -79.9311],
    "Columbia, SC": [34.0007, -81.0348],
    "Greenville, SC": [34.8526, -82.3940],
    "Knoxville, TN": [35.9606, -83.9207],
    "Chattanooga, TN": [35.0456, -85.3097],
    "El Paso, TX": [31.7619, -106.4850],
    "Lubbock, TX": [33.5779, -101.8552],
    "Amarillo, TX": [35.2220, -101.8313],
    "Brownsville, TX": [25.9018, -97.4975],
    "McAllen, TX": [26.2034, -98.2300]
}

CITIES = list(CITIES_WITH_COORDS.keys())