import os

content = open('chauffeur/solver/matcher.py', 'r').read()

r1 = '''                travel_time_mins = get_travel_time_minutes(e1.location, e2.location)
                total_needed_seconds = (travel_time_mins + 5) * 60 + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                gap_seconds = (e2.start - e1.end).total_seconds()
                
                # Check attendance constraints
                attendance_conflict = event_requires_attendance.get(e1.id, False) or event_requires_attendance.get(e2.id, False)
                
                gap_seconds_with_tolerance = gap_seconds + (e_tolerances.get(e2.id, 0) * 60)
                if gap_seconds_with_tolerance < total_needed_seconds:
                    # Passenger conflict soft penalty
                    for d1 in drivers:
                        for d2 in drivers:
                            both = model.NewBoolVar(f'pass_conf_{e1.id}_{d1.id}_{e2.id}_{d2.id}')
                            model.AddImplication(both, assign_vars[(e1.id, d1.id)])
                            model.AddImplication(both, assign_vars[(e2.id, d2.id)])
                            model.AddBoolOr([both, assign_vars[(e1.id, d1.id)].Not(), assign_vars[(e2.id, d2.id)].Not()])
                            objective_terms.append(both * -2000000)'''
s1 = '''                travel_time_mins = get_travel_time_minutes(e1.location, e2.location)
                min_needed_seconds = (travel_time_mins + 5) * 60
                desired_needed_seconds = min_needed_seconds + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                gap_seconds = (e2.start - e1.end).total_seconds()
                
                # Check attendance constraints
                attendance_conflict = event_requires_attendance.get(e1.id, False) or event_requires_attendance.get(e2.id, False)
                
                gap_seconds_with_tolerance = gap_seconds + (e_tolerances.get(e2.id, 0) * 60)
                if gap_seconds_with_tolerance < min_needed_seconds:
                    # Passenger conflict hard penalty (impossible)
                    for d1 in drivers:
                        for d2 in drivers:
                            both = model.NewBoolVar(f'pass_conf_{e1.id}_{d1.id}_{e2.id}_{d2.id}')
                            model.AddImplication(both, assign_vars[(e1.id, d1.id)])
                            model.AddImplication(both, assign_vars[(e2.id, d2.id)])
                            model.AddBoolOr([both, assign_vars[(e1.id, d1.id)].Not(), assign_vars[(e2.id, d2.id)].Not()])
                            objective_terms.append(both * -2000000)
                elif gap_seconds < desired_needed_seconds:
                    # Passenger conflict soft penalty (buffer eaten into)
                    for d1 in drivers:
                        for d2 in drivers:
                            both = model.NewBoolVar(f'pass_buffer_conf_{e1.id}_{d1.id}_{e2.id}_{d2.id}')
                            model.AddImplication(both, assign_vars[(e1.id, d1.id)])
                            model.AddImplication(both, assign_vars[(e2.id, d2.id)])
                            model.AddBoolOr([both, assign_vars[(e1.id, d1.id)].Not(), assign_vars[(e2.id, d2.id)].Not()])
                            objective_terms.append(both * -50)'''
content = content.replace(r1, s1)

r2 = '''                travel_time_mins = get_switch_travel_time(e1, e2, events)
                total_needed_seconds = (travel_time_mins + 5) * 60 + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                gap_seconds = (e2.start - e1.end).total_seconds()
                
                if e1.location and e2.location and e1.location.strip().lower() == e2.location.strip().lower():
                    gap_seconds = float('inf')
                else:
                    attendance_conflict = event_requires_attendance.get(e1.id, False) or event_requires_attendance.get(e2.id, False)
                    if not attendance_conflict and e1.location and e2.location:
                        req_d1_d2 = get_switch_travel_time(e1, e2, events) * 60
                        late_drop_e2 = max(0, req_d1_d2 - (e2.start - e1.start).total_seconds())
                        
                        req_e1_e2 = get_travel_time_minutes(e1.location, e2.location) * 60 + 5 * 60 + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                        req_e2_e1 = get_travel_time_minutes(e2.location, e1.location) * 60 + 5 * 60 + e_buffer_after.get(e2.id, 0) * 60 + e_buffer_before.get(e1.id, 0) * 60
                        
                        tol_e1 = e_tolerances.get(e1.id, 0) * 60
                        tol_e2 = e_tolerances.get(e2.id, 0) * 60
                        
                        if e2.end <= e1.end:
                            # Profile B: e2 is fully enveloped by e1. Drop e1 -> Drop e2 -> Pick e2 -> Pick e1
                            late_pick_e1 = max(0, req_e2_e1 - (e1.end - e2.end).total_seconds())
                            if late_drop_e2 <= tol_e2 and late_pick_e1 <= tol_e1:
                                gap_seconds = float('inf')
                        else:
                            # Profile A: e1 and e2 overlap. Drop e1 -> Drop e2 -> Pick e1 -> Pick e2
                            late_pick_e1 = max(0, req_e2_e1 - (e1.end - e2.start).total_seconds())
                            late_pick_e2 = max(0, req_e1_e2 - (e2.end - e1.end).total_seconds())
                            if late_drop_e2 <= tol_e2 and late_pick_e1 <= tol_e1 and late_pick_e2 <= tol_e2:
                                gap_seconds = float('inf')

                if (e1.id, e2.id) in grouped_event_pairs:
                    gap_seconds = float('inf')

                gap_seconds_with_tolerance = gap_seconds + (e_tolerances.get(e2.id, 0) * 60)
                if gap_seconds_with_tolerance < total_needed_seconds:
                    # Driver conflict soft penalty
                    for d in drivers:
                        both = model.NewBoolVar(f'drv_conf_{e1.id}_{e2.id}_{d.id}')
                        model.AddImplication(both, assign_vars[(e1.id, d.id)])
                        model.AddImplication(both, assign_vars[(e2.id, d.id)])
                        model.AddBoolOr([both, assign_vars[(e1.id, d.id)].Not(), assign_vars[(e2.id, d.id)].Not()])
                        objective_terms.append(both * -1000000)'''
s2 = '''                travel_time_mins = get_switch_travel_time(e1, e2, events)
                min_needed_seconds = (travel_time_mins + 5) * 60
                desired_needed_seconds = min_needed_seconds + e_buffer_after.get(e1.id, 0) * 60 + e_buffer_before.get(e2.id, 0) * 60
                gap_seconds = (e2.start - e1.end).total_seconds()
                
                if e1.location and e2.location and e1.location.strip().lower() == e2.location.strip().lower():
                    gap_seconds = float('inf')
                else:
                    attendance_conflict = event_requires_attendance.get(e1.id, False) or event_requires_attendance.get(e2.id, False)
                    if not attendance_conflict and e1.location and e2.location:
                        req_d1_d2 = get_switch_travel_time(e1, e2, events) * 60
                        late_drop_e2 = max(0, req_d1_d2 - (e2.start - e1.start).total_seconds())
                        
                        # In profile overlap checks, we use min_needed_seconds strictly since it's already tight
                        req_e1_e2 = get_travel_time_minutes(e1.location, e2.location) * 60 + 5 * 60
                        req_e2_e1 = get_travel_time_minutes(e2.location, e1.location) * 60 + 5 * 60
                        
                        tol_e1 = e_tolerances.get(e1.id, 0) * 60
                        tol_e2 = e_tolerances.get(e2.id, 0) * 60
                        
                        if e2.end <= e1.end:
                            # Profile B: e2 is fully enveloped by e1. Drop e1 -> Drop e2 -> Pick e2 -> Pick e1
                            late_pick_e1 = max(0, req_e2_e1 - (e1.end - e2.end).total_seconds())
                            if late_drop_e2 <= tol_e2 and late_pick_e1 <= tol_e1:
                                gap_seconds = float('inf')
                        else:
                            # Profile A: e1 and e2 overlap. Drop e1 -> Drop e2 -> Pick e1 -> Pick e2
                            late_pick_e1 = max(0, req_e2_e1 - (e1.end - e2.start).total_seconds())
                            late_pick_e2 = max(0, req_e1_e2 - (e2.end - e1.end).total_seconds())
                            if late_drop_e2 <= tol_e2 and late_pick_e1 <= tol_e1 and late_pick_e2 <= tol_e2:
                                gap_seconds = float('inf')

                if (e1.id, e2.id) in grouped_event_pairs:
                    gap_seconds = float('inf')

                gap_seconds_with_tolerance = gap_seconds + (e_tolerances.get(e2.id, 0) * 60)
                if gap_seconds_with_tolerance < min_needed_seconds:
                    # Driver conflict hard penalty (impossible)
                    for d in drivers:
                        both = model.NewBoolVar(f'drv_conf_{e1.id}_{e2.id}_{d.id}')
                        model.AddImplication(both, assign_vars[(e1.id, d.id)])
                        model.AddImplication(both, assign_vars[(e2.id, d.id)])
                        model.AddBoolOr([both, assign_vars[(e1.id, d.id)].Not(), assign_vars[(e2.id, d.id)].Not()])
                        objective_terms.append(both * -1000000)
                elif gap_seconds < desired_needed_seconds:
                    # Driver conflict soft penalty (buffer eaten into)
                    for d in drivers:
                        both = model.NewBoolVar(f'drv_buffer_conf_{e1.id}_{e2.id}_{d.id}')
                        model.AddImplication(both, assign_vars[(e1.id, d.id)])
                        model.AddImplication(both, assign_vars[(e2.id, d.id)])
                        model.AddBoolOr([both, assign_vars[(e1.id, d.id)].Not(), assign_vars[(e2.id, d.id)].Not()])
                        objective_terms.append(both * -50)'''
content = content.replace(r2, s2)

open('chauffeur/solver/matcher.py', 'w').write(content)
