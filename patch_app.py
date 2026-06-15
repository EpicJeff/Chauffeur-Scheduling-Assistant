import os

content = open('chauffeur/templates/app.html', 'r').read()

r1 = '''                            const depTime = new Date(new Date(ev.start).getTime() - (edge.travel_mins + 5) * 60000);'''
s1 = '''                            const depTime = new Date(new Date(ev.start).getTime() - (edge.travel_mins + 5 + (edge.buffer_before_mins || 0)) * 60000);'''
content = content.replace(r1, s1)

r2 = '''                        if (edge.home_waypoint) {
                            const leg1Mins = edge.home_waypoint.to_home_mins;
                            const leg2Mins = edge.home_waypoint.from_home_mins;
                            const leg2DepTime = new Date(new Date(ev.end).getTime() + (leg1Mins + edge.home_waypoint.layover_mins) * 60000);
                            const driverHomeLoc = edge.home_waypoint.driver_home_location || globalHome;
                            
                            let args1 = `\\'${computedOrigin.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${driverHomeLoc.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive to Hotel/Home\\', \\'${ev.id}\\'`;
                            html += renderLegPill(formatTime(ev.end), "Drive to Hotel/Home", leg1Mins, 0, args1 + `, 'route_${ev.id}_1'`, 'blue', '', `route_${ev.id}_1`, new Date(ev.end) < new Date());
                            
                            let args2 = `\\'${driverHomeLoc.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${destinationLocation.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive to ${destinationLocation.split(',')[0].replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${ev.id}\\'`;
                            html += renderLegPill(formatTime(leg2DepTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, leg2Mins, edge.delay_mins, args2 + `, 'route_${ev.id}_2'`, 'blue', nextBadges, `route_${ev.id}_2`, leg2DepTime < new Date(), edge.late_mins || 0);
                        } else if (edge.pickup_waypoint) {
                            const leg1Mins = edge.pickup_waypoint.to_pickup_mins;
                            const leg2Mins = edge.pickup_waypoint.from_pickup_mins;
                            const pickupLocation = edge.pickup_waypoint.pickup_location || globalHome;
                            const pickupTitle = edge.pickup_waypoint.pickup_event_title ? `Pickup at ${edge.pickup_waypoint.pickup_event_title}` : 'Pickup';
                            const leg2DepTime = new Date(new Date(ev.end).getTime() + leg1Mins * 60000);
                            
                            let args1 = `\\'${computedOrigin.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${pickupLocation.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${pickupTitle.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${ev.id}\\'`;
                            html += renderLegPill(formatTime(ev.end), pickupTitle, leg1Mins, 0, args1 + `, 'route_${ev.id}_1'`, 'blue', nextBadges, `route_${ev.id}_1`, new Date(ev.end) < new Date());
                            
                            let args2 = `\\'${pickupLocation.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${destinationLocation.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive to ${destinationLocation.split(',')[0].replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${ev.id}\\'`;
                            html += renderLegPill(formatTime(leg2DepTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, leg2Mins, edge.delay_mins, args2 + `, 'route_${ev.id}_2'`, 'blue', '', `route_${ev.id}_2`, leg2DepTime < new Date(), edge.late_mins || 0);
                        } else {
                            let destStr = destinationLocation ? destinationLocation.split(',')[0] : 'Next Event';
                            let args = `\\'${(computedOrigin || '').replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${(destinationLocation || '').replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive to ${destStr.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${ev.id}\\'`;
                            html += renderLegPill(formatTime(ev.end), `Drive to ${destStr}`, edge.travel_mins, edge.delay_mins, args + `, 'route_${ev.id}_${nextEv.id}'`, 'blue', nextBadges, `route_${ev.id}_${nextEv.id}`, new Date(ev.end) < new Date(), edge.late_mins || 0);
                        }'''
r2 = r2.replace("\\'", "'").replace("\\\\'", "\\'")
s2 = '''                        const leaveTimeObj = new Date(new Date(ev.end).getTime() + (edge.buffer_after_mins || 0) * 60000);
                        const leaveTimeStr = leaveTimeObj.toISOString();
                        if (edge.home_waypoint) {
                            const leg1Mins = edge.home_waypoint.to_home_mins;
                            const leg2Mins = edge.home_waypoint.from_home_mins;
                            const leg2DepTime = new Date(leaveTimeObj.getTime() + (leg1Mins + edge.home_waypoint.layover_mins) * 60000);
                            const driverHomeLoc = edge.home_waypoint.driver_home_location || globalHome;
                            
                            let args1 = `\\'${computedOrigin.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${driverHomeLoc.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive to Hotel/Home\\', \\'${ev.id}\\'`;
                            html += renderLegPill(formatTime(leaveTimeStr), "Drive to Hotel/Home", leg1Mins, 0, args1 + `, 'route_${ev.id}_1'`, 'blue', '', `route_${ev.id}_1`, leaveTimeObj < new Date());
                            
                            let args2 = `\\'${driverHomeLoc.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${destinationLocation.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive to ${destinationLocation.split(',')[0].replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${ev.id}\\'`;
                            html += renderLegPill(formatTime(leg2DepTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, leg2Mins, edge.delay_mins, args2 + `, 'route_${ev.id}_2'`, 'blue', nextBadges, `route_${ev.id}_2`, leg2DepTime < new Date(), edge.late_mins || 0);
                        } else if (edge.pickup_waypoint) {
                            const leg1Mins = edge.pickup_waypoint.to_pickup_mins;
                            const leg2Mins = edge.pickup_waypoint.from_pickup_mins;
                            const pickupLocation = edge.pickup_waypoint.pickup_location || globalHome;
                            const pickupTitle = edge.pickup_waypoint.pickup_event_title ? `Pickup at ${edge.pickup_waypoint.pickup_event_title}` : 'Pickup';
                            const leg2DepTime = new Date(leaveTimeObj.getTime() + leg1Mins * 60000);
                            
                            let args1 = `\\'${computedOrigin.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${pickupLocation.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${pickupTitle.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${ev.id}\\'`;
                            html += renderLegPill(formatTime(leaveTimeStr), pickupTitle, leg1Mins, 0, args1 + `, 'route_${ev.id}_1'`, 'blue', nextBadges, `route_${ev.id}_1`, leaveTimeObj < new Date());
                            
                            let args2 = `\\'${pickupLocation.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${destinationLocation.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive to ${destinationLocation.split(',')[0].replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${ev.id}\\'`;
                            html += renderLegPill(formatTime(leg2DepTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, leg2Mins, edge.delay_mins, args2 + `, 'route_${ev.id}_2'`, 'blue', '', `route_${ev.id}_2`, leg2DepTime < new Date(), edge.late_mins || 0);
                        } else {
                            let destStr = destinationLocation ? destinationLocation.split(',')[0] : 'Next Event';
                            let args = `\\'${(computedOrigin || '').replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${(destinationLocation || '').replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive to ${destStr.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${ev.id}\\'`;
                            html += renderLegPill(formatTime(leaveTimeStr), `Drive to ${destStr}`, edge.travel_mins, edge.delay_mins, args + `, 'route_${ev.id}_${nextEv.id}'`, 'blue', nextBadges, `route_${ev.id}_${nextEv.id}`, leaveTimeObj < new Date(), edge.late_mins || 0);
                        }'''
s2 = s2.replace("\\'", "'").replace("\\\\'", "\\'")
content = content.replace(r2, s2)

r3 = '''                            const arriveDate = new Date(new Date(ev.end).getTime() + edge.travel_mins * 60000);
                            const originLocation = ev.location;
                            const destinationLocation = edge.driver_home_location || driverConfig.home_location || globalHome;
                            const badges = getPassengerBadges(ev);
                            
                            if (edge.dropoff_waypoint) {
                                const leg1Mins = edge.dropoff_waypoint.to_global_home_mins;
                                const leg2Mins = edge.dropoff_waypoint.to_driver_home_mins;
                                const leg2DepTime = new Date(new Date(ev.end).getTime() + leg1Mins * 60000);
                                const leg2ArrTime = arriveDate;
                                
                                const paxDropoffLoc = edge.dropoff_waypoint.dropoff_location || globalHome;
                                const driverHomeLoc = edge.dropoff_waypoint.driver_home_location || destinationLocation;
                                
                                let args1 = `\\'${originLocation.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${paxDropoffLoc.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive to Dropoff\\', \\'${ev.id}\\'`;
                                html += renderLegPill(formatTime(leg2DepTime.toISOString()), "Drive to Dropoff", leg1Mins, 0, args1 + `, 'final_${ev.id}_1'`, 'green', badges, `final_${ev.id}_1`, leg2DepTime < new Date());
                                
                                let args2 = `\\'${paxDropoffLoc.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${driverHomeLoc.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive Home\\', \\'${ev.id}\\'`;
                                html += renderLegPill(formatTime(leg2ArrTime.toISOString()), "Drive Home", leg2Mins, edge.delay_mins, args2 + `, 'final_${ev.id}'`, 'green', '', `final_${ev.id}`, leg2ArrTime < new Date());
                            } else {
                                let args = `\\'${(originLocation || '').replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${(destinationLocation || '').replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive Home\\', \\'${ev.id}\\'`;
                                html += renderLegPill(formatTime(ev.end), "Drive Home", edge.travel_mins, edge.delay_mins, args + `, 'final_${ev.id}'`, 'green', badges, `final_${ev.id}`, new Date(ev.end) < new Date());
                            }'''
r3 = r3.replace("\\'", "'").replace("\\\\'", "\\'")
s3 = '''                            const leaveTimeObj = new Date(new Date(ev.end).getTime() + (edge.buffer_after_mins || 0) * 60000);
                            const arriveDate = new Date(leaveTimeObj.getTime() + edge.travel_mins * 60000);
                            const originLocation = ev.location;
                            const destinationLocation = edge.driver_home_location || driverConfig.home_location || globalHome;
                            const badges = getPassengerBadges(ev);
                            
                            if (edge.dropoff_waypoint) {
                                const leg1Mins = edge.dropoff_waypoint.to_global_home_mins;
                                const leg2Mins = edge.dropoff_waypoint.to_driver_home_mins;
                                const leg2DepTime = new Date(leaveTimeObj.getTime() + leg1Mins * 60000);
                                const leg2ArrTime = arriveDate;
                                
                                const paxDropoffLoc = edge.dropoff_waypoint.dropoff_location || globalHome;
                                const driverHomeLoc = edge.dropoff_waypoint.driver_home_location || destinationLocation;
                                
                                let args1 = `\\'${originLocation.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${paxDropoffLoc.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive to Dropoff\\', \\'${ev.id}\\'`;
                                html += renderLegPill(formatTime(leg2DepTime.toISOString()), "Drive to Dropoff", leg1Mins, 0, args1 + `, 'final_${ev.id}_1'`, 'green', badges, `final_${ev.id}_1`, leg2DepTime < new Date());
                                
                                let args2 = `\\'${paxDropoffLoc.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${driverHomeLoc.replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive Home\\', \\'${ev.id}\\'`;
                                html += renderLegPill(formatTime(leg2ArrTime.toISOString()), "Drive Home", leg2Mins, edge.delay_mins, args2 + `, 'final_${ev.id}'`, 'green', '', `final_${ev.id}`, leg2ArrTime < new Date());
                            } else {
                                let args = `\\'${(originLocation || '').replace(/\\'/g, "\\\\\\'\\'")}\\', \\'${(destinationLocation || '').replace(/\\'/g, "\\\\\\'\\'")}\\', \\'Drive Home\\', \\'${ev.id}\\'`;
                                html += renderLegPill(formatTime(leaveTimeObj.toISOString()), "Drive Home", edge.travel_mins, edge.delay_mins, args + `, 'final_${ev.id}'`, 'green', badges, `final_${ev.id}`, leaveTimeObj < new Date());
                            }'''
s3 = s3.replace("\\'", "'").replace("\\\\'", "\\'")
content = content.replace(r3, s3)

open('chauffeur/templates/app.html', 'w').write(content)
