import os

content = open('chauffeur/solver/matcher.py', 'r').read()

r1 = '''                        travel = 20
                    needed_secs_e_to_de = (travel + 5) * 60 + e_buffer_after.get(e.id, 0) * 60
                    needed_secs_de_to_e = (travel + 5) * 60 + e_buffer_before.get(e.id, 0) * 60
                    
                    # Check for overlap'''
s1 = '''                        travel = 20
                    needed_secs_e_to_de = (travel + 5) * 60
                    needed_secs_de_to_e = (travel + 5) * 60
                    
                    # Check for overlap'''
content = content.replace(r1, s1)

r2 = '''                    travel_time_mins = get_travel_time_minutes(first.location, second.location)
                
                total_needed_seconds = (travel_time_mins + 5) * 60 + e_buffer_after.get(first.id, 0) * 60 + e_buffer_before.get(second.id, 0) * 60
                
                if (second.start - first.end).total_seconds() < total_needed_seconds:'''
s2 = '''                    travel_time_mins = get_travel_time_minutes(first.location, second.location)
                
                total_needed_seconds = (travel_time_mins + 5) * 60
                
                if (second.start - first.end).total_seconds() < total_needed_seconds:'''
content = content.replace(r2, s2)

open('chauffeur/solver/matcher.py', 'w').write(content)
