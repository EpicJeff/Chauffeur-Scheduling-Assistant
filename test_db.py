import sys
sys.path.append('e:\\repositories\\Chauffeur\\chauffeur')
from services import storage
from models.schemas import Rule

for r in storage.rules_table.all():
    rule = Rule(**r)
    if getattr(rule, 'constraint_type', None) == 'group':
        print(f"Group Rule: {rule.model_dump_json(indent=2)}")
        
for e in storage.events_table.all():
    print(f"Event: {e.get('title')} - {e.get('start')} - Pax: {e.get('calendar_ids')}")
