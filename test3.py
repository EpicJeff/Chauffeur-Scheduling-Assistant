function renderSchedule(data, options = {}) {
            if (!data) data = {};
            const {
                targetContainerId = 'schedule-container',
                isModal = false,
                dateFilter = null,
                isPagination = false
            } = options;

            const {
                events = [],
                assignments = {},
                ghost_assignments = {},
                unassigned = [],
                no_location = [],
                calendar_metadata = {},
                overridden_events = [],
                lateness_warnings = [],
                scheduled_errands = []
            } = data;

            let localEvents = [...events];
            let localAssignments = { ...assignments };
            let localRouteEdges = JSON.parse(JSON.stringify(data.route_edges || {}));
            let localInitialEdges = JSON.parse(JSON.stringify(initialEdges || {}));
            let localFinalEdges = JSON.parse(JSON.stringify(finalEdges || {}));

            if (window.showErrands && scheduled_errands && scheduled_errands.length > 0) {
                scheduled_errands.forEach(errand => {
                    errand.start = errand.start_time;
                    errand.end = errand.end_time;
                    errand.event_type = 'errand';
                    localEvents.push(errand);
                    localAssignments[errand.id] = errand.driver.id;

                    // Patch route edges for drive time pills
                    const d_id = errand.driver.id;
                    if (!localRouteEdges[d_id]) localRouteEdges[d_id] = {};
                    if (!localInitialEdges[d_id]) localInitialEdges[d_id] = {};
                    if (!localFinalEdges[d_id]) localFinalEdges[d_id] = {};

                    const e1_id = errand.inserted_after_event_id;
                    const e2_id = errand.inserted_before_event_id;

                    if (e1_id === null && e2_id === null) {
                        // Only event of the day
                        localInitialEdges[d_id][errand.id] = {
                            to_event: errand.id,
                            travel_mins: errand.travel_to_mins,
                            delay_mins: 0
                        };
                        localFinalEdges[d_id][errand.id] = {
                            from_event: errand.id,
                            travel_mins: errand.travel_from_mins,
                            delay_mins: 0
                        };
                    } else if (e1_id === null) {
                        // Before first event
                        localInitialEdges[d_id][errand.id] = {
                            to_event: errand.id,
                            travel_mins: errand.travel_to_mins,
                            delay_mins: 0
                        };
                        delete localInitialEdges[d_id][e2_id];

                        localRouteEdges[d_id][errand.id] = {
                            from_event: errand.id,
                            to_event: e2_id,
                            travel_mins: errand.travel_from_mins,
                            delay_mins: 0
                        };
                    } else if (e2_id === null) {
                        // After last event
                        localFinalEdges[d_id][errand.id] = {
                            from_event: errand.id,
                            travel_mins: errand.travel_from_mins,
                            delay_mins: 0
                        };
                        delete localFinalEdges[d_id][e1_id];

                        localRouteEdges[d_id][e1_id] = {
                            from_event: e1_id,
                            to_event: errand.id,
                            travel_mins: errand.travel_to_mins,
                            delay_mins: 0
                        };
                    } else {
                        // Between events
                        if (localRouteEdges[d_id][e1_id]) {
                            localRouteEdges[d_id][e1_id] = {
                                from_event: e1_id,
                                to_event: errand.id,
                                travel_mins: errand.travel_to_mins,
                                delay_mins: 0
                            };
                        }

                        localRouteEdges[d_id][errand.id] = {
                            from_event: errand.id,
                            to_event: e2_id,
                            travel_mins: errand.travel_from_mins,
                            delay_mins: 0
                        };
                    }
                });
            }

            if (!isModal) {
                // --- Inbox Logic ---
                let triageEvents = events.filter(e => e.needs_triage);

                // Group recurring events
                const seriesGrouped = {};
                const deduplicatedTriageEvents = [];
                for (const ev of triageEvents) {
                    if (ev.recurring_event_id) {
                        if (!seriesGrouped[ev.recurring_event_id]) {
                            seriesGrouped[ev.recurring_event_id] = {
                                ...ev,
                                is_series_grouped: true,
                                series_count: 1
                            };
                            deduplicatedTriageEvents.push(seriesGrouped[ev.recurring_event_id]);
                        } else {
                            seriesGrouped[ev.recurring_event_id].series_count++;
                        }
                    } else {
                        deduplicatedTriageEvents.push(ev);
                    }
                }

                triageEvents = deduplicatedTriageEvents;

                const inboxContainer = document.getElementById('inbox-container');
                const inboxList = document.getElementById('inbox-list');
                const inboxCount = document.getElementById('inbox-count');

                if (triageEvents.length > 0 && !isKiosk) {
                    inboxCount.textContent = triageEvents.length;
                    inboxContainer.classList.remove('hidden');
                    inboxList.innerHTML = triageEvents.map(ev => {
                        const calMetas = (ev.calendar_ids || []).map(c => calendar_metadata && calendar_metadata[c] ? calendar_metadata[c] : { backgroundColor: '#3B82F6', summary: 'Calendar' });
                        const evColor = calMetas.length > 0 ? calMetas[0].backgroundColor : '#3B82F6';

                        const seriesBadge = ev.is_series_grouped && ev.series_count > 1 ? `<span class="bg-indigo-900/50 text-indigo-300 text-[10px] font-bold uppercase px-2 py-0.5 rounded ml-2 border border-indigo-700/50 shrink-0">Series (${ev.series_count})</span>` : '';

                        return `
                        <div onclick="openEventModal('${ev.id}')" class="bg-gray-800 border border-red-500/50 rounded-xl p-4 cursor-pointer hover:bg-gray-700 transition shadow-lg relative overflow-hidden group">
                            <div class="absolute left-0 top-0 bottom-0 w-1.5" style="background-color: ${evColor}"></div>
                            <div class="pl-2">
                                <h3 class="font-bold text-white text-lg truncate group-hover:text-blue-300 transition flex items-center">
                                    <span>${ev.title || '(No Title)'}</span>
                                    ${seriesBadge}
                                </h3>
                                <p class="text-sm text-gray-400 mt-1">${formatDateStr(ev.start)} • ${formatTime(ev.start)}</p>
                                <div class="mt-3 flex items-center justify-between">
                                    <span class="text-xs font-bold uppercase tracking-wider text-red-400 bg-red-900/30 px-2 py-1 rounded-md">Needs Setup</span>
                                