class DummyPOI:
    def __init__(self, name, ideal_time_start=None, valid_days_of_week=None, priority='Normal'):
        self.name = name
        self.ideal_time_start = ideal_time_start
        self.valid_days_of_week = valid_days_of_week
        self.priority = priority
        
pois = [
    DummyPOI("Akershus", ideal_time_start="17:30", valid_days_of_week=[0], priority="Must See"),
    DummyPOI("Garden Grill", priority="Must See"),
    DummyPOI("Unconstrained"),
    DummyPOI("Columbia Harbour", ideal_time_start="17:30", priority="Must See")
]

cluster_pois = sorted(
    pois, 
    key=lambda p: (
        getattr(p, 'priority', '') == 'Must See',
        bool(getattr(p, 'ideal_time_start', None)), 
        bool(getattr(p, 'valid_days_of_week', None))
    ), 
    reverse=True
)

for p in cluster_pois:
    print(p.name, p.ideal_time_start, p.valid_days_of_week, p.priority)
