import re

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update openActionSheet signature
content = content.replace("function openActionSheet(origin, destination, legTitle, eventId = null) {", "function openActionSheet(origin, destination, legTitle, eventId = null, legId = null) {")
content = content.replace("routeContext = { origin, destination, legTitle, eventId };", "routeContext = { origin, destination, legTitle, eventId, legId };")

# 2. Update markCompleted to send leg_id
old_mark = """body: JSON.stringify({
                        driver_id: currentDriverId,
                        event_id: routeContext.eventId,
                        action: actionStr,
                        details: routeContext.legTitle
                    })"""
new_mark = """body: JSON.stringify({
                        driver_id: currentDriverId,
                        event_id: routeContext.eventId,
                        action: actionStr,
                        details: routeContext.legTitle,
                        leg_id: routeContext.legId
                    })
                });
                
                // ALSO mark it in drive_status backend
                await fetch('/api/drive_status', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        leg_id: routeContext.legId,
                        status: 'completed'
                    })"""
content = content.replace(old_mark, new_mark)

# 3. Add legId to renderLegPill calls
content = content.replace("html += renderLegPill(formatTime(depTime.toISOString()), \"Drive to Pickup\", leg1Mins, 0, args1, 'blue', badges);", "html += renderLegPill(formatTime(depTime.toISOString()), \"Drive to Pickup\", leg1Mins, 0, args1 + `, 'init_${ev.id}_1'`, 'blue', badges, `init_${ev.id}_1`);")
content = content.replace("html += renderLegPill(formatTime(leg2DepTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, leg2Mins, edge.delay_mins, args2, 'blue');", "html += renderLegPill(formatTime(leg2DepTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, leg2Mins, edge.delay_mins, args2 + `, 'init_${ev.id}'`, 'blue', '', `init_${ev.id}`);")
content = content.replace("html += renderLegPill(formatTime(depTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, edge.travel_mins, edge.delay_mins, args, 'blue', badges);", "html += renderLegPill(formatTime(depTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, edge.travel_mins, edge.delay_mins, args + `, 'init_${ev.id}'`, 'blue', badges, `init_${ev.id}`);")

content = content.replace("html += renderLegPill(formatTime(ev.end), \"Drive to Dropoff/Pickup\", leg1Mins, 0, args1, 'blue');", "html += renderLegPill(formatTime(ev.end), \"Drive to Dropoff/Pickup\", leg1Mins, 0, args1 + `, 'route_${ev.id}_1'`, 'blue', '', `route_${ev.id}_1`);")
content = content.replace("html += renderLegPill(formatTime(leg2DepTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, leg2Mins, edge.delay_mins, args2, 'blue', nextBadges);", "html += renderLegPill(formatTime(leg2DepTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, leg2Mins, edge.delay_mins, args2 + `, 'route_${ev.id}_2'`, 'blue', nextBadges, `route_${ev.id}_2`);")

content = content.replace("html += renderLegPill(formatTime(ev.end), \"Drive to Pickup\", leg1Mins, 0, args1, 'blue', nextBadges);", "html += renderLegPill(formatTime(ev.end), \"Drive to Pickup\", leg1Mins, 0, args1 + `, 'route_${ev.id}_1'`, 'blue', nextBadges, `route_${ev.id}_1`);")
content = content.replace("html += renderLegPill(formatTime(ev.end), `Drive to ${destStr}`, edge.travel_mins, edge.delay_mins, args, 'blue', nextBadges);", "html += renderLegPill(formatTime(ev.end), `Drive to ${destStr}`, edge.travel_mins, edge.delay_mins, args + `, 'route_${ev.id}_${nextEv.id}'`, 'blue', nextBadges, `route_${ev.id}_${nextEv.id}`);")

content = content.replace("html += renderLegPill(formatTime(leg2DepTime.toISOString()), \"Drive to Dropoff\", leg1Mins, 0, args1, 'green', badges);", "html += renderLegPill(formatTime(leg2DepTime.toISOString()), \"Drive to Dropoff\", leg1Mins, 0, args1 + `, 'final_${ev.id}_1'`, 'green', badges, `final_${ev.id}_1`);")
content = content.replace("html += renderLegPill(formatTime(leg2ArrTime.toISOString()), \"Drive Home\", leg2Mins, edge.delay_mins, args2, 'green');", "html += renderLegPill(formatTime(leg2ArrTime.toISOString()), \"Drive Home\", leg2Mins, edge.delay_mins, args2 + `, 'final_${ev.id}'`, 'green', '', `final_${ev.id}`);")
content = content.replace("html += renderLegPill(formatTime(arriveDate.toISOString()), \"Drive Home\", edge.travel_mins, edge.delay_mins, args, 'green', badges);", "html += renderLegPill(formatTime(arriveDate.toISOString()), \"Drive Home\", edge.travel_mins, edge.delay_mins, args + `, 'final_${ev.id}'`, 'green', badges, `final_${ev.id}`);")

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("app UI patched")
