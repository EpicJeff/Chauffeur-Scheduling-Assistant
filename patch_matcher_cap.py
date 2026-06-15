import os

content = open('chauffeur/solver/matcher.py', 'r').read()

r1 = '''                edges[d_id][e1.id] = {
                    "to_event": e2.id,
                    "travel_mins": travel,
                    "delay_mins": delay,
                    "wait_mins": int(wait),
                    "late_mins": int(late),
                    "buffer_after_mins": e_buffer_after.get(e1.id, 0),
                    "buffer_before_mins": e_buffer_before.get(e2.id, 0)
                }'''
s1 = '''                ba = e_buffer_after.get(e1.id, 0)
                bb = e_buffer_before.get(e2.id, 0)
                slack = max(0, (e2.start.timestamp() - e1.end.timestamp()) / 60 - travel)
                if ba + bb > slack:
                    if ba + bb > 0:
                        actual_ba = int(slack * ba / (ba + bb))
                        actual_bb = int(slack * bb / (ba + bb))
                    else:
                        actual_ba = 0
                        actual_bb = 0
                else:
                    actual_ba = ba
                    actual_bb = bb

                edges[d_id][e1.id] = {
                    "to_event": e2.id,
                    "travel_mins": travel,
                    "delay_mins": delay,
                    "wait_mins": int(wait),
                    "late_mins": int(late),
                    "buffer_after_mins": actual_ba,
                    "buffer_before_mins": actual_bb
                }'''
content = content.replace(r1, s1)

open('chauffeur/solver/matcher.py', 'w').write(content)
