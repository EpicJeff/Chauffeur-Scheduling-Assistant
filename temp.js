
        let driversData = [];
        let scheduleData = null;
        let selectedDriverId = localStorage.getItem('chauffeur_driver_id');
        let currentDates = [];
        let activeDateIndex = 0;
        let routeContext = null;

        async function init() {
            await fetchDrivers();
            if (selectedDriverId && driversData.find(d => d.id === selectedDriverId)) {
                selectDriver(selectedDriverId);
            } else {
                showDriverSelection();
            }
        }

        async function fetchDrivers() {
            try {
                const res = await fetch('api/drivers');
                const data = await res.json();
                driversData = data.filter(d => !d.is_disabled);
            } catch (e) {
                console.error("Failed to fetch drivers", e);
            }
        }

        function showDriverSelection() {
            document.getElementById('screen-schedule').classList.add('hidden');
            document.getElementById('btn-switch-driver').classList.add('hidden');
            document.getElementById('screen-select-driver').classList.remove('hidden');
            
            document.getElementById('driver-name').textContent = "Select Driver";
            document.getElementById('date-subtitle').textContent = "Chauffeur App";
            document.getElementById('driver-avatar').textContent = "?";
            document.getElementById('driver-avatar').style.borderColor = "#374151";
            document.getElementById('driver-avatar').style.color = "#6B7280";

            const list = document.getElementById('driver-list');
            if (driversData.length === 0) {
                list.innerHTML = "<p class='text-center text-gray-500'>No drivers configured.</p>";
                return;
            }

            list.innerHTML = driversData.map(d => `
                <button onclick="selectDriver('${d.id}')" class="flex items-center gap-4 p-4 rounded-2xl bg-gray-900 border border-gray-800 active:bg-gray-800 active:border-gray-700 transition-all shadow-lg text-left w-full">
                    <div class="w-14 h-14 rounded-full flex items-center justify-center font-black text-2xl border-4 shadow-inner bg-gray-800" style="border-color: ${d.color_code}; color: ${d.color_code}">
                        ${d.name.charAt(0).toUpperCase()}
                    </div>
                    <div>
                        <div class="text-xl font-bold text-white">${d.name}</div>
                        <div class="text-sm text-gray-400 font-medium">${d.group} driver</div>
                    </div>
                </button>
            `).join('');
        }

        async function selectDriver(driverId) {
            selectedDriverId = driverId;
            localStorage.setItem('chauffeur_driver_id', driverId);
            
            const d = driversData.find(d => d.id === driverId);
            if (d) {
                document.getElementById('driver-name').textContent = d.name;
                document.getElementById('driver-avatar').textContent = d.name.charAt(0).toUpperCase();
                document.getElementById('driver-avatar').style.borderColor = d.color_code;
                document.getElementById('driver-avatar').style.color = d.color_code;
            }

            document.getElementById('screen-select-driver').classList.add('hidden');
            document.getElementById('screen-schedule').classList.remove('hidden');
            document.getElementById('btn-switch-driver').classList.remove('hidden');
            
            await fetchData();
        }

        function clearDriver() {
            selectedDriverId = null;
            localStorage.removeItem('chauffeur_driver_id');
            showDriverSelection();
        }

        async function fetchData() {
            const btnSync = document.getElementById('btn-sync');
            btnSync.classList.add('animate-spin');
            
            try {
                const res = await fetch('api/schedule');
                scheduleData = await res.json();
                buildTimeline();
            } catch (e) {
                console.error("Failed to fetch schedule", e);
                document.getElementById('days-container').innerHTML = `<div class="w-full flex items-center justify-center text-red-400">Failed to load data</div>`;
            } finally {
                setTimeout(() => btnSync.classList.remove('animate-spin'), 500);
            }
        }

        function formatTime(isoStr) {
            return new Date(isoStr).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
        }
        
        function formatDuration(mins) {
            if (mins < 60) return `${mins}m`;
            const h = Math.floor(mins/60);
            const m = mins % 60;
            return m > 0 ? `${h}h ${m}m` : `${h}h`;
        }

        function openActionSheet(origin, destination, legTitle, waypoint = null) {
            routeContext = { origin, destination, waypoint };
            document.getElementById('sheet-subtitle').textContent = legTitle;
            
            const sheet = document.getElementById('action-sheet');
            const content = document.getElementById('action-sheet-content');
            sheet.classList.remove('hidden');
            sheet.style.display = 'flex';
            
            // Trigger reflow
            void sheet.offsetWidth;
            
            sheet.classList.remove('opacity-0');
            content.classList.remove('translate-y-full');
        }

        function closeActionSheet() {
            const sheet = document.getElementById('action-sheet');
            const content = document.getElementById('action-sheet-content');
            
            sheet.classList.add('opacity-0');
            content.classList.add('translate-y-full');
            
            setTimeout(() => {
                sheet.classList.add('hidden');
                sheet.style.display = 'none';
                routeContext = null;
            }, 300);
        }

        function openMaps(provider) {
            if (!routeContext) return;
            const originEnc = routeContext.origin ? `&origin=${encodeURIComponent(routeContext.origin)}` : '';
            const destEnc = encodeURIComponent(routeContext.destination);
            
            let url = '';
            if (provider === 'google') {
                url = `https://www.google.com/maps/dir/?api=1${originEnc}&destination=${destEnc}`;
            } else if (provider === 'apple') {
                url = `http://maps.apple.com/?daddr=${destEnc}${routeContext.origin ? `&saddr=${encodeURIComponent(routeContext.origin)}` : ''}`;
            } else if (provider === 'waze') {
                url = `https://waze.com/ul?q=${destEnc}&navigate=yes`;
            }
            
            closeActionSheet();
            window.location.href = url;
        }

        function openEventModal(titleStr) {
            const ev = JSON.parse(decodeURIComponent(titleStr));
            document.getElementById('em-title').textContent = ev.title;
            document.getElementById('em-time').textContent = ev.timeStr;
            document.getElementById('em-location').textContent = ev.location || 'No location provided';
            document.getElementById('em-passengers').innerHTML = ev.passengerHtml || '<span class="text-gray-500 italic">None</span>';
            
            const mapBtn = document.getElementById('em-map-btn');
            if (ev.location) {
                mapBtn.style.display = 'flex';
                mapBtn.onclick = () => {
                    closeEventModal();
                    setTimeout(() => openActionSheet('', ev.location, 'Map to Event'), 300);
                };
            } else {
                mapBtn.style.display = 'none';
            }
            
            const modal = document.getElementById('event-modal');
            const content = document.getElementById('event-modal-content');
            modal.classList.remove('hidden');
            modal.style.display = 'flex';
            void modal.offsetWidth; // trigger reflow
            modal.classList.remove('opacity-0');
            content.classList.remove('translate-y-full');
            content.classList.remove('sm:scale-95');
        }

        function closeEventModal() {
            const modal = document.getElementById('event-modal');
            const content = document.getElementById('event-modal-content');
            modal.classList.add('opacity-0');
            content.classList.add('translate-y-full');
            content.classList.add('sm:scale-95');
            setTimeout(() => {
                modal.classList.add('hidden');
                modal.style.display = 'none';
            }, 300);
        }

        function renderLegPill(timeStr, title, mins, delayMins, actionArgs, colorTheme = 'blue', subtitleHtml = '') {
            const iconSvg = colorTheme === 'blue' 
                ? `<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M18.92 6.01C18.72 5.42 18.16 5 17.5 5h-11c-.66 0-1.21.42-1.42 1.01L3 12v8c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h12v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-8l-2.08-5.99zM6.85 7h10.29l1.08 3.11H5.77L6.85 7zM19 17H5v-5h14v5zM7.5 16c.83 0 1.5-.67 1.5-1.5S8.33 13 7.5 13 6 13.67 6 14.5 6.67 16 7.5 16z"/></svg>`
                : `<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>`;
            
            const colorClassBg = colorTheme === 'blue' ? 'bg-blue-900' : 'bg-green-900';
            const colorClassText = colorTheme === 'blue' ? 'text-blue-300' : 'text-green-300';
            const timeColorClassText = colorTheme === 'blue' ? 'text-blue-400' : 'text-green-400';
            const durationClassText = colorTheme === 'blue' ? 'text-blue-500' : 'text-green-500';

            const timeLabel = colorTheme === 'blue' ? 'Leave at' : 'Arrive by';

            return `
                <div class="flex items-start mb-6 relative z-10 group cursor-pointer" onclick="openActionSheet(${actionArgs})">
                    <div class="w-10 h-10 rounded-full ${colorClassBg} border-4 border-gray-950 flex items-center justify-center shrink-0 shadow-md ${colorClassText}">
                        ${iconSvg}
                    </div>
                    <div class="ml-4 flex-1 bg-gray-900 border border-gray-800 rounded-xl p-4 shadow-sm active:bg-gray-800 transition-colors">
                        <div class="text-sm font-bold ${timeColorClassText} mb-1 uppercase tracking-wider">${timeLabel} ${timeStr}</div>
                        <div class="text-white font-medium text-lg leading-tight mb-2">${title}</div>
                        ${subtitleHtml ? `<div class="flex flex-wrap gap-1 mb-2">${subtitleHtml}</div>` : ''}
                        <div class="flex items-center text-xs font-mono text-gray-400 bg-gray-950 inline-flex px-2 py-1 rounded">
                            <span class="${durationClassText}">${formatDuration(mins)}</span>
                            ${delayMins > 3 ? `<span class="ml-2 text-yellow-500 font-bold">⚠ +${delayMins}m</span>` : ''}
                        </div>
                    </div>
                </div>
            `;
        }

        function buildTimeline() {
            const container = document.getElementById('days-container');
            const dId = selectedDriverId;
            if (!scheduleData || !dId) return;

            const { events, assignments, ghost_assignments, route_edges, initial_edges, final_edges } = scheduleData;
            
            const myEvents = events.filter(ev => {
                const assigned = (assignments && assignments[ev.id]) || (ghost_assignments && ghost_assignments[ev.id]);
                if (assigned === dId) return true;
                if (scheduleData.driver_events && scheduleData.driver_events[dId] && scheduleData.driver_events[dId].includes(ev.id)) return true;
                return false;
            });

            const byDate = {};
            myEvents.forEach(ev => {
                const dStr = new Date(ev.start).toLocaleDateString('en-CA');
                if (!byDate[dStr]) byDate[dStr] = [];
                byDate[dStr].push(ev);
            });

            currentDates = [];
            let startDate = new Date();
            startDate.setHours(0,0,0,0);
            
            const sortedAvailableDates = Object.keys(byDate).sort();
            if (sortedAvailableDates.length > 0) {
                const firstEvDate = new Date(sortedAvailableDates[0] + 'T00:00:00');
                if (firstEvDate > startDate) {
                    startDate = firstEvDate;
                }
            }

            const daysToShow = scheduleData.settings ? scheduleData.settings.days_to_show : 7;
            for (let i=0; i<daysToShow; i++) {
                const d = new Date(startDate);
                d.setDate(d.getDate() + i);
                currentDates.push(d.toLocaleDateString('en-CA'));
            }

            container.innerHTML = '';
            
            currentDates.forEach((dateStr, index) => {
                const evs = byDate[dateStr] || [];
                evs.sort((a, b) => new Date(a.start) - new Date(b.start));

                const pane = document.createElement('div');
                pane.className = "min-w-full w-full h-full snap-center overflow-y-auto px-4 py-6";
                pane.id = `pane-${index}`;

                if (evs.length === 0) {
                    pane.innerHTML = `
                        <div class="flex flex-col items-center justify-center h-full opacity-50 text-center">
                            <div class="text-6xl mb-4">☕</div>
                            <h3 class="text-xl font-bold mb-2">No Drives Scheduled</h3>
                            <p class="text-gray-400">Enjoy your free time!</p>
                        </div>
                    `;
                    container.appendChild(pane);
                    return;
                }

                let html = '<div class="flex flex-col relative before:absolute before:left-[19px] before:top-4 before:bottom-4 before:w-1 before:bg-gray-800 before:z-0">';
                
                const driverConfig = driversData.find(d => d.id === dId) || {};
                const globalHome = scheduleData.home_location || '';
                const calendar_metadata = scheduleData.calendar_metadata || {};

                function getPassengerBadges(eventObj) {
                    const calMetas = eventObj.calendar_ids.map(c => calendar_metadata[c] || { backgroundColor: '#3B82F6', summary: 'Passenger' });
                    return calMetas.map(meta => `<span class="px-2 py-0.5 text-[10px] font-bold rounded-full border border-gray-600 truncate max-w-[80px]" style="background-color: ${meta.backgroundColor}20; color: ${meta.backgroundColor}; border-color: ${meta.backgroundColor}50;" title="${meta.summary}">${meta.summary}</span>`).join('');
                }
                
                evs.forEach((ev, evIdx) => {
                    const isDriverOnly = !(assignments && assignments[ev.id]) && !(ghost_assignments && ghost_assignments[ev.id]);
                    
                    // --- Initial Edge ---
                    if (evIdx === 0 && !isDriverOnly) {
                        const edge = initial_edges[ev.id];
                        if (edge && edge.travel_mins > 0) {
                            const originLocation = driverConfig.home_location || globalHome;
                            const destinationLocation = ev.location;
                            const depTime = new Date(new Date(ev.start).getTime() - (edge.travel_mins + 5) * 60000);
                            const badges = getPassengerBadges(ev);
                            
                            if (edge.pickup_waypoint) {
                                const leg1Mins = edge.pickup_waypoint.from_driver_home_mins;
                                const leg2Mins = edge.pickup_waypoint.from_global_home_mins;
                                const leg2DepTime = new Date(depTime.getTime() + leg1Mins * 60000);
                                
                                let args1 = `'${originLocation.replace(/'/g, "\\'")}', '${globalHome.replace(/'/g, "\\'")}', 'Drive to Pickup'`;
                                html += renderLegPill(formatTime(depTime.toISOString()), "Drive to Pickup", leg1Mins, 0, args1, 'blue', badges);
                                
                                let args2 = `'${globalHome.replace(/'/g, "\\'")}', '${destinationLocation.replace(/'/g, "\\'")}', 'Drive to ${destinationLocation.split(',')[0].replace(/'/g, "\\'")}'`;
                                html += renderLegPill(formatTime(leg2DepTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, leg2Mins, edge.delay_mins, args2, 'blue');
                            } else {
                                let args = `'${originLocation.replace(/'/g, "\\'")}', '${destinationLocation.replace(/'/g, "\\'")}', 'Drive to ${destinationLocation.split(',')[0].replace(/'/g, "\\'")}'`;
                                html += renderLegPill(formatTime(depTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, edge.travel_mins, edge.delay_mins, args, 'blue', badges);
                            }
                        }
                    }

                    // --- Event ---
                    let bgColor = isDriverOnly ? 'bg-gray-800/50 border-gray-700 border-dashed border' : 'bg-gray-800 border-gray-700 border';
                    let titleClass = isDriverOnly ? 'text-gray-400' : 'text-white';
                    const badges = getPassengerBadges(ev);
                    
                    const eventData = {
                        title: ev.title,
                        timeStr: `${formatTime(ev.start)} - ${formatTime(ev.end)}`,
                        location: ev.location,
                        passengerHtml: badges
                    };
                    const evDataStr = encodeURIComponent(JSON.stringify(eventData));

                    html += `
                        <div class="flex items-start mb-6 relative z-10 group cursor-pointer" onclick="openEventModal('${evDataStr.replace(/'/g, "\\'")}')">
                            <div class="w-10 h-10 rounded-full bg-gray-700 border-4 border-gray-950 flex items-center justify-center shrink-0 shadow-md text-white font-bold text-xs" style="background-color: ${driverConfig.color_code || '#4a5568'}">
                                ${formatTime(ev.start).split(':')[0]}
                            </div>
                            <div class="ml-4 flex-1 ${bgColor} rounded-xl p-4 shadow-sm active:bg-gray-800 transition-colors">
                                <div class="text-sm font-bold text-gray-400 mb-1">${formatTime(ev.start)} - ${formatTime(ev.end)}</div>
                                <div class="${titleClass} font-bold text-xl leading-tight mb-2">${ev.title}</div>
                                ${badges ? `<div class="flex flex-wrap gap-1 mb-2">${badges}</div>` : ''}
                                ${ev.location ? `<div class="text-sm text-gray-500 flex items-start gap-1"><svg class="w-4 h-4 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"></path></svg><span class="break-words line-clamp-2">${ev.location}</span></div>` : ''}
                            </div>
                        </div>
                    `;

                    // --- Routing Edge ---
                    if (!isDriverOnly && evIdx < evs.length - 1 && route_edges[ev.id]) {
                        const edge = route_edges[ev.id];
                        const nextEv = evs[evIdx + 1];
                        
                        let computedOrigin = ev.location;
                        const destinationLocation = nextEv.location;
                        const nextBadges = getPassengerBadges(nextEv);

                        if (edge.home_waypoint) {
                            const leg1Mins = edge.home_waypoint.to_home_mins;
                            const leg2Mins = edge.home_waypoint.from_home_mins;
                            const leg2DepTime = new Date(new Date(ev.end).getTime() + (leg1Mins + edge.home_waypoint.layover_mins) * 60000);
                            
                            let args1 = `'${computedOrigin.replace(/'/g, "\\'")}', '${globalHome.replace(/'/g, "\\'")}', 'Drive to Dropoff/Pickup'`;
                            html += renderLegPill(formatTime(ev.end), "Drive to Dropoff/Pickup", leg1Mins, 0, args1, 'blue');
                            
                            let args2 = `'${globalHome.replace(/'/g, "\\'")}', '${destinationLocation.replace(/'/g, "\\'")}', 'Drive to ${destinationLocation.split(',')[0].replace(/'/g, "\\'")}'`;
                            html += renderLegPill(formatTime(leg2DepTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, leg2Mins, edge.delay_mins, args2, 'blue', nextBadges);
                        } else if (edge.pickup_waypoint) {
                            const leg1Mins = edge.pickup_waypoint.to_pickup_mins;
                            const leg2Mins = edge.pickup_waypoint.from_pickup_mins;
                            const leg2DepTime = new Date(new Date(ev.end).getTime() + leg1Mins * 60000);
                            
                            let args1 = `'${computedOrigin.replace(/'/g, "\\'")}', '${globalHome.replace(/'/g, "\\'")}', 'Drive to Pickup'`;
                            html += renderLegPill(formatTime(ev.end), "Drive to Pickup", leg1Mins, 0, args1, 'blue', nextBadges);
                            
                            let args2 = `'${globalHome.replace(/'/g, "\\'")}', '${destinationLocation.replace(/'/g, "\\'")}', 'Drive to ${destinationLocation.split(',')[0].replace(/'/g, "\\'")}'`;
                            html += renderLegPill(formatTime(leg2DepTime.toISOString()), `Drive to ${destinationLocation.split(',')[0]}`, leg2Mins, edge.delay_mins, args2, 'blue');
                        } else {
                            let destStr = destinationLocation ? destinationLocation.split(',')[0] : 'Next Event';
                            let args = `'${(computedOrigin || '').replace(/'/g, "\\'")}', '${(destinationLocation || '').replace(/'/g, "\\'")}', 'Drive to ${destStr.replace(/'/g, "\\'")}'`;
                            html += renderLegPill(formatTime(ev.end), `Drive to ${destStr}`, edge.travel_mins, edge.delay_mins, args, 'blue', nextBadges);
                        }
                    }

                    // --- Final Edge ---
                    if (evIdx === evs.length - 1 && !isDriverOnly) {
                        const edge = final_edges[ev.id];
                        if (edge && edge.travel_mins > 0) {
                            const arriveDate = new Date(new Date(ev.end).getTime() + edge.travel_mins * 60000);
                            const originLocation = ev.location;
                            const destinationLocation = driverConfig.home_location || globalHome;
                            const badges = getPassengerBadges(ev);
                            
                            if (edge.dropoff_waypoint) {
                                const leg1Mins = edge.dropoff_waypoint.to_global_home_mins;
                                const leg2Mins = edge.dropoff_waypoint.to_driver_home_mins;
                                const leg2DepTime = new Date(new Date(ev.end).getTime() + leg1Mins * 60000);
                                const leg2ArrTime = arriveDate;
                                
                                let args1 = `'${originLocation.replace(/'/g, "\\'")}', '${globalHome.replace(/'/g, "\\'")}', 'Drive to Dropoff'`;
                                html += renderLegPill(formatTime(leg2DepTime.toISOString()), "Drive to Dropoff", leg1Mins, 0, args1, 'green', badges);
                                
                                let args2 = `'${globalHome.replace(/'/g, "\\'")}', '${destinationLocation.replace(/'/g, "\\'")}', 'Drive Home'`;
                                html += renderLegPill(formatTime(leg2ArrTime.toISOString()), "Drive Home", leg2Mins, edge.delay_mins, args2, 'green');
                            } else {
                                let args = `'${(originLocation || '').replace(/'/g, "\\'")}', '${(destinationLocation || '').replace(/'/g, "\\'")}', 'Drive Home'`;
                                html += renderLegPill(formatTime(arriveDate.toISOString()), "Drive Home", edge.travel_mins, edge.delay_mins, args, 'green', badges);
                            }
                        }
                    }
                });

                html += '</div>';
                pane.innerHTML = html;
                container.appendChild(pane);
            });

            updateHeaderDate();

            // Set up scroll snapping logic
            container.addEventListener('scroll', () => {
                const scrollLeft = container.scrollLeft;
                const paneWidth = container.clientWidth;
                const idx = Math.round(scrollLeft / paneWidth);
                if (idx !== activeDateIndex) {
                    activeDateIndex = idx;
                    updateHeaderDate();
                }
            });
        }

        function updateHeaderDate() {
            if (currentDates.length === 0) return;
            const dStr = currentDates[activeDateIndex];
            
            const today = new Date();
            const tomorrow = new Date();
            tomorrow.setDate(today.getDate() + 1);
            
            const todayStr = today.toLocaleDateString('en-CA');
            const tomorrowStr = tomorrow.toLocaleDateString('en-CA');
            
            let label = "";
            let subLabel = "";
            const options = { weekday: 'long', month: 'short', day: 'numeric' };
            const dDate = new Date(dStr + 'T12:00:00');
            
            if (dStr === todayStr) {
                label = "Today";
            } else if (dStr === tomorrowStr) {
                label = "Tomorrow";
            } else {
                label = dDate.toLocaleDateString(undefined, options);
            }
            
            document.getElementById('current-day-label').textContent = label;
            document.getElementById('date-subtitle').textContent = dDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
            
            document.getElementById('btn-prev-day').disabled = activeDateIndex === 0;
            document.getElementById('btn-next-day').disabled = activeDateIndex === currentDates.length - 1;
        }

        function prevDay() {
            if (activeDateIndex > 0) {
                const container = document.getElementById('days-container');
                const paneWidth = container.clientWidth;
                container.scrollBy({ left: -paneWidth, behavior: 'smooth' });
            }
        }

        function nextDay() {
            if (activeDateIndex < currentDates.length - 1) {
                const container = document.getElementById('days-container');
                const paneWidth = container.clientWidth;
                container.scrollBy({ left: paneWidth, behavior: 'smooth' });
            }
        }

        window.onload = init;
    