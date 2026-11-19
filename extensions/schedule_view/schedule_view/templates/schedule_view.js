/* Schedule View — full-page dashboard */
(function () {
  "use strict";

  var API_BASE = "/plugin-io/api/schedule_view/schedule";

  // ── DOM refs ───────────────────────────────────────────────
  var datePicker        = document.getElementById("date-picker");
  var dateDisplay       = document.getElementById("date-display");
  var btnPrev           = document.getElementById("btn-prev");
  var btnNext           = document.getElementById("btn-next");
  var btnToday          = document.getElementById("btn-today");
  var btnRefresh        = document.getElementById("btn-refresh");
  var msProvider        = document.getElementById("ms-provider");
  var msLocation        = document.getElementById("ms-location");
  var statusBar         = document.getElementById("status-bar");
  var statsText         = document.getElementById("stats-text");
  var loadingState      = document.getElementById("loading-state");
  var emptyState        = document.getElementById("empty-state");
  var scheduleGrid      = document.getElementById("schedule-grid");
  var appointmentsTable = document.getElementById("appointments-table");
  var monthViewEl       = document.getElementById("month-view");
  var monthGridHeader   = document.getElementById("month-grid-header");
  var monthGridBody     = document.getElementById("month-grid-body");
  var weekViewEl        = document.getElementById("week-view");
  var weekGridHeader    = document.getElementById("week-grid-header");
  var weekGridBody      = document.getElementById("week-grid-body");
  var btnViewDay        = document.getElementById("btn-view-day");
  var btnViewWeek       = document.getElementById("btn-view-week");
  var btnViewMonth      = document.getElementById("btn-view-month");
  var btnTypeAll        = document.getElementById("btn-type-all");
  var btnTypeProviders  = document.getElementById("btn-type-providers");
  var btnTypeRooms      = document.getElementById("btn-type-rooms");
  var btnTypeLocations  = document.getElementById("btn-type-locations");
  var modalOverlay      = document.getElementById("appt-modal-overlay");

  // ── Sticky filter persistence (localStorage) ────────────────
  var STORAGE_KEY_PREFIX = "schedule_view_";

  function loadStored(key, fallback) {
    try {
      var raw = localStorage.getItem(STORAGE_KEY_PREFIX + key);
      return raw !== null ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  }

  function storeValue(key, value) {
    try { localStorage.setItem(STORAGE_KEY_PREFIX + key, JSON.stringify(value)); }
    catch (e) { /* quota exceeded or private mode — ignore */ }
  }

  // ── State ──────────────────────────────────────────────────
  var currentDate       = loadStored("date", toISODate(new Date()));
  var currentView       = loadStored("view", "day");   // "day" | "week" | "month"
  var allAppointments   = [];
  var calendarBlocks    = [];   // availability + busy blocks from Calendar Events
  var providers         = [];
  var locations         = [];
  var availableLabels   = [];  // fetched once from /labels
  var allPracticeLocations = [];  // all active locations from the instance
  var allRoomStaff = [];          // all RR (room resource) staff from the instance
  var allProviderStaff = [];      // all non-room providers from the instance
  var scheduleTypeFilter = loadStored("scheduleType", "providers");  // "all" | "providers" | "rooms" | "locations"

  // Multi-select filter state: arrays of selected IDs (empty = all)
  var selectedProviders = loadStored("selectedProviders", []);
  var selectedLocations = loadStored("selectedLocations", []);

  // Month view: cache of { "YYYY-MM-DD": count } fetched so far
  var monthCountCache   = {};
  // The YYYY-MM currently rendered in month view
  var renderedMonth     = "";

  // ── Type color palette ─────────────────────────────────────
  var TYPE_PALETTE = [
    ["#2563eb", "#dbeafe", "#1e40af"],  // blue
    ["#16a34a", "#dcfce7", "#14532d"],  // green
    ["#7c3aed", "#ede9fe", "#4c1d95"],  // purple
    ["#ea580c", "#ffedd5", "#9a3412"],  // orange
    ["#0d9488", "#ccfbf1", "#134e4a"],  // teal
    ["#a855f7", "#f5f3ff", "#6b21a8"],  // violet
    ["#d97706", "#fef3c7", "#78350f"],  // amber
    ["#4338ca", "#e0e7ff", "#312e81"],  // indigo
    ["#64748b", "#f1f5f9", "#334155"],  // slate
    ["#0891b2", "#cffafe", "#155e75"],  // cyan
  ];

  function typeColorIndex(typeName) {
    if (!typeName) return 0;
    var h = 0;
    for (var i = 0; i < typeName.length; i++) {
      h = (h * 31 + typeName.charCodeAt(i)) & 0xfffffff;
    }
    return h % TYPE_PALETTE.length;
  }

  function typeColors(typeName) {
    return TYPE_PALETTE[typeColorIndex(typeName)];
  }

  // ── Time grid scaling ───────────────────────────────────────
  // Compute px-per-minute so the grid fills the available viewport height.
  // Falls back to 1 if the viewport can't be measured.
  var PX_PER_MIN = 1;

  function computePxPerMin(bounds) {
    // Available height = viewport minus toolbar, stats bar, column headers, padding
    var overhead = 52 + 36 + 40 + 40; // toolbar + stats + col header + padding
    var available = window.innerHeight - overhead;
    if (available < 200) available = 200;
    var totalMinutes = (bounds.endMin - bounds.startMin) || 540;
    return Math.max(available / totalMinutes, 1);
  }

  function minutesFromMidnight(isoString) {
    var d = new Date(isoString);
    return d.getHours() * 60 + d.getMinutes();
  }

  function formatLocalTime(isoString) {
    if (!isoString) return "";
    var d = new Date(isoString);
    var h = d.getHours();
    var m = d.getMinutes();
    var ampm = h >= 12 ? "PM" : "AM";
    var h12 = h % 12 || 12;
    return h12 + ":" + (m < 10 ? "0" : "") + m + " " + ampm;
  }

  var _cfg = window.__SCHEDULE_CONFIG || {};
  var GRID_START_HOUR = _cfg.gridStartHour != null ? _cfg.gridStartHour : 7;
  var GRID_END_HOUR   = _cfg.gridEndHour   != null ? _cfg.gridEndHour   : 18;

  function computeGridBounds(appointments) {
    var earliest = GRID_START_HOUR * 60;
    var latest   = GRID_END_HOUR * 60;
    var firstApptMin = null;
    appointments.forEach(function (a) {
      if (!a.start_time) return;
      var s = minutesFromMidnight(a.start_time);
      var e = s + (a.duration_minutes || 15);
      if (firstApptMin === null || s < firstApptMin) firstApptMin = s;
      // Extend grid bounds to show any appointment outside the configured window
      if (s < earliest) earliest = Math.floor(s / 60) * 60;
      if (e > latest)   latest   = Math.ceil(e / 60) * 60;
    });
    // Also extend to current time if viewing today
    var now = new Date();
    if (currentDate === toISODate(now)) {
      var nowMin = now.getHours() * 60 + now.getMinutes();
      if (nowMin > latest) latest = Math.ceil(nowMin / 60) * 60;
    }
    return { startMin: earliest, endMin: latest, firstApptMin: firstApptMin };
  }

  function computeOverlapLayout(appointments) {
    // Use visual end (accounting for min card height) to detect overlaps
    var minHeightMinutes = Math.ceil(30 / PX_PER_MIN);
    var items = appointments
      .filter(function (a) { return a.start_time; })
      .map(function (a) {
        var s = minutesFromMidnight(a.start_time);
        var dur = a.duration_minutes || 15;
        var visualEnd = s + Math.max(dur, minHeightMinutes);
        return { id: a.id, start: s, end: visualEnd, isScheduleEvent: !!a.is_schedule_event };
      })
      .sort(function (a, b) {
        if (a.start !== b.start) return a.start - b.start;
        // Provider appointments left, room schedule events right
        if (a.isScheduleEvent !== b.isScheduleEvent) return a.isScheduleEvent ? 1 : -1;
        return (b.end - b.start) - (a.end - a.start);
      });

    var groups = [];
    var group  = [];
    var groupEnd = -1;

    items.forEach(function (item) {
      if (group.length && item.start >= groupEnd) {
        groups.push(group);
        group = [];
        groupEnd = -1;
      }
      group.push(item);
      if (item.end > groupEnd) groupEnd = item.end;
    });
    if (group.length) groups.push(group);

    var layout = {};
    groups.forEach(function (g) {
      var columns = [];
      g.forEach(function (item) {
        var placed = false;
        for (var c = 0; c < columns.length; c++) {
          if (item.start >= columns[c]) {
            columns[c] = item.end;
            layout[item.id] = { col: c };
            placed = true;
            break;
          }
        }
        if (!placed) {
          layout[item.id] = { col: columns.length };
          columns.push(item.end);
        }
      });
      var total = columns.length;
      g.forEach(function (item) {
        layout[item.id].total = total;
      });
    });

    return layout;
  }

  function buildTimeGrid(appointments, bounds) {
    PX_PER_MIN = computePxPerMin(bounds);

    var grid = document.createElement("div");
    grid.className = "time-grid";

    var totalMinutes = bounds.endMin - bounds.startMin;
    var totalHeight  = totalMinutes * PX_PER_MIN;

    // Time gutter
    var gutter = document.createElement("div");
    gutter.className = "time-gutter";
    gutter.style.height = totalHeight + "px";

    for (var m = bounds.startMin; m <= bounds.endMin; m += 60) {
      var label = document.createElement("div");
      label.className = "time-gutter-label";
      label.style.top = ((m - bounds.startMin) * PX_PER_MIN) + "px";
      label.textContent = formatHourLabel(m / 60);
      gutter.appendChild(label);
    }
    grid.appendChild(gutter);

    // Content area
    var content = document.createElement("div");
    content.className = "time-grid-content";
    content.style.height = totalHeight + "px";

    // Hour lines
    for (var h = bounds.startMin; h <= bounds.endMin; h += 60) {
      var line = document.createElement("div");
      line.className = "hour-line";
      line.style.top = ((h - bounds.startMin) * PX_PER_MIN) + "px";
      content.appendChild(line);
    }

    // Half-hour lines
    for (var hh = bounds.startMin + 30; hh < bounds.endMin; hh += 60) {
      var halfLine = document.createElement("div");
      halfLine.className = "half-hour-line";
      halfLine.style.top = ((hh - bounds.startMin) * PX_PER_MIN) + "px";
      content.appendChild(halfLine);
    }

    // Current time indicator
    var now    = new Date();
    var nowMin = now.getHours() * 60 + now.getMinutes();
    if (currentDate === toISODate(now) && nowMin >= bounds.startMin && nowMin <= bounds.endMin) {
      var nowLine = document.createElement("div");
      nowLine.className = "now-line";
      nowLine.style.top = ((nowMin - bounds.startMin) * PX_PER_MIN) + "px";
      content.appendChild(nowLine);
    }

    // Overlap layout
    var layout = computeOverlapLayout(appointments);

    // Render appointments
    appointments.forEach(function (appt) {
      if (!appt.start_time) return;
      var startMin = minutesFromMidnight(appt.start_time);
      var duration = appt.duration_minutes || 15;
      var info     = layout[appt.id] || { col: 0, total: 1 };

      var top      = (startMin - bounds.startMin) * PX_PER_MIN;
      var height   = Math.max(duration * PX_PER_MIN, 30);
      var col      = info.col;
      var total    = info.total || 1;
      var GAP      = 4;

      var card = buildGridAppt(appt, height);
      card.style.position = "absolute";
      card.style.top      = top + "px";
      card.style.minHeight = height + "px";

      // In column views, use percentage widths to fit the column
      var isColumnView = scheduleTypeFilter === "providers" || scheduleTypeFilter === "locations" || scheduleTypeFilter === "rooms";
      if (isColumnView) {
        var pct = (100 / total);
        card.style.left  = (col * pct) + "%";
        card.style.width = "calc(" + pct + "% - " + GAP + "px)";
      } else {
        var CARD_W = 180;
        card.style.left  = (col * (CARD_W + GAP)) + "px";
        card.style.width = CARD_W + "px";
      }

      content.appendChild(card);
    });

    grid.appendChild(content);
    return grid;
  }

  function buildGridAppt(appt, height) {
    var card = document.createElement("div");
    var blockClass = "";
    if (appt.is_calendar_block) {
      blockClass = appt.block_type === "available" ? " calendar-available" : " calendar-busy";
    } else if (appt.is_block) {
      blockClass = " schedule-block";
    }
    card.className = "grid-appt " + (appt.status_css || "status-unknown") +
      (appt.is_schedule_event ? " schedule-event" : "") + blockClass;

    // Type-based left border color + background tint
    if (appt.note_type_name) {
      var colors = typeColors(appt.note_type_name);
      card.style.borderLeftColor = colors[0];
      if (!appt.is_schedule_event && !appt.is_block && !appt.is_calendar_block) {
        card.style.backgroundColor = colors[1];
      }
    }

    // Card click → open appointment detail modal
    card.style.cursor = "pointer";
    card.title = appt.is_block ? "Schedule block" : "View appointment details";
    card.addEventListener("click", function (e) {
      e.stopPropagation();
      openAppointmentModal(appt);
    });

    // Patient name (or "Block" label for availability blocks)
    var nameEl = document.createElement("div");
    nameEl.className = "grid-appt-patient";
    nameEl.textContent = appt.is_block ? (appt.comment || "Block") : (appt.patient_name || "Unknown");
    card.appendChild(nameEl);

    var isCompact = height < 30;

    // Time + duration (use browser-local time to match grid positioning)
    var localTime = appt.start_time ? formatLocalTime(appt.start_time) : appt.start_display;
    var timeEl = document.createElement("div");
    timeEl.className = "grid-appt-time";
    timeEl.textContent = localTime + (appt.duration_minutes ? " \u00B7 " + appt.duration_minutes + "m" : "");
    card.appendChild(timeEl);

    // Appointment type
    if (appt.note_type_name) {
      var typeEl = document.createElement("div");
      typeEl.className = "grid-appt-type";
      typeEl.textContent = appt.note_type_name;
      card.appendChild(typeEl);
    }

    // Provider (or parent provider for schedule events / room bookings)
    var displayProvider = appt.provider_name;
    if (appt.is_schedule_event && appt.parent_provider_name) {
      displayProvider = appt.parent_provider_name;
    }
    if (displayProvider) {
      var provEl = document.createElement("div");
      provEl.className = "grid-appt-provider";
      provEl.textContent = displayProvider;
      card.appendChild(provEl);
    }

    // Appointment type on room cards (from parent appointment)
    if (appt.is_schedule_event && appt.parent_note_type_name) {
      var parentTypeEl = document.createElement("div");
      parentTypeEl.className = "grid-appt-type";
      parentTypeEl.textContent = appt.parent_note_type_name;
      card.appendChild(parentTypeEl);
    }

    // Patient name on room cards (from parent appointment)
    if (appt.is_schedule_event && appt.parent_patient_name) {
      var parentPatientEl = document.createElement("div");
      parentPatientEl.className = "grid-appt-patient-ref";
      parentPatientEl.textContent = appt.parent_patient_name;
      card.appendChild(parentPatientEl);
    }

    if (!isCompact) {
      // Room name (from linked schedule event)
      if (appt.room_name) {
        var roomEl = document.createElement("div");
        roomEl.className = "grid-appt-room";
        roomEl.textContent = "\uD83C\uDFE0 " + appt.room_name;
        card.appendChild(roomEl);
      }

      // Location / Room
      if (appt.location_name) {
        var locEl = document.createElement("div");
        locEl.className = "grid-appt-location";
        locEl.textContent = appt.location_name;
        card.appendChild(locEl);
      }

      // Labels (hidden for schedule events)
      if (!appt.is_schedule_event && appt.labels && appt.labels.length) {
        var labelsEl = document.createElement("div");
        labelsEl.className = "grid-appt-labels";
        appt.labels.forEach(function (lbl) {
          var chip = document.createElement("span");
          chip.className = "label-chip color-" + (lbl.color || "");
          chip.textContent = lbl.name;
          labelsEl.appendChild(chip);
        });
        card.appendChild(labelsEl);
      }

      // Comment (free text note on the appointment)
      if (appt.comment && !appt.is_block) {
        var commentEl = document.createElement("div");
        commentEl.className = "grid-appt-comment";
        commentEl.textContent = appt.comment;
        card.appendChild(commentEl);
      }

      // Status badge (hidden for schedule events)
      if (!appt.is_schedule_event && appt.status_label) {
        var statusRow = document.createElement("div");
        statusRow.className = "grid-appt-status-row";
        var badge = document.createElement("span");
        badge.className = "status-badge " + (appt.status_css || "status-unknown");
        badge.textContent = appt.status_label;
        statusRow.appendChild(badge);
        card.appendChild(statusRow);
      }
    }

    return card;
  }

  // ── Bootstrap ──────────────────────────────────────────────

  function init() {
    datePicker.value = currentDate;
    updateDateDisplay(currentDate);
    attachEvents();
    fetchAvailableLabels();

    // Restore persisted schedule type filter button
    var typeMap = { all: btnTypeAll, providers: btnTypeProviders, rooms: btnTypeRooms, locations: btnTypeLocations };
    var activeTypeBtn = typeMap[scheduleTypeFilter] || btnTypeAll;
    [btnTypeAll, btnTypeProviders, btnTypeRooms, btnTypeLocations].forEach(function (b) {
      b.classList.remove("active");
      b.setAttribute("aria-pressed", "false");
    });
    activeTypeBtn.classList.add("active");
    activeTypeBtn.setAttribute("aria-pressed", "true");

    // Immediately show persisted filter counts before data loads
    if (selectedProviders.length) {
      msProvider.querySelector(".multiselect-label").textContent =
        selectedProviders.length === 1 ? "1 selected" : selectedProviders.length + " selected";
    }
    if (selectedLocations.length) {
      msLocation.querySelector(".multiselect-label").textContent =
        selectedLocations.length === 1 ? "1 selected" : selectedLocations.length + " selected";
    }

    // Restore persisted view mode.
    // Always fetch provider/location lists first so dropdowns work in every view.
    // For day view, loadAppointments() does this. For week/month, we need a
    // lightweight fetch to populate allProviderStaff/allPracticeLocations/allRoomStaff.
    if (currentView !== "day") {
      fetch(API_BASE + "/appointments?date=" + encodeURIComponent(currentDate), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : {}; })
        .then(function (data) {
          allProviderStaff = data.all_providers || [];
          allPracticeLocations = data.all_locations || [];
          allRoomStaff = data.all_rooms || [];
          updateProviderFilter();
          updateLocationFilter();
        })
        .catch(function () {});
      switchView(currentView);
    } else {
      loadAppointments();
    }
  }

  function fetchAvailableLabels() {
    fetch(API_BASE + "/labels", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : { labels: [] }; })
      .then(function (data) { availableLabels = data.labels || []; })
      .catch(function () { availableLabels = []; });
  }

  function attachEvents() {
    btnPrev.addEventListener("click", function () {
      if (currentView === "month") {
        var d = new Date(currentDate + "T12:00:00");
        d.setDate(1);
        d.setMonth(d.getMonth() - 1);
        currentDate = toISODate(d);
      } else if (currentView === "week") {
        currentDate = addDays(currentDate, -7);
      } else {
        currentDate = addDays(currentDate, -1);
      }
      datePicker.value = currentDate;
      updateDateDisplay(currentDate);
      refreshCurrentView();
    });

    btnNext.addEventListener("click", function () {
      if (currentView === "month") {
        var d = new Date(currentDate + "T12:00:00");
        d.setDate(1);
        d.setMonth(d.getMonth() + 1);
        currentDate = toISODate(d);
      } else if (currentView === "week") {
        currentDate = addDays(currentDate, 7);
      } else {
        currentDate = addDays(currentDate, 1);
      }
      datePicker.value = currentDate;
      updateDateDisplay(currentDate);
      refreshCurrentView();
    });

    btnToday.addEventListener("click", function () {
      currentDate = toISODate(new Date());
      datePicker.value = currentDate;
      updateDateDisplay(currentDate);
      refreshCurrentView();
    });

    datePicker.addEventListener("change", function () {
      currentDate = datePicker.value;
      updateDateDisplay(currentDate);
      refreshCurrentView();
    });

    btnRefresh.addEventListener("click", function () {
      if (currentView === "month") {
        var ym = currentDate.slice(0, 7);
        Object.keys(monthCountCache).forEach(function (k) {
          if (k.slice(0, 7) === ym) delete monthCountCache[k];
        });
        renderedMonth = "";
      }
      refreshCurrentView();
    });

    // Multi-select dropdowns are wired up in initMultiSelects()
    initMultiSelects();

    // Schedule type toggle (All / Providers / Rooms / Locations)
    var typeButtons = [btnTypeAll, btnTypeProviders, btnTypeRooms, btnTypeLocations];
    typeButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        typeButtons.forEach(function (b) {
          b.classList.remove("active");
          b.setAttribute("aria-pressed", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-pressed", "true");
        if (btn === btnTypeAll) scheduleTypeFilter = "all";
        else if (btn === btnTypeProviders) scheduleTypeFilter = "providers";
        else if (btn === btnTypeRooms) scheduleTypeFilter = "rooms";
        else scheduleTypeFilter = "locations";
        storeValue("scheduleType", scheduleTypeFilter);
        updateProviderFilter();
        refreshCurrentView();
      });
    });

    btnViewDay.addEventListener("click", function () {
      if (currentView === "day") return;
      switchView("day");
    });

    btnViewWeek.addEventListener("click", function () {
      if (currentView === "week") return;
      switchView("week");
    });

    btnViewMonth.addEventListener("click", function () {
      if (currentView === "month") return;
      switchView("month");
    });
  }

  function refreshCurrentView() {
    storeValue("date", currentDate);
    if (currentView === "day") loadAppointments();
    else if (currentView === "week") renderWeekView();
    else renderMonthView();
  }

  // ── View switching ─────────────────────────────────────────

  function switchView(view) {
    currentView = view;
    storeValue("view", view);

    [btnViewDay, btnViewWeek, btnViewMonth].forEach(function (btn) {
      btn.classList.remove("active");
      btn.setAttribute("aria-pressed", "false");
    });

    hide(monthViewEl);
    hide(weekViewEl);
    hide(loadingState);
    hide(emptyState);
    hide(scheduleGrid);

    if (view === "day") {
      btnViewDay.classList.add("active");
      btnViewDay.setAttribute("aria-pressed", "true");
      updateDateDisplay(currentDate);
      loadAppointments();
    } else if (view === "week") {
      btnViewWeek.classList.add("active");
      btnViewWeek.setAttribute("aria-pressed", "true");
      updateDateDisplay(currentDate);
      renderWeekView();
    } else {
      btnViewMonth.classList.add("active");
      btnViewMonth.setAttribute("aria-pressed", "true");
      renderMonthView();
    }
  }

  // ── Date display ───────────────────────────────────────────

  var DAY_NAMES   = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
  var DAY_ABBR    = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  var MONTH_NAMES = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  var MONTH_ABBR  = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  function updateDateDisplay(isoDate) {
    var d     = new Date(isoDate + "T12:00:00");
    var today = toISODate(new Date());
    var isToday = isoDate === today;

    if (currentView === "month") {
      dateDisplay.textContent = MONTH_NAMES[d.getMonth()] + " " + d.getFullYear();
    } else if (currentView === "week") {
      var weekStart = getWeekStart(isoDate);
      var weekEnd   = addDays(weekStart, 6);
      var ws = new Date(weekStart + "T12:00:00");
      var we = new Date(weekEnd + "T12:00:00");
      dateDisplay.textContent = MONTH_ABBR[ws.getMonth()] + " " + ws.getDate() +
        " \u2013 " + MONTH_ABBR[we.getMonth()] + " " + we.getDate() + ", " + we.getFullYear();
    } else {
      var dayName   = DAY_NAMES[d.getDay()];
      var monthAbbr = MONTH_ABBR[d.getMonth()];
      var dayNum    = d.getDate();
      var year      = d.getFullYear();
      dateDisplay.textContent = dayName + ", " + monthAbbr + " " + dayNum + ", " + year;
    }

    if (isToday) {
      btnToday.classList.add("is-today");
    } else {
      btnToday.classList.remove("is-today");
    }
  }

  // ── Data loading (day view) ────────────────────────────────

  function loadAppointments() {
    showLoading();
    hideError();
    btnRefresh.classList.add("spinning");

    var url = API_BASE + "/appointments?date=" + encodeURIComponent(currentDate);

    fetch(url, { credentials: "same-origin" })
      .then(function (resp) {
        if (!resp.ok) {
          return resp.json().then(function (body) {
            throw new Error(body.error || "HTTP " + resp.status);
          });
        }
        return resp.json();
      })
      .then(function (data) {
        allAppointments = data.appointments || [];
        calendarBlocks = data.calendar_blocks || [];
        providers = data.providers || [];
        allPracticeLocations = data.all_locations || [];
        allRoomStaff = data.all_rooms || [];
        allProviderStaff = data.all_providers || [];
        buildLocationList();
        updateProviderFilter();
        updateLocationFilter();
        renderSchedule();
      })
      .catch(function (err) {
        showError("Failed to load appointments: " + err.message);
        showEmpty();
      })
      .finally(function () {
        btnRefresh.classList.remove("spinning");
      });
  }

  // ── Week view ──────────────────────────────────────────────

  var weekDataCache = {};

  function getWeekStart(isoDate) {
    var d = new Date(isoDate + "T12:00:00");
    var dow = d.getDay();
    return addDays(isoDate, -dow);
  }

  function renderWeekView() {
    hide(loadingState);
    hide(emptyState);
    hide(scheduleGrid);
    hide(monthViewEl);
    show(weekViewEl);

    updateDateDisplay(currentDate);

    var weekStart = getWeekStart(currentDate);
    var today = toISODate(new Date());

    weekGridHeader.innerHTML = "";
    var days = [];
    for (var i = 0; i < 7; i++) {
      var dayIso = addDays(weekStart, i);
      days.push(dayIso);
      var hdr = document.createElement("div");
      hdr.className = "week-day-header" + (dayIso === today ? " is-today" : "");
      var d = new Date(dayIso + "T12:00:00");
      hdr.innerHTML = '<span class="week-day-name">' + DAY_ABBR[d.getDay()] + '</span>' +
        '<span class="week-day-num">' + d.getDate() + '</span>';
      weekGridHeader.appendChild(hdr);
    }

    weekGridBody.innerHTML = "";
    var columns = [];
    for (var j = 0; j < 7; j++) {
      var col = document.createElement("div");
      col.className = "week-day-column" + (days[j] === today ? " is-today" : "");
      col.setAttribute("data-date", days[j]);

      var placeholder = document.createElement("div");
      placeholder.className = "week-loading";
      placeholder.textContent = "\u2026";
      placeholder.id = "week-col-" + days[j];
      col.appendChild(placeholder);

      (function (iso) {
        col.addEventListener("dblclick", function () {
          currentDate = iso;
          datePicker.value = iso;
          switchView("day");
        });
      })(days[j]);

      weekGridBody.appendChild(col);
      columns.push({ iso: days[j], el: col });
    }

    // Reset provider/location lists — will be rebuilt from all 7 days
    var weekProvidersSeen = {};
    var weekLocationsSeen = {};
    var weekProviders = [];
    var weekLocations = [];
    var daysCompleted = 0;

    var provFilter = selectedProviders;
    var locFilter  = selectedLocations;
    columns.forEach(function (c) {
      fetchWeekDayData(c.iso, c.el, provFilter, locFilter, function (dayProviders, dayLocations) {
        // Merge providers from this day
        (dayProviders || []).forEach(function (p) {
          if (!weekProvidersSeen[p.id]) {
            weekProvidersSeen[p.id] = true;
            weekProviders.push(p);
          }
        });
        // Merge locations from this day
        (dayLocations || []).forEach(function (l) {
          if (!weekLocationsSeen[l.id]) {
            weekLocationsSeen[l.id] = true;
            weekLocations.push(l);
          }
        });
        daysCompleted++;
        if (daysCompleted === 7) {
          weekProviders.sort(function (a, b) { return a.name.localeCompare(b.name); });
          weekLocations.sort(function (a, b) { return a.name.localeCompare(b.name); });
          providers = weekProviders;
          locations = weekLocations;
          updateProviderFilter();
          updateLocationFilter();
        }
      });
    });

    statsText.textContent = "Week of " + formatShortDate(weekStart);
  }

  function fetchWeekDayData(isoDate, colEl, provFilter, locFilter, onDone) {
    var url = API_BASE + "/appointments?date=" + encodeURIComponent(isoDate);
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var appts = data.appointments || [];
        var dayProviders = data.providers || [];

        // Build location list from this day's appointments
        var locSeen = {};
        var dayLocations = [];
        appts.forEach(function (a) {
          if (a.location_id && !locSeen[a.location_id]) {
            locSeen[a.location_id] = true;
            dayLocations.push({ id: a.location_id, name: a.location_name || "" });
          }
        });

        if (provFilter.length) {
          appts = appts.filter(function (a) { return provFilter.indexOf(a.provider_id) !== -1; });
        }
        if (locFilter.length) {
          appts = appts.filter(function (a) { return locFilter.indexOf(a.location_id) !== -1; });
        }
        if (scheduleTypeFilter === "providers") {
          appts = appts.filter(function (a) { return !a.is_schedule_event; });
        } else if (scheduleTypeFilter === "rooms") {
          appts = appts.filter(function (a) { return a.is_schedule_event; });
        }

        colEl.innerHTML = "";

        if (appts.length === 0) {
          var emptyEl = document.createElement("div");
          emptyEl.className = "week-empty";
          emptyEl.textContent = "No appts";
          colEl.appendChild(emptyEl);
          if (onDone) onDone(dayProviders, dayLocations);
          return;
        }

        // Sort by local time, then provider appointments before room events
        appts.sort(function (a, b) {
          if (!a.start_time || !b.start_time) return 0;
          var da = new Date(a.start_time);
          var db = new Date(b.start_time);
          var ma = da.getHours() * 60 + da.getMinutes();
          var mb = db.getHours() * 60 + db.getMinutes();
          if (ma !== mb) return ma - mb;
          // Same time: provider appointments first, rooms after
          var sa = a.is_schedule_event ? 1 : 0;
          var sb = b.is_schedule_event ? 1 : 0;
          return sa - sb;
        });

        appts.forEach(function (appt) {
          var card = document.createElement("div");
          var wBlockClass = "";
          if (appt.is_calendar_block) {
            wBlockClass = appt.block_type === "available" ? " calendar-available" : " calendar-busy";
          } else if (appt.is_block) {
            wBlockClass = " schedule-block";
          }
          card.className = "week-appt-card " + (appt.status_css || "") +
            (appt.is_schedule_event ? " schedule-event" : "") + wBlockClass;

          if (appt.note_type_name) {
            var colors = typeColors(appt.note_type_name);
            card.style.borderLeftColor = colors[0];
            if (!appt.is_schedule_event && !appt.is_block) {
              card.style.backgroundColor = colors[1];
            }
          }

          var timeEl = document.createElement("div");
          timeEl.className = "week-appt-time";
          timeEl.textContent = appt.start_time ? formatLocalTime(appt.start_time) : (appt.start_display || "");
          card.appendChild(timeEl);

          var nameEl = document.createElement("div");
          nameEl.className = "week-appt-name";
          nameEl.textContent = appt.is_block ? (appt.comment || "Block") : (appt.patient_name || "Unknown");
          card.appendChild(nameEl);

          if (appt.note_type_name) {
            var typeEl = document.createElement("div");
            typeEl.className = "week-appt-type";
            typeEl.textContent = appt.note_type_name;
            card.appendChild(typeEl);
          }

          if (appt.provider_name) {
            var provEl = document.createElement("div");
            provEl.className = "week-appt-provider";
            provEl.textContent = appt.provider_name;
            card.appendChild(provEl);
          }

          // Status badge on week cards (hidden for schedule events)
          if (!appt.is_schedule_event && appt.status_label) {
            var wStatusRow = document.createElement("div");
            wStatusRow.className = "grid-appt-status-row";
            var wBadge = document.createElement("span");
            wBadge.className = "status-badge " + (appt.status_css || "status-unknown");
            wBadge.textContent = appt.status_label;
            wStatusRow.appendChild(wBadge);
            card.appendChild(wStatusRow);
          }

          // Comment on week cards
          if (appt.comment && !appt.is_block) {
            var wCommentEl = document.createElement("div");
            wCommentEl.className = "grid-appt-comment";
            wCommentEl.textContent = appt.comment;
            card.appendChild(wCommentEl);
          }

          // Labels on week cards (hidden for schedule events)
          if (!appt.is_schedule_event && appt.labels && appt.labels.length) {
            var wLabelsEl = document.createElement("div");
            wLabelsEl.className = "week-appt-labels";
            appt.labels.forEach(function (lbl) {
              var wChip = document.createElement("span");
              wChip.className = "label-chip color-" + (lbl.color || "");
              wChip.textContent = lbl.name;
              wLabelsEl.appendChild(wChip);
            });
            card.appendChild(wLabelsEl);
          }

          // Click card → open appointment detail modal
          card.style.cursor = "pointer";
          card.title = "View appointment details";
          (function (a) {
            card.addEventListener("click", function (e) {
              e.stopPropagation();
              openAppointmentModal(a);
            });
          })(appt);

          colEl.appendChild(card);
        });

        if (onDone) onDone(dayProviders, dayLocations);
      })
      .catch(function () {
        colEl.innerHTML = '<div class="week-empty">Error</div>';
        if (onDone) onDone([], []);
      });
  }

  function formatShortDate(isoDate) {
    var d = new Date(isoDate + "T12:00:00");
    return MONTH_ABBR[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear();
  }

  // ── Month view ─────────────────────────────────────────────

  function renderMonthView() {
    var d        = new Date(currentDate + "T12:00:00");
    var year     = d.getFullYear();
    var month    = d.getMonth();
    var ym       = year + "-" + pad(month + 1);
    var today    = toISODate(new Date());

    updateDateDisplay(currentDate);

    hide(loadingState);
    hide(emptyState);
    hide(scheduleGrid);
    show(monthViewEl);

    var forceRebuild = renderedMonth !== ym;
    renderedMonth = ym;

    if (forceRebuild) {
      monthGridHeader.innerHTML = "";
      monthGridBody.innerHTML = "";

      DAY_ABBR.forEach(function (name) {
        var cell = document.createElement("div");
        cell.className = "month-day-name";
        cell.textContent = name;
        monthGridHeader.appendChild(cell);
      });

      var firstDay  = new Date(year, month, 1);
      var startDow  = firstDay.getDay();
      var lastDay   = new Date(year, month + 1, 0);
      var totalDays = lastDay.getDate();
      var totalCells = Math.ceil((startDow + totalDays) / 7) * 7;

      for (var i = 0; i < totalCells; i++) {
        var dayOffset = i - startDow;
        var cellDate  = new Date(year, month, 1 + dayOffset);
        var isoCell   = toISODate(cellDate);
        var isCurrentMonth = cellDate.getMonth() === month;

        var cell = document.createElement("div");
        cell.className = "month-cell" +
          (isCurrentMonth ? "" : " other-month") +
          (isoCell === today ? " is-today" : "");
        cell.setAttribute("data-date", isoCell);

        var dayNumEl = document.createElement("div");
        dayNumEl.className = "month-cell-day";
        dayNumEl.textContent = cellDate.getDate();
        cell.appendChild(dayNumEl);

        var badge = document.createElement("div");
        badge.className = "month-cell-badge zero";
        badge.id = "month-badge-" + isoCell;
        badge.textContent = "\u2026";
        cell.appendChild(badge);

        (function (iso) {
          cell.addEventListener("click", function () {
            currentDate = iso;
            datePicker.value = iso;
            switchView("day");
          });
        })(isoCell);

        monthGridBody.appendChild(cell);
      }
    }

    fetchMonthCounts(year, month);
    statsText.textContent = MONTH_NAMES[month] + " " + year;
  }

  function fetchMonthCounts(year, month) {
    var firstDay  = new Date(year, month, 1);
    var lastDay   = new Date(year, month + 1, 0);
    var startDow  = firstDay.getDay();
    var totalDays = lastDay.getDate();
    var totalCells = Math.ceil((startDow + totalDays) / 7) * 7;

    var toFetch = [];
    for (var i = 0; i < totalCells; i++) {
      var dayOffset = i - startDow;
      var cellDate  = new Date(year, month, 1 + dayOffset);
      var iso       = toISODate(cellDate);
      if (!(iso in monthCountCache)) {
        toFetch.push(iso);
      } else {
        updateMonthBadge(iso, monthCountCache[iso]);
      }
    }

    var BATCH = 7;
    function fetchNext(batch) {
      if (batch.length === 0) return;
      var iso = batch.shift();
      var url = API_BASE + "/appointments?date=" + encodeURIComponent(iso);
      fetch(url, { credentials: "same-origin" })
        .then(function (resp) { return resp.ok ? resp.json() : { appointments: [] }; })
        .then(function (data) {
          var appts = data.appointments || [];
          if (selectedProviders.length) {
            appts = appts.filter(function (a) { return selectedProviders.indexOf(a.provider_id) !== -1; });
          }
          if (selectedLocations.length) {
            appts = appts.filter(function (a) { return selectedLocations.indexOf(a.location_id) !== -1; });
          }
          if (scheduleTypeFilter === "providers") {
            appts = appts.filter(function (a) { return !a.is_schedule_event; });
          } else if (scheduleTypeFilter === "rooms") {
            appts = appts.filter(function (a) { return a.is_schedule_event; });
          }
          var count = appts.length;
          monthCountCache[iso] = count;
          updateMonthBadge(iso, count);
        })
        .catch(function () {
          monthCountCache[iso] = 0;
          updateMonthBadge(iso, 0);
        })
        .finally(function () { fetchNext(batch); });
    }

    var chunks = [];
    for (var j = 0; j < toFetch.length; j++) {
      var ci = j % BATCH;
      if (!chunks[ci]) chunks[ci] = [];
      chunks[ci].push(toFetch[j]);
    }
    chunks.forEach(function (chunk) { fetchNext(chunk); });
  }

  function updateMonthBadge(iso, count) {
    var badge = document.getElementById("month-badge-" + iso);
    if (!badge) return;
    badge.textContent = count;
    if (count === 0) {
      badge.className = "month-cell-badge zero";
    } else {
      badge.className = "month-cell-badge";
    }
  }

  // ── Location list (derived from appointments) ──────────────

  function buildLocationList() {
    var seen = {};
    locations = [];
    allAppointments.forEach(function (a) {
      var id   = a.location_id   || "";
      var name = a.location_name || "";
      if (id && !seen[id]) {
        seen[id] = true;
        locations.push({ id: id, name: name });
      }
    });
    locations.sort(function (a, b) { return a.name.localeCompare(b.name); });
  }

  // ── Multi-select filter component ───────────────────────────

  function initMultiSelects() {
    // Toggle open/close on button click
    [msProvider, msLocation].forEach(function (ms) {
      var btn = ms.querySelector(".multiselect-btn");
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var wasOpen = ms.classList.contains("open");
        closeAllMultiSelects();
        if (!wasOpen) {
          ms.classList.add("open");
          ms.querySelector(".multiselect-panel").classList.remove("hidden");
        }
      });
    });

    // Close on outside click
    document.addEventListener("click", function () {
      closeAllMultiSelects();
    });

    // Prevent panel clicks from closing
    [msProvider, msLocation].forEach(function (ms) {
      ms.querySelector(".multiselect-panel").addEventListener("click", function (e) {
        e.stopPropagation();
      });
    });
  }

  function closeAllMultiSelects() {
    [msProvider, msLocation].forEach(function (ms) {
      ms.classList.remove("open");
      ms.querySelector(".multiselect-panel").classList.add("hidden");
    });
  }

  function renderMultiSelect(msEl, items, selectedArr, allLabel, onChanged) {
    var panel = msEl.querySelector(".multiselect-panel");
    var label = msEl.querySelector(".multiselect-label");
    panel.innerHTML = "";

    // Select All / Clear buttons
    var actions = document.createElement("div");
    actions.className = "multiselect-actions";

    var btnSelectAll = document.createElement("button");
    btnSelectAll.type = "button";
    btnSelectAll.className = "multiselect-action-btn";
    btnSelectAll.textContent = "Select All";
    btnSelectAll.addEventListener("click", function (e) {
      e.stopPropagation();
      selectedArr.length = 0;
      items.forEach(function (item) { selectedArr.push(item.id); });
      panel.querySelectorAll("input[type=checkbox]").forEach(function (cb) { cb.checked = true; });
      updateMultiSelectLabel(label, selectedArr, items, allLabel);
      onChanged();
    });

    var btnClear = document.createElement("button");
    btnClear.type = "button";
    btnClear.className = "multiselect-action-btn";
    btnClear.textContent = "Clear";
    btnClear.addEventListener("click", function (e) {
      e.stopPropagation();
      selectedArr.length = 0;
      panel.querySelectorAll("input[type=checkbox]").forEach(function (cb) { cb.checked = false; });
      updateMultiSelectLabel(label, selectedArr, items, allLabel);
      onChanged();
    });

    actions.appendChild(btnSelectAll);
    actions.appendChild(btnClear);
    panel.appendChild(actions);

    items.forEach(function (item) {
      var row = document.createElement("label");
      row.className = "multiselect-item";

      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = item.id;
      cb.checked = selectedArr.indexOf(item.id) !== -1;

      cb.addEventListener("change", function () {
        if (cb.checked) {
          if (selectedArr.indexOf(item.id) === -1) selectedArr.push(item.id);
        } else {
          var idx = selectedArr.indexOf(item.id);
          if (idx !== -1) selectedArr.splice(idx, 1);
        }
        updateMultiSelectLabel(label, selectedArr, items, allLabel);
        onChanged();
      });

      var text = document.createElement("span");
      text.className = "multiselect-item-label";
      text.textContent = item.name;

      row.appendChild(cb);
      row.appendChild(text);
      panel.appendChild(row);
    });

    updateMultiSelectLabel(label, selectedArr, items, allLabel);
  }

  function updateMultiSelectLabel(labelEl, selectedArr, items, allLabel) {
    if (selectedArr.length === 0) {
      labelEl.textContent = allLabel;
    } else if (selectedArr.length === 1) {
      var match = items.filter(function (i) { return i.id === selectedArr[0]; })[0];
      labelEl.textContent = match ? match.name : "1 selected";
    } else {
      labelEl.textContent = selectedArr.length + " selected";
    }
  }

  function updateProviderFilter() {
    // In Rooms mode, show only room staff; otherwise show all providers + rooms
    var items;
    var filterLabel;
    if (scheduleTypeFilter === "rooms" && allRoomStaff.length > 0) {
      items = allRoomStaff;
      filterLabel = "All Rooms";
    } else if (scheduleTypeFilter === "providers" && allProviderStaff.length > 0) {
      items = allProviderStaff;
      filterLabel = "All Providers";
    } else if (allProviderStaff.length > 0) {
      items = allProviderStaff.concat(allRoomStaff).sort(function (a, b) { return a.name.localeCompare(b.name); });
      filterLabel = "All Providers and Rooms";
    } else {
      items = providers;
      filterLabel = "All Providers and Rooms";
    }
    if (items.length === 0) { hide(msProvider); return; }
    show(msProvider);
    var onChanged = function () {
      storeValue("selectedProviders", selectedProviders);
      if (currentView === "day") renderSchedule();
      else if (currentView === "week") renderWeekView();
      else if (currentView === "month") { monthCountCache = {}; renderedMonth = ""; renderMonthView(); }
    };
    renderMultiSelect(msProvider, items, selectedProviders, filterLabel, onChanged);
  }

  function updateLocationFilter() {
    // Prefer allPracticeLocations (all active locations) over the day-specific list
    var items = allPracticeLocations.length > 0 ? allPracticeLocations : locations;
    if (items.length === 0) { hide(msLocation); return; }
    show(msLocation);
    var onChanged = function () {
      storeValue("selectedLocations", selectedLocations);
      if (currentView === "day") renderSchedule();
      else if (currentView === "week") renderWeekView();
      else if (currentView === "month") { monthCountCache = {}; renderedMonth = ""; renderMonthView(); }
    };
    renderMultiSelect(msLocation, items, selectedLocations, "All Locations", onChanged);
  }

  // ── Render (day view — time grid) ─────────────────────────

  function renderSchedule() {
    var filtered = allAppointments.filter(function (a) {
      // In rooms/providers mode, skip provider filter (column visibility handles it)
      if (scheduleTypeFilter !== "rooms" && scheduleTypeFilter !== "providers" && selectedProviders.length && selectedProviders.indexOf(a.provider_id) === -1) return false;
      if (selectedLocations.length && selectedLocations.indexOf(a.location_id) === -1) return false;
      if (scheduleTypeFilter === "providers" && a.is_schedule_event) return false;
      if (scheduleTypeFilter === "rooms" && !a.is_schedule_event) return false;
      return true;
    });

    // Merge calendar blocks into the rendered list
    // Only show busy blocks (lunch, admin, OOO) — availability blocks hidden for now
    // Skip in Rooms mode (blocks are provider-level, not room-level)
    if (scheduleTypeFilter !== "rooms") {
      calendarBlocks.forEach(function (block) {
        // Only show busy blocks; availability windows kept in data but hidden
        if (block.block_type !== "busy") return;
        // Apply provider filter in non-column modes
        if (scheduleTypeFilter !== "providers" && selectedProviders.length && selectedProviders.indexOf(block.provider_id) === -1) return;
        // Apply location filter
        if (selectedLocations.length && block.location_name) {
          var locMatch = false;
          allPracticeLocations.forEach(function (loc) {
            if (selectedLocations.indexOf(loc.id) !== -1 && loc.name === block.location_name) locMatch = true;
          });
          if (!locMatch) return;
        }
        filtered.push({
          id: block.id,
          start_time: block.start_time,
          end_time: block.end_time,
          start_display: "",
          duration_minutes: block.duration_minutes,
          patient_name: "",
          patient_id: "",
          patient_key: "",
          provider_name: block.provider_name,
          provider_id: block.provider_id,
          location_name: block.location_name,
          location_id: "",
          note_type_name: "",
          status: "",
          status_label: "",
          status_css: "",
          labels: [],
          comment: block.title,
          note_id: "",
          is_schedule_event: false,
          is_block: true,
          is_calendar_block: true,
          block_type: block.block_type,
          parent_appointment_id: "",
        });
      });
    }

    hideLoading();

    // Stats bar
    var confirmed = filtered.filter(function (a) {
      return a.status_css === "status-confirmed" ||
             a.status_css === "status-arrived"   ||
             a.status_css === "status-roomed";
    }).length;
    statsText.textContent = filtered.length + " appointment" + (filtered.length === 1 ? "" : "s") +
      (filtered.length > 0 ? " \u00B7 " + confirmed + " confirmed/arrived/roomed" : "");

    if (filtered.length === 0 && scheduleTypeFilter === "all") {
      showEmpty();
      return;
    }

    hideEmpty();
    hide(monthViewEl);
    hide(weekViewEl);
    appointmentsTable.innerHTML = "";

    if (scheduleTypeFilter === "providers") {
      // Show persistent columns per provider (non-schedule-event appointments only)
      var provAppts = filtered.filter(function (a) { return !a.is_schedule_event; });

      // Build provider groups from all providers in the instance
      var provGroups = {};
      allProviderStaff.forEach(function (p) {
        provGroups[p.id] = { name: p.name, appts: [] };
      });

      provAppts.forEach(function (a) {
        var pid = a.provider_id || "";
        if (provGroups[pid]) {
          provGroups[pid].appts.push(a);
        }
      });

      var bounds = computeGridBounds(provAppts);
      if (provAppts.length === 0) {
        bounds = { startMin: GRID_START_HOUR * 60, endMin: GRID_END_HOUR * 60, firstApptMin: null };
      }

      var visibleProvs = allProviderStaff.filter(function (p) {
        if (selectedProviders.length && selectedProviders.indexOf(p.id) === -1) return false;
        return true;
      });

      var columnsEl = document.createElement("div");
      columnsEl.className = "location-columns";

      visibleProvs.forEach(function (p) {
        var group = provGroups[p.id];
        var col = document.createElement("div");
        col.className = "location-column";

        var header = document.createElement("div");
        header.className = "location-column-header";
        header.textContent = group.name;
        col.appendChild(header);

        col.appendChild(buildTimeGrid(group.appts, bounds));
        columnsEl.appendChild(col);
      });

      appointmentsTable.appendChild(columnsEl);
    } else if (scheduleTypeFilter === "locations") {
      // Show all practice locations as persistent columns (rooms on right)
      var locGroups = {};
      allPracticeLocations.forEach(function (loc) {
        locGroups[loc.id] = { name: loc.name, appts: [] };
      });

      // Assign appointments to their location column
      filtered.forEach(function (a) {
        var lid = a.location_id || "";
        if (locGroups[lid]) {
          locGroups[lid].appts.push(a);
        } else if (lid) {
          locGroups[lid] = { name: a.location_name || "Unknown", appts: [a] };
        }
      });

      // Sort each group: provider appointments first, room events second
      // so rooms consistently render on the right when overlapping
      Object.keys(locGroups).forEach(function (lid) {
        locGroups[lid].appts.sort(function (a, b) {
          if (a.is_schedule_event !== b.is_schedule_event) {
            return a.is_schedule_event ? 1 : -1;
          }
          return 0;
        });
      });

      // Compute shared bounds across ALL appointments so columns align
      var bounds = computeGridBounds(filtered);
      // If no appointments at all, use default bounds
      if (filtered.length === 0) {
        bounds = { startMin: GRID_START_HOUR * 60, endMin: GRID_END_HOUR * 60, firstApptMin: null };
      }

      var columnsEl = document.createElement("div");
      columnsEl.className = "location-columns";

      var visibleLocations = allPracticeLocations.filter(function (loc) {
        if (selectedLocations.length && selectedLocations.indexOf(loc.id) === -1) return false;
        return true;
      });

      visibleLocations.forEach(function (loc) {
        var group = locGroups[loc.id];
        var col = document.createElement("div");
        col.className = "location-column";

        var header = document.createElement("div");
        header.className = "location-column-header";
        header.textContent = group.name;
        col.appendChild(header);

        col.appendChild(buildTimeGrid(group.appts, bounds));
        columnsEl.appendChild(col);
      });

      appointmentsTable.appendChild(columnsEl);
    } else if (scheduleTypeFilter === "rooms") {
      // Show all rooms as persistent columns, only schedule events
      var roomGroups = {};
      allRoomStaff.forEach(function (room) {
        roomGroups[room.id] = { name: room.name, appts: [] };
      });

      // Room schedule events have the room as the provider
      var roomAppts = filtered.filter(function (a) { return a.is_schedule_event; });
      roomAppts.forEach(function (a) {
        var rid = a.provider_id || "";
        if (roomGroups[rid]) {
          roomGroups[rid].appts.push(a);
        }
      });

      var bounds = computeGridBounds(roomAppts);
      if (roomAppts.length === 0) {
        bounds = { startMin: GRID_START_HOUR * 60, endMin: GRID_END_HOUR * 60, firstApptMin: null };
      }

      var visibleRooms = allRoomStaff.filter(function (room) {
        if (selectedProviders.length && selectedProviders.indexOf(room.id) === -1) return false;
        return true;
      });

      var columnsEl = document.createElement("div");
      columnsEl.className = "location-columns";

      visibleRooms.forEach(function (room) {
        var group = roomGroups[room.id];
        var col = document.createElement("div");
        col.className = "location-column";

        var header = document.createElement("div");
        header.className = "location-column-header";
        header.textContent = group.name;
        col.appendChild(header);

        col.appendChild(buildTimeGrid(group.appts, bounds));
        columnsEl.appendChild(col);
      });

      appointmentsTable.appendChild(columnsEl);
    } else {
      var bounds = computeGridBounds(filtered);
      appointmentsTable.appendChild(buildTimeGrid(filtered, bounds));
    }

    show(scheduleGrid);

  }

  // ── Group by hour (kept for reference) ─────────────────────

  function groupByHour(appts) {
    var groups = {};
    appts.forEach(function (a) {
      var hour = 0;
      if (a.start_time) {
        var d = new Date(a.start_time);
        hour = d.getHours();
      }
      var key = String(hour);
      if (!groups[key]) groups[key] = [];
      groups[key].push(a);
    });
    return groups;
  }

  function formatHourLabel(hour) {
    if (hour === 0)   return "12 AM";
    if (hour < 12)    return hour + " AM";
    if (hour === 12)  return "12 PM";
    return (hour - 12) + " PM";
  }

  // ── Meta chip helper ───────────────────────────────────────

  function metaChip(iconEl, text) {
    var chip = document.createElement("span");
    chip.className = "meta-chip";
    chip.appendChild(iconEl);
    var textEl = document.createElement("span");
    textEl.className = "meta-chip-text";
    textEl.textContent = text;
    chip.appendChild(textEl);
    return chip;
  }

  // ── Icon SVG helpers ───────────────────────────────────────

  function svgIcon(path) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", "12");
    svg.setAttribute("height", "12");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("fill", "currentColor");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = path;
    return svg;
  }

  function svgIconLg(path) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", "14");
    svg.setAttribute("height", "14");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("fill", "currentColor");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = path;
    return svg;
  }

  function iconProvider() {
    return svgIcon('<path d="M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm5 5H3a5 5 0 0 1 10 0z"/>');
  }

  // ── UI state helpers ───────────────────────────────────────

  function show(el) { el.classList.remove("hidden"); }
  function hide(el) { el.classList.add("hidden"); }

  function showLoading() {
    show(loadingState);
    hide(emptyState);
    hide(scheduleGrid);
    hide(monthViewEl);
  }

  function hideLoading() { hide(loadingState); }

  function showEmpty() {
    hide(loadingState);
    show(emptyState);
    hide(scheduleGrid);
    hide(monthViewEl);
  }

  function hideEmpty() { hide(emptyState); }

  function showError(msg) {
    statusBar.textContent = msg;
    statusBar.className = "status-bar error";
    show(statusBar);
  }

  function hideError() {
    statusBar.textContent = "";
    hide(statusBar);
  }

  // ── Date utilities ─────────────────────────────────────────

  function toISODate(d) {
    var y   = d.getFullYear();
    var m   = pad(d.getMonth() + 1);
    var day = pad(d.getDate());
    return y + "-" + m + "-" + day;
  }

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function addDays(isoDate, delta) {
    var d = new Date(isoDate + "T12:00:00");
    d.setDate(d.getDate() + delta);
    return toISODate(d);
  }

  // ── Appointment detail modal ────────────────────────────────

  var STATUS_OPTIONS = [
    { value: "unconfirmed", label: "Unconfirmed", css: "status-unconfirmed" },
    { value: "attempted",   label: "Attempted",   css: "status-attempted" },
    { value: "confirmed",   label: "Confirmed",   css: "status-confirmed" },
    { value: "arrived",     label: "Arrived",     css: "status-arrived" },
    { value: "roomed",      label: "Roomed",      css: "status-roomed" },
    { value: "exited",      label: "Exited",      css: "status-exited" },
  ];

  var LABEL_COLOR_BG = {
    red: "#fde8e8", orange: "#fff7ed", yellow: "#fefce8", olive: "#f7fee7",
    green: "#dcfce7", teal: "#ccfbf1", blue: "#dbeafe", violet: "#ede9fe",
    purple: "#f3e8ff", pink: "#fce7f3", brown: "#fef3c7", grey: "#f3f4f6",
    black: "#e5e7eb", "": "#f3f4f6",
  };

  var LABEL_COLOR_FG = {
    red: "#b91c1c", orange: "#c2410c", yellow: "#854d0e", olive: "#3f6212",
    green: "#14532d", teal: "#134e4a", blue: "#1e3a8a", violet: "#4c1d95",
    purple: "#3b0764", pink: "#831843", brown: "#78350f", grey: "#374151",
    black: "#111827", "": "#4b5563",
  };

  function openAppointmentModal(appt) {
    modalOverlay.innerHTML = "";
    modalOverlay.classList.remove("hidden");

    var card = document.createElement("div");
    card.className = "modal-card";
    card.style.position = "relative";

    // ── Header: patient name + close
    var header = document.createElement("div");
    header.className = "modal-header";

    var nameLink = document.createElement("a");
    nameLink.className = "modal-patient-name";
    nameLink.textContent = appt.patient_name || "Unknown";
    if (appt.patient_key && appt.note_id) {
      nameLink.href = "#";
      nameLink.addEventListener("click", function (e) {
        e.preventDefault();
        window.top.location.href = "/patient/" + encodeURIComponent(appt.patient_key) + "?noteId=" + encodeURIComponent(appt.note_id);
      });
    }
    header.appendChild(nameLink);

    var closeBtn = document.createElement("button");
    closeBtn.className = "modal-close";
    closeBtn.innerHTML = "&times;";
    closeBtn.title = "Close";
    closeBtn.addEventListener("click", closeAppointmentModal);
    header.appendChild(closeBtn);
    card.appendChild(header);

    // ── Body
    var body = document.createElement("div");
    body.className = "modal-body";

    // Details section
    var details = document.createElement("div");
    details.className = "modal-section";

    // Type chip
    if (appt.note_type_name) {
      var typeRow = document.createElement("div");
      typeRow.className = "modal-detail-row";
      var typeChip = document.createElement("span");
      typeChip.className = "modal-type-chip";
      var colors = typeColors(appt.note_type_name);
      typeChip.style.background = colors[1];
      typeChip.style.color = colors[2];
      typeChip.textContent = appt.note_type_name;
      typeRow.appendChild(typeChip);
      details.appendChild(typeRow);
    }

    // Date/time
    addDetailRow(details, "Time", formatLocalTime(appt.start_time) +
      (appt.end_time ? " \u2013 " + formatLocalTime(appt.end_time) : "") +
      (appt.duration_minutes ? " (" + appt.duration_minutes + " min)" : ""));

    // Provider (or parent provider for schedule events)
    var modalProvider = appt.is_schedule_event && appt.parent_provider_name
      ? appt.parent_provider_name : appt.provider_name;
    if (modalProvider) addDetailRow(details, "Provider", modalProvider);

    // Room (from linked schedule event)
    if (appt.room_name) addDetailRow(details, "Room", appt.room_name);

    // Location
    if (appt.location_name) addDetailRow(details, "Location", appt.location_name);

    // Editable comment field
    if (!appt.is_calendar_block) {
      var commentSection = document.createElement("div");
      commentSection.className = "modal-comment-section";

      var commentLabel = document.createElement("label");
      commentLabel.className = "modal-comment-label";
      commentLabel.textContent = "Note";
      commentSection.appendChild(commentLabel);

      var commentInput = document.createElement("input");
      commentInput.type = "text";
      commentInput.className = "modal-comment-input";
      commentInput.placeholder = "Add a note\u2026";
      commentInput.value = appt.comment || "";
      commentSection.appendChild(commentInput);

      var commentStatus = document.createElement("span");
      commentStatus.className = "modal-comment-status";
      commentSection.appendChild(commentStatus);

      var saveTimeout = null;
      commentInput.addEventListener("input", function () {
        clearTimeout(saveTimeout);
        commentStatus.textContent = "";
        saveTimeout = setTimeout(function () {
          var newComment = commentInput.value.trim();
          fetch(API_BASE + "/appointment/" + encodeURIComponent(appt.id) + "/comment", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ comment: newComment }),
          })
            .then(function (r) {
              if (!r.ok) throw new Error("Save failed");
              return r.json();
            })
            .then(function () {
              appt.comment = newComment;
              commentStatus.textContent = "\u2713 Saved";
              commentStatus.className = "modal-comment-status saved";
              refreshCurrentView();
            })
            .catch(function () {
              commentStatus.textContent = "Failed to save";
              commentStatus.className = "modal-comment-status error";
            });
        }, 800);
      });

      details.appendChild(commentSection);
    }

    // Note link
    if (appt.patient_key && appt.note_id) {
      var linkEl = document.createElement("a");
      linkEl.className = "modal-chart-link";
      linkEl.textContent = "Open note \u2192";
      linkEl.href = "#";
      linkEl.addEventListener("click", function (e) {
        e.preventDefault();
        window.top.location.href = "/patient/" + encodeURIComponent(appt.patient_key) + "?noteId=" + encodeURIComponent(appt.note_id);
      });
      linkEl.style.marginTop = "6px";
      details.appendChild(linkEl);
    }

    body.appendChild(details);

    // ── Schedule event indicator with link to parent appointment
    if (appt.is_schedule_event) {
      var seNotice = document.createElement("div");
      seNotice.className = "modal-section modal-schedule-event-notice";

      var noticeText = document.createElement("span");
      noticeText.textContent = "Room reservation \u2014 status and labels are managed on the ";

      // Find the parent appointment in current data to link to it
      var parentAppt = null;
      if (appt.parent_appointment_id) {
        parentAppt = allAppointments.filter(function (a) {
          return a.id === appt.parent_appointment_id;
        })[0];
      }

      if (parentAppt && parentAppt.patient_key && parentAppt.note_id) {
        var parentLink = document.createElement("a");
        parentLink.className = "modal-chart-link";
        parentLink.textContent = "linked provider appointment";
        parentLink.href = "#";
        parentLink.style.display = "inline";
        parentLink.addEventListener("click", function (e) {
          e.preventDefault();
          closeAppointmentModal();
          openAppointmentModal(parentAppt);
        });
        seNotice.appendChild(noticeText);
        seNotice.appendChild(parentLink);
        seNotice.appendChild(document.createTextNode("."));
      } else {
        noticeText.textContent = "Room reservation \u2014 status and labels are managed on the linked provider appointment.";
        seNotice.appendChild(noticeText);
      }

      body.appendChild(seNotice);
    }

    // ── Status section (hidden for schedule events)
    var isTerminal = appt.status === "cancelled" || appt.status === "noshowed";
    if (!appt.is_schedule_event) {
      var statusSection = document.createElement("div");
      statusSection.className = "modal-section";
      var statusTitle = document.createElement("div");
      statusTitle.className = "modal-section-title";
      statusTitle.textContent = "Status";
      statusSection.appendChild(statusTitle);

      if (isTerminal) {
        var readOnly = document.createElement("div");
        readOnly.className = "modal-status-readonly";
        readOnly.textContent = appt.status_label || appt.status;
        statusSection.appendChild(readOnly);
      } else {
        var select = document.createElement("select");
        select.className = "modal-status-select";
        STATUS_OPTIONS.forEach(function (opt) {
          var option = document.createElement("option");
          option.value = opt.value;
          option.textContent = opt.label;
          if (opt.value === appt.status) option.selected = true;
          select.appendChild(option);
        });
        select.addEventListener("change", function () {
          updateAppointmentStatus(appt, select.value, select);
        });
        statusSection.appendChild(select);
      }
      body.appendChild(statusSection);
    }

    // ── Labels section (hidden for schedule events)
    if (!appt.is_schedule_event) {
      var labelsSection = document.createElement("div");
      labelsSection.className = "modal-section";
      labelsSection.id = "modal-labels-section";
      renderLabelsSection(labelsSection, appt);
      body.appendChild(labelsSection);
    }

    // ── Actions section (hidden for terminal statuses)
    if (!isTerminal) {
      var actionsSection = document.createElement("div");
      actionsSection.className = "modal-section";
      var actionsTitle = document.createElement("div");
      actionsTitle.className = "modal-section-title";
      actionsTitle.textContent = "Actions";
      actionsSection.appendChild(actionsTitle);

      var actionsRow = document.createElement("div");
      actionsRow.className = "modal-actions-row";

      // Reschedule (calls scheduling_with_rooms /book with appointment_id)
      if (!appt.is_schedule_event && !appt.is_block && !appt.is_calendar_block && appt.patient_id) {
        var rescheduleBtn = document.createElement("button");
        rescheduleBtn.className = "modal-action-btn action-primary";
        rescheduleBtn.textContent = "Reschedule";
        rescheduleBtn.addEventListener("click", function () {
          showRescheduleForm(card, appt);
        });
        actionsRow.appendChild(rescheduleBtn);
      }

      // No Show
      var noshowBtn = document.createElement("button");
      noshowBtn.className = "modal-action-btn action-warning";
      noshowBtn.textContent = "No Show";
      noshowBtn.addEventListener("click", function () {
        showConfirmation(card, "Mark as No Show",
          "Please confirm that " + (appt.patient_name || "this patient") + " did not show up for the appointment.",
          "confirm-warning", function () { markNoShow(appt); });
      });
      actionsRow.appendChild(noshowBtn);

      // Cancel
      var cancelBtn = document.createElement("button");
      cancelBtn.className = "modal-action-btn action-danger";
      cancelBtn.textContent = "Cancel";
      cancelBtn.addEventListener("click", function () {
        showCancelConfirmation(card, appt);
      });
      actionsRow.appendChild(cancelBtn);

      actionsSection.appendChild(actionsRow);
      body.appendChild(actionsSection);
    }

    card.appendChild(body);
    modalOverlay.appendChild(card);

    // Close on overlay click
    modalOverlay.addEventListener("click", function (e) {
      if (e.target === modalOverlay) closeAppointmentModal();
    });

    // Close on Escape
    document.addEventListener("keydown", modalEscHandler);
  }

  function closeAppointmentModal() {
    modalOverlay.classList.add("hidden");
    modalOverlay.innerHTML = "";
    document.removeEventListener("keydown", modalEscHandler);
  }

  function modalEscHandler(e) {
    if (e.key === "Escape") closeAppointmentModal();
  }

  function addDetailRow(parent, label, value) {
    var row = document.createElement("div");
    row.className = "modal-detail-row";
    var lbl = document.createElement("span");
    lbl.className = "modal-detail-label";
    lbl.textContent = label;
    var val = document.createElement("span");
    val.className = "modal-detail-value";
    val.textContent = value;
    row.appendChild(lbl);
    row.appendChild(val);
    parent.appendChild(row);
  }

  function renderLabelsSection(container, appt) {
    container.innerHTML = "";
    var title = document.createElement("div");
    title.className = "modal-section-title";
    title.textContent = "Labels";
    container.appendChild(title);

    var currentLabels = (appt.labels || []).slice();
    var atMax = currentLabels.length >= 3;

    // Current labels with remove buttons
    if (currentLabels.length > 0) {
      var list = document.createElement("div");
      list.className = "modal-labels-list";
      currentLabels.forEach(function (lbl) {
        var chip = document.createElement("span");
        chip.className = "modal-label-chip";
        var c = lbl.color || "";
        chip.style.background = LABEL_COLOR_BG[c] || LABEL_COLOR_BG[""];
        chip.style.color = LABEL_COLOR_FG[c] || LABEL_COLOR_FG[""];
        chip.textContent = lbl.name;

        var rmBtn = document.createElement("button");
        rmBtn.className = "modal-label-remove";
        rmBtn.innerHTML = "&times;";
        rmBtn.title = "Remove " + lbl.name;
        rmBtn.addEventListener("click", function () {
          removeLabelFromAppointment(appt, lbl.name, container);
        });
        chip.appendChild(rmBtn);
        list.appendChild(chip);
      });
      container.appendChild(list);
    }

    // Add label button + dropdown
    var addWrap = document.createElement("div");
    addWrap.className = "modal-label-add-wrap";

    var addBtn = document.createElement("button");
    addBtn.className = "modal-label-add-btn";
    addBtn.textContent = "+ Add Label";
    if (atMax) addBtn.disabled = true;

    var dropdown = document.createElement("div");
    dropdown.className = "modal-label-dropdown hidden";

    var currentNames = currentLabels.map(function (l) { return l.name; });
    availableLabels.forEach(function (lbl) {
      var alreadyAdded = currentNames.indexOf(lbl.name) !== -1;
      var opt = document.createElement("button");
      opt.className = "modal-label-option";
      if (alreadyAdded || atMax) opt.disabled = true;

      var dot = document.createElement("span");
      dot.className = "modal-label-dot";
      dot.style.background = LABEL_COLOR_FG[lbl.color || ""] || "#6b7280";
      opt.appendChild(dot);

      var nameEl = document.createElement("span");
      nameEl.textContent = lbl.name;
      opt.appendChild(nameEl);

      if (!alreadyAdded && !atMax) {
        opt.addEventListener("click", function () {
          addLabelToAppointment(appt, lbl.name, container);
        });
      }
      dropdown.appendChild(opt);
    });

    addBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      dropdown.classList.toggle("hidden");
    });
    addWrap.appendChild(addBtn);
    addWrap.appendChild(dropdown);
    container.appendChild(addWrap);

    if (atMax) {
      var limitMsg = document.createElement("div");
      limitMsg.className = "modal-label-limit";
      limitMsg.textContent = "Limit reached: Only 3 appointment labels allowed";
      container.appendChild(limitMsg);
    }

    // Close dropdown on outside click
    document.addEventListener("click", function closeDropdown(e) {
      if (!addWrap.contains(e.target)) {
        dropdown.classList.add("hidden");
        document.removeEventListener("click", closeDropdown);
      }
    });
  }

  // ── Modal API calls ────────────────────────────────────────

  function updateAppointmentStatus(appt, newStatus, selectEl) {
    selectEl.disabled = true;
    fetch(API_BASE + "/appointment/" + encodeURIComponent(appt.id) + "/status", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("Status update failed");
        return r.json();
      })
      .then(function () {
        // Update local state and re-render
        appt.status = newStatus;
        var meta = STATUS_OPTIONS.filter(function (o) { return o.value === newStatus; })[0];
        if (meta) {
          appt.status_label = meta.label;
          appt.status_css = meta.css;
        }
        closeAppointmentModal();
        refreshCurrentView();
      })
      .catch(function (err) {
        selectEl.disabled = false;
        showError("Failed to update status: " + err.message);
      });
  }

  function addLabelToAppointment(appt, labelName, container) {
    container.innerHTML = '<div class="modal-loading"><div class="spinner"></div>Adding label\u2026</div>';
    fetch(API_BASE + "/appointment/" + encodeURIComponent(appt.id) + "/add-labels", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ labels: [labelName] }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("Failed to add label");
        return r.json();
      })
      .then(function () {
        // Add to local state
        var matchLabel = availableLabels.filter(function (l) { return l.name === labelName; })[0];
        appt.labels = appt.labels || [];
        appt.labels.push({ name: labelName, color: matchLabel ? matchLabel.color : "grey" });
        renderLabelsSection(container, appt);
        refreshCurrentView();
      })
      .catch(function (err) {
        showError("Failed to add label: " + err.message);
        renderLabelsSection(container, appt);
      });
  }

  function removeLabelFromAppointment(appt, labelName, container) {
    container.innerHTML = '<div class="modal-loading"><div class="spinner"></div>Removing label\u2026</div>';
    fetch(API_BASE + "/appointment/" + encodeURIComponent(appt.id) + "/remove-labels", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ labels: [labelName] }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("Failed to remove label");
        return r.json();
      })
      .then(function () {
        appt.labels = (appt.labels || []).filter(function (l) { return l.name !== labelName; });
        renderLabelsSection(container, appt);
        refreshCurrentView();
      })
      .catch(function (err) {
        showError("Failed to remove label: " + err.message);
        renderLabelsSection(container, appt);
      });
  }

  function cancelAppointment(appt, suppressNotification) {
    var doCancel = function () {
      fetch(API_BASE + "/appointment/" + encodeURIComponent(appt.id) + "/cancel", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ suppress_notification: !!suppressNotification }),
      })
        .then(function (r) {
          return r.json().then(function (data) {
            if (!r.ok) throw new Error(data.error || "Cancel failed");
            return data;
          });
        })
        .then(function () {
          closeAppointmentModal();
          refreshCurrentView();
        })
        .catch(function (err) {
          showError(err.message);
          closeAppointmentModal();
        });
    };

    if (suppressNotification) {
      // Add a silent-cancel label before cancelling so notification plugins
      // can check for it and skip sending the cancellation message.
      fetch(API_BASE + "/appointment/" + encodeURIComponent(appt.id) + "/add-labels", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ labels: ["Silent Cancel"] }),
      })
        .then(function (r) {
          if (!r.ok) throw new Error("Failed to set silent-cancel label");
          return r.json();
        })
        .then(doCancel)
        .catch(function (err) {
          showError("Failed to suppress notification: " + err.message);
          closeAppointmentModal();
        });
    } else {
      doCancel();
    }
  }

  function markNoShow(appt) {
    fetch(API_BASE + "/appointment/" + encodeURIComponent(appt.id) + "/noshow", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (body) {
          throw new Error(body.error || "No-show update failed");
        });
        return r.json();
      })
      .then(function () {
        closeAppointmentModal();
        refreshCurrentView();
      })
      .catch(function (err) {
        showError("Failed to mark as no-show: " + err.message);
        closeAppointmentModal();
      });
  }

  function showCancelConfirmation(cardEl, appt) {
    var overlay = document.createElement("div");
    overlay.className = "modal-confirm-overlay";

    var titleEl = document.createElement("div");
    titleEl.className = "modal-confirm-title";
    titleEl.textContent = "Cancel Appointment";
    overlay.appendChild(titleEl);

    var msgEl = document.createElement("div");
    msgEl.className = "modal-confirm-message";
    msgEl.textContent = "Please confirm that this appointment for " +
      (appt.patient_name || "the patient") + " should be cancelled.";
    overlay.appendChild(msgEl);

    // Suppress-notification checkbox
    var checkRow = document.createElement("label");
    checkRow.className = "modal-confirm-checkbox-row";
    var checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = "suppress-cancel-notification";
    checkRow.appendChild(checkbox);
    var checkLabel = document.createElement("span");
    checkLabel.textContent = "Do not send cancellation notification to patient";
    checkRow.appendChild(checkLabel);
    overlay.appendChild(checkRow);

    var btns = document.createElement("div");
    btns.className = "modal-confirm-buttons";

    var goBackBtn = document.createElement("button");
    goBackBtn.className = "modal-confirm-btn confirm-cancel";
    goBackBtn.textContent = "Go Back";
    goBackBtn.addEventListener("click", function () {
      overlay.remove();
    });
    btns.appendChild(goBackBtn);

    var confirmBtn = document.createElement("button");
    confirmBtn.className = "modal-confirm-btn confirm-danger";
    confirmBtn.textContent = "Cancel Appointment";
    confirmBtn.addEventListener("click", function () {
      var suppress = checkbox.checked;
      overlay.remove();
      cancelAppointment(appt, suppress);
    });
    btns.appendChild(confirmBtn);

    overlay.appendChild(btns);
    cardEl.appendChild(overlay);
  }

  function showConfirmation(cardEl, title, message, btnClass, onConfirm) {
    var overlay = document.createElement("div");
    overlay.className = "modal-confirm-overlay";

    var titleEl = document.createElement("div");
    titleEl.className = "modal-confirm-title";
    titleEl.textContent = title;
    overlay.appendChild(titleEl);

    var msgEl = document.createElement("div");
    msgEl.className = "modal-confirm-message";
    msgEl.textContent = message;
    overlay.appendChild(msgEl);

    var btns = document.createElement("div");
    btns.className = "modal-confirm-buttons";

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "modal-confirm-btn confirm-cancel";
    cancelBtn.textContent = "Go Back";
    cancelBtn.addEventListener("click", function () {
      overlay.remove();
    });
    btns.appendChild(cancelBtn);

    var confirmBtn = document.createElement("button");
    confirmBtn.className = "modal-confirm-btn " + btnClass;
    confirmBtn.textContent = title;
    confirmBtn.addEventListener("click", function () {
      overlay.remove();
      onConfirm();
    });
    btns.appendChild(confirmBtn);

    overlay.appendChild(btns);
    cardEl.appendChild(overlay);
  }

  // ── Reschedule ─────────────────────────────────────────────

  var RESCHEDULE_API = "/plugin-io/api/scheduling_with_rooms/book";
  var SLOTS_API = "/plugin-io/api/scheduling_with_rooms/all-slots";

  function showRescheduleForm(cardEl, appt) {
    var overlay = document.createElement("div");
    overlay.className = "modal-confirm-overlay";
    overlay.style.overflowY = "auto";

    var titleEl = document.createElement("div");
    titleEl.className = "modal-confirm-title";
    titleEl.textContent = "Reschedule Appointment";
    overlay.appendChild(titleEl);

    var msgEl = document.createElement("div");
    msgEl.className = "modal-confirm-message";
    msgEl.textContent = (appt.patient_name || "Patient") + " \u00B7 " +
      (appt.note_type_name || "Appointment") + " \u00B7 " +
      (appt.duration_minutes || 30) + " min";
    overlay.appendChild(msgEl);

    // Date picker
    var dateLabel = document.createElement("label");
    dateLabel.className = "modal-reschedule-label";
    dateLabel.textContent = "Date";
    overlay.appendChild(dateLabel);
    var dateInput = document.createElement("input");
    dateInput.type = "date";
    dateInput.className = "modal-reschedule-input";
    dateInput.value = appt.start_time ? appt.start_time.slice(0, 10) : currentDate;
    overlay.appendChild(dateInput);

    // Slot grid container
    var slotsLabel = document.createElement("label");
    slotsLabel.className = "modal-reschedule-label";
    slotsLabel.textContent = "Available times";
    overlay.appendChild(slotsLabel);
    var slotsContainer = document.createElement("div");
    slotsContainer.className = "reschedule-slots";
    overlay.appendChild(slotsContainer);

    var selectedSlot = null;

    function loadSlots(date) {
      slotsContainer.innerHTML = "<div class='reschedule-slots-loading'>Loading slots\u2026</div>";
      selectedSlot = null;

      var locationId = appt.location_uuid || appt.location_id;
      var providerId = appt.provider_uuid || appt.provider_id;
      var duration = appt.duration_minutes || 30;
      var noteTypeCode = appt.note_type_code || "";

      var url = SLOTS_API +
        "?location_id=" + encodeURIComponent(locationId) +
        "&date=" + encodeURIComponent(date) +
        "&duration=" + encodeURIComponent(duration) +
        "&provider_id=" + encodeURIComponent(providerId) +
        (noteTypeCode ? "&note_type_code=" + encodeURIComponent(noteTypeCode) : "");

      fetch(url, { credentials: "same-origin" })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function (data) {
          slotsContainer.innerHTML = "";
          var calendarTz = data.timezone || "UTC";
          // Find slots for this provider — match with or without dashes
          var providerSlots = [];
          var pidClean = providerId.replace(/-/g, "");
          (data.providers || []).forEach(function (p) {
            if (p.id === providerId || p.id.replace(/-/g, "") === pidClean) {
              providerSlots = p.slots || [];
            }
          });

          if (providerSlots.length === 0) {
            slotsContainer.innerHTML = "<div class='reschedule-slots-empty'>No available slots for this date</div>";
            return;
          }

          providerSlots.forEach(function (slot) {
            var btn = document.createElement("button");
            btn.className = "reschedule-slot-btn";
            btn.type = "button";
            // slot.start is naive ISO in calendar tz (e.g. "2026-08-10T09:00:00")
            var startStr = slot.start || slot;
            // To display in browser-local time: create a Date that represents
            // "this naive time IS in calendarTz", then format in local.
            // Intl.DateTimeFormat with timeZone gives us the wall-clock in any tz.
            // We need to find what UTC instant corresponds to startStr in calendarTz,
            // then let the browser display that instant in local time.
            //
            // Trick: new Date(naive) parses as local. We want to parse as calendarTz.
            // Use the formatter to find the offset between calendarTz and local.
            var naiveAsLocal = new Date(startStr);
            // What does this instant look like in calendarTz?
            var inCalTz = new Date(naiveAsLocal.toLocaleString("en-US", { timeZone: calendarTz }));
            // Difference = how many ms ahead/behind calendarTz is from local
            var diffMs = naiveAsLocal.getTime() - inCalTz.getTime();
            // The actual UTC instant: naive parsed as local, adjusted by the diff
            var utcInstant = new Date(naiveAsLocal.getTime() + diffMs);
            // Now display in browser-local time
            var h = utcInstant.getHours();
            var m = String(utcInstant.getMinutes()).padStart(2, "0");
            var ampm = h >= 12 ? "PM" : "AM";
            var h12 = h % 12 || 12;
            btn.textContent = h12 + ":" + m + " " + ampm;
            btn.addEventListener("click", function () {
              // Send the naive calendar-tz time to /book (it expects calendar tz)
              selectedSlot = startStr;
              slotsContainer.querySelectorAll(".reschedule-slot-btn").forEach(function (b) {
                b.classList.remove("selected");
              });
              btn.classList.add("selected");
            });
            slotsContainer.appendChild(btn);
          });
        })
        .catch(function (err) {
          slotsContainer.innerHTML = "<div class='reschedule-slots-empty'>Failed to load available times: " + err.message + "</div>";
        });
    }

    // Load slots for initial date
    loadSlots(dateInput.value);

    // Reload slots when date changes
    dateInput.addEventListener("change", function () {
      loadSlots(dateInput.value);
    });

    // Buttons
    var btns = document.createElement("div");
    btns.className = "modal-confirm-buttons";
    btns.style.marginTop = "16px";

    var goBackBtn = document.createElement("button");
    goBackBtn.className = "modal-confirm-btn confirm-cancel";
    goBackBtn.textContent = "Go Back";
    goBackBtn.addEventListener("click", function () { overlay.remove(); });
    btns.appendChild(goBackBtn);

    var confirmBtn = document.createElement("button");
    confirmBtn.className = "modal-confirm-btn confirm-primary";
    confirmBtn.textContent = "Reschedule";
    confirmBtn.addEventListener("click", function () {
      if (!selectedSlot) {
        showError("Please select an available time slot.");
        return;
      }
      overlay.remove();
      rescheduleAppointment(appt, selectedSlot);
    });
    btns.appendChild(confirmBtn);

    overlay.appendChild(btns);
    cardEl.appendChild(overlay);
  }

  function rescheduleAppointment(appt, newStartTime) {
    var body = {
      appointment_id: appt.id,
      patient_id: appt.patient_uuid || appt.patient_id,
      provider_id: appt.provider_uuid || appt.provider_id,
      location_id: appt.location_uuid || appt.location_id,
      note_type_id: appt.note_type_id || "",
      note_type_code: appt.note_type_code || "",
      start_time: newStartTime,
      duration_minutes: appt.duration_minutes || 30,
      rr_staff_id: appt.rr_staff_id || "",
    };

    fetch(RESCHEDULE_API, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        if (!r.ok) {
          return r.json().then(function (data) {
            throw new Error(data.error || data.detail || "Reschedule failed");
          });
        }
        return r.json();
      })
      .then(function () {
        closeAppointmentModal();
        refreshCurrentView();
      })
      .catch(function (err) {
        showError("Reschedule failed: " + err.message);
        closeAppointmentModal();
      });
  }

  // ── Entry point ────────────────────────────────────────────

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();

