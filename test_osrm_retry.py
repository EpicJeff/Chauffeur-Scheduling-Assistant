import requests
import time

url = "http://router.project-osrm.org/table/v1/driving/30.0762974,-20.3383799;-89.9301766,15.5395297;129.0601538,35.2034465;0.3287156,51.0661732;-122.1989988,37.4189641;126.635862,45.8336035;-7.0995514,42.7052097;2.2844935,48.85985;76.134713,10.6140091;-1.3157013,43.6614308;-73.890108,40.828775;27.2593695,31.3541689;-122.1,37.4;-78.8021,35.7725"
params = {
    "sources": "0;1;2;3;4;5;6;7;8;9;10;11;12;13",
    "destinations": "0;1;2;3;4;5;6;7;8;9;10;11;12;13",
    "annotations": "duration,distance"
}

for i in range(5):
    resp = requests.get(url, params=params)
    print(f"Attempt {i}: {resp.status_code}")
    if resp.status_code == 200:
        break
    time.sleep(2)
