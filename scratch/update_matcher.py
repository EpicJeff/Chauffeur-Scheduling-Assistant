import re

with open('chauffeur/solver/matcher.py', 'r', encoding='utf-8') as f:
    content = f.read()

helper = '''def does_event_match_rule(event, rule) -> bool:
    has_any_criteria = False
    
    # 1. Keywords
    if hasattr(rule, 'keywords') and rule.keywords:
        has_any_criteria = True
        match_kw = False
        event_text = (event.title + " " + (event.description or "")).lower()
        for kw in rule.keywords:
            if kw.lower() in event_text:
                match_kw = True
                break
        if not match_kw: return False
        
    # 2. Passengers
    if hasattr(rule, 'passenger_ids') and rule.passenger_ids:
        has_any_criteria = True
        match_pax = False
        for pid in rule.passenger_ids:
            if pid in event.calendar_ids:
                match_pax = True
                break
        if not match_pax: return False
        
    # 3. Days of Week
    if hasattr(rule, 'days_of_week') and rule.days_of_week:
        has_any_criteria = True
        if event.start.weekday() not in rule.days_of_week: return False
        
    # 4. Time Window
    if hasattr(rule, 'time_start') and rule.time_start:
        has_any_criteria = True
        try:
            h, m = map(int, rule.time_start.split(':'))
            if event.start.hour * 60 + event.start.minute < h * 60 + m: return False
        except: pass
        
    if hasattr(rule, 'time_end') and rule.time_end:
        has_any_criteria = True
        try:
            h, m = map(int, rule.time_end.split(':'))
            if event.end.hour * 60 + event.end.minute > h * 60 + m: return False
        except: pass
        
    return has_any_criteria

'''

if 'def does_event_match_rule' not in content:
    content = content.replace('def solve_schedule(', helper + 'def solve_schedule(')

# Replace existing checks with does_event_match_rule
# 1. Tolerances
content = re.sub(
    r"if r\.constraint_type == 'tolerance' and r\.event_keyword\.lower\(\) in e\.title\.lower\(\):",
    r"if r.constraint_type == 'tolerance' and does_event_match_rule(e, r):",
    content
)

# 2. Priority rules
content = re.sub(
    r"if pr\.match_type == 'keyword' and pr\.match_value\.lower\(\) in e\.title\.lower\(\):\s+base_event_weight \+= mod\s+elif pr\.match_type == 'calendar' and any\(pr\.match_value in cid for cid in e\.calendar_ids\):\s+base_event_weight \+= mod",
    r"if does_event_match_rule(e, pr):\n                base_event_weight += mod",
    content
)

# 3. Driver rules
content = re.sub(
    r"if r\.event_keyword\.lower\(\) in e\.title\.lower\(\) and r\.driver_id == d\.id:",
    r"if does_event_match_rule(e, r) and r.driver_id == d.id:",
    content
)

# 4. Mutually exclusive rules
content = re.sub(
    r"mut_ex_rules = \[r for r in rules if r\.constraint_type == 'mutually_exclusive' and getattr\(r, 'event_keyword', None\)\]",
    r"mut_ex_rules = [r for r in rules if r.constraint_type == 'mutually_exclusive']",
    content
)

content = re.sub(
    r"if r\.event_keyword\.lower\(\) in e\.title\.lower\(\):",
    r"if does_event_match_rule(e, r):",
    content
)

# 5. Diagnostic checks
content = re.sub(
    r"if r\.event_keyword\.lower\(\) in e\.title\.lower\(\):",
    r"if does_event_match_rule(e, r):",
    content
)

with open('chauffeur/solver/matcher.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated matcher.py successfully")
