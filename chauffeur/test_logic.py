import datetime
slot_time = datetime.time(4, 45)
earliest_time = datetime.time(8, 0)
print(f"slot_time: {slot_time}, earliest_time: {earliest_time}")
print(f"slot_time < earliest_time: {slot_time < earliest_time}")
