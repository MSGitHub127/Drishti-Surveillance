/**
 * Unified State CCTV Integration Platform - Main App Controller
 * Team Vayunotics (GPH26)
 */

const AppState = {
    currentTab: "tab-map",
    cameras: [],
    watchlist: [],
    alerts: [],
    currentRole: "SUPER_ADMIN",
    audioEnabled: true,
    ws: null
};

document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initWebSocket();
    loadInitialData();
    initGlobalEventListeners();
});

function initTabs() {
    const tabs = document.querySelectorAll(".nav-tab");
    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            tabs.forEach(t => t.classList.remove("active"));
            tab.classList.add("active");

            const target = tab.getAttribute("data-tab");
            AppState.currentTab = target;

            document.querySelectorAll(".tab-panel").forEach(panel => {
                panel.classList.remove("active");
            });

            const activePanel = document.getElementById(target);
            if (activePanel) {
                activePanel.classList.add("active");
            }

            // Invalidate Leaflet map size on tab switch
            if (target === "tab-map" && window.GisMap) {
                setTimeout(() => window.GisMap.invalidateSize(), 200);
            }
            if (target === "tab-trace" && window.TraceEngine) {
                setTimeout(() => window.TraceEngine.invalidateMapSize(), 200);
            }
            if (target === "tab-health" && window.HealthModule) {
                window.HealthModule.refreshCharts();
            }
        });
    });
}

function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/alerts`;

    try {
        AppState.ws = new WebSocket(wsUrl);

        AppState.ws.onopen = () => {
            console.log("[WebSocket] Connected to CCTV Real-Time Alert Bus");
        };

        AppState.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === "ALERT") {
                    handleIncomingAlert(msg.data);
                } else if (msg.type === "DETECTION") {
                    handleIncomingDetection(msg.data);
                }
            } catch (err) {
                console.error("[WebSocket] Parse error:", err);
            }
        };

        AppState.ws.onclose = () => {
            console.warn("[WebSocket] Disconnected. Reconnecting in 3s...");
            setTimeout(initWebSocket, 3000);
        };
    } catch (e) {
        console.error("[WebSocket] Init error:", e);
    }
}

async function loadInitialData() {
    try {
        // 1. Fetch Cameras
        const camResp = await fetch("/api/registry/cameras");
        if (camResp.ok) {
            AppState.cameras = await camResp.json();
            document.getElementById("telemetry-cam-count").textContent = `${AppState.cameras.length} / 50`;
            if (window.GisMap) {
                window.GisMap.renderCameras(AppState.cameras);
            }
            if (window.StreamGrid) {
                window.StreamGrid.initGrid(AppState.cameras);
            }
        }

        // 2. Fetch Watchlist
        const wlResp = await fetch("/api/watchlist");
        if (wlResp.ok) {
            AppState.watchlist = await wlResp.json();
            renderWatchlistTable(AppState.watchlist);
        }

        // 3. Fetch Existing Alerts
        const alertResp = await fetch("/api/alerts");
        if (alertResp.ok) {
            AppState.alerts = await alertResp.json();
            if (window.AlertsModule) {
                window.AlertsModule.renderAlerts(AppState.alerts);
            }
        }

        // 4. Probe Hardware USB Webcam Status
        await checkWebcamStatus();
        if (!window._webcamPollStarted) {
            window._webcamPollStarted = true;
            setInterval(checkWebcamStatus, 8000);
        }
    } catch (err) {
        console.error("Error loading initial data:", err);
    }
}

async function checkWebcamStatus() {
    try {
        const resp = await fetch("/api/webcam/status");
        if (!resp.ok) return;
        const data = await resp.json();

        const el = document.getElementById("telemetry-webcam-val");
        const btnText = document.getElementById("btn-webcam-text");
        const btnToggle = document.getElementById("btn-toggle-webcam");

        if (el) {
            if (data.is_streaming_webcam) {
                el.className = "t-val status-online";
                el.innerHTML = `<span class="pulse-dot"></span> CONNECTED (Device ${data.available_devices[0] ? data.available_devices[0].index : 0})`;
            } else if (data.hardware_detected) {
                el.className = "t-val";
                el.innerHTML = `<span class="pulse-dot" style="background:#eab308; box-shadow:0 0 6px #eab308;"></span> DETECTED (Standby)`;
            } else {
                el.className = "t-val";
                el.innerHTML = `<span class="pulse-dot" style="background:#94a3b8;"></span> STANDBY (Simulation)`;
            }
        }

        if (btnText) {
            if (data.is_streaming_webcam) {
                btnText.textContent = "USB Webcam: ACTIVE (Click to switch to Sim)";
                if (btnToggle) {
                    btnToggle.classList.remove("btn-secondary");
                    btnToggle.classList.add("btn-primary");
                }
            } else {
                btnText.textContent = data.hardware_detected ? "Switch to USB Webcam" : "USB Webcam: Standby";
                if (btnToggle) {
                    btnToggle.classList.remove("btn-primary");
                    btnToggle.classList.add("btn-secondary");
                }
            }
        }

        const tileBadge = document.getElementById("badge-source-cam-val-001");
        if (tileBadge) {
            if (data.is_streaming_webcam) {
                tileBadge.style.color = "#4ade80";
                tileBadge.innerHTML = `<i data-lucide="camera"></i> LIVE USB WEBCAM`;
            } else {
                tileBadge.style.color = "#38bdf8";
                tileBadge.innerHTML = `<i data-lucide="video"></i> SURVEILLANCE FEED`;
            }
            if (window.lucide) window.lucide.createIcons();
        }
    } catch (e) {
        // Silently catch polling errors
    }
}

function handleIncomingAlert(alertData) {
    AppState.alerts.unshift(alertData);
    if (window.AlertsModule) {
        window.AlertsModule.addAlert(alertData);
    }

    // Flash camera tile border on Video Wall if visible (without obstructing video feeds)
    if (alertData.camera_id) {
        const tile = document.getElementById(`cam-tile-${alertData.camera_id}`);
        if (tile) {
            tile.classList.add("tile-alert-flash");
            setTimeout(() => tile.classList.remove("tile-alert-flash"), 4000);
        }
    }

    // Play audible siren/chime if enabled
    if (AppState.audioEnabled) {
        playAlertSound(alertData.severity);
    }

    // Update telemetry badge
    const badge = document.getElementById("nav-alert-badge");
    const countEl = document.getElementById("telemetry-alert-count");
    if (badge) badge.textContent = AppState.alerts.length;
    if (countEl) countEl.textContent = AppState.alerts.length;
}

function handleIncomingDetection(detectionData) {
    if (window.StreamGrid && window.StreamGrid.handleDetection) {
        window.StreamGrid.handleDetection(detectionData);
    }
}

function playAlertSound(severity) {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);

        if (severity === "CRITICAL") {
            osc.frequency.setValueAtTime(880, audioCtx.currentTime); // High alarm
            osc.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.3);
            gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
            gain.gain.linearRampToValueAtTime(0.01, audioCtx.currentTime + 0.3);
            osc.start();
            osc.stop(audioCtx.currentTime + 0.3);
        } else {
            osc.frequency.setValueAtTime(587.33, audioCtx.currentTime);
            gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
            gain.gain.linearRampToValueAtTime(0.01, audioCtx.currentTime + 0.2);
            osc.start();
            osc.stop(audioCtx.currentTime + 0.2);
        }
    } catch (e) {
        // AudioContext may be blocked before user interaction
    }
}

function renderWatchlistTable(items) {
    const tbody = document.getElementById("watchlist-table-body");
    if (!tbody) return;

    if (items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="text-center">No watchlist entries found.</td></tr>`;
        return;
    }

    tbody.innerHTML = items.map(item => `
        <tr>
            <td><strong style="font-family: var(--font-mono); color: #facc15; font-size: 13px;">${item.plate_number}</strong></td>
            <td>${item.person_name || '<span class="text-muted">Unknown</span>'}</td>
            <td><span class="chip-pill ${item.category === 'Stolen Vehicle' ? 'pill-critical' : 'pill-high'}">${item.category}</span></td>
            <td><span class="chip-pill pill-neutral">${item.source_dept}</span></td>
            <td><span style="font-family: var(--font-mono); font-size: 11px;">${item.fir_number || '-'}</span></td>
            <td>${item.vehicle_make_model || '-'}</td>
            <td><span class="chip-pill ${item.severity === 'CRITICAL' ? 'pill-critical' : (item.severity === 'HIGH' ? 'pill-high' : 'pill-medium')}">${item.severity}</span></td>
            <td><span class="chip-pill pill-success"><span class="pulse-dot"></span> Active</span></td>
            <td>
                <button class="btn btn-sm btn-secondary" onclick="window.TraceEngine.searchPlate('${item.plate_number}')">
                    <i data-lucide="navigation"></i> Trace
                </button>
            </td>
        </tr>
    `).join("");

    if (window.lucide) window.lucide.createIcons();
}

function initGlobalEventListeners() {
    // Audio Mute Toggle
    const btnAudio = document.getElementById("btn-audio-toggle");
    if (btnAudio) {
        btnAudio.addEventListener("click", () => {
            AppState.audioEnabled = !AppState.audioEnabled;
            btnAudio.innerHTML = AppState.audioEnabled ? `<i data-lucide="volume-2"></i>` : `<i data-lucide="volume-x"></i>`;
            if (window.lucide) window.lucide.createIcons();
        });
    }

    // RBAC Role Switcher
    const rbacSelect = document.getElementById("rbac-role-select");
    if (rbacSelect) {
        rbacSelect.addEventListener("change", (e) => {
            AppState.currentRole = e.target.value;
            console.log(`[RBAC] Switched operator role to: ${AppState.currentRole}`);
            // Apply department filtering view
            if (window.GisMap) {
                let deptFilter = "";
                if (AppState.currentRole === "POLICE_OFFICER") deptFilter = "POLICE";
                if (AppState.currentRole === "RTO_OFFICER") deptFilter = "RTO";
                if (AppState.currentRole === "FCS_OFFICER") deptFilter = "FCS";
                document.getElementById("filter-map-dept").value = deptFilter;
                window.GisMap.filterMarkers();
            }
        });
    }

    // Sync /api/ingest Catalogue Button
    const btnSync = document.getElementById("btn-sync-catalog");
    if (btnSync) {
        btnSync.addEventListener("click", async () => {
            btnSync.disabled = true;
            btnSync.innerHTML = `<i data-lucide="refresh-cw"></i> Syncing...`;
            try {
                const resp = await fetch("/api/registry/sync", { method: "POST" });
                const res = await resp.json();
                alert(`Catalog Synchronization Complete: ${res.synced_cameras || 50} cameras synced from /api/ingest contract.`);
                loadInitialData();
            } catch (err) {
                alert("Catalog sync failed: " + err.message);
            } finally {
                btnSync.disabled = false;
                btnSync.innerHTML = `<i data-lucide="refresh-cw"></i> Sync /api/ingest`;
                if (window.lucide) window.lucide.createIcons();
            }
        });
    }

    // Export Evaluation Report Button
    const btnExport = document.getElementById("btn-export-eval-report");
    if (btnExport) {
        btnExport.addEventListener("click", () => {
            window.open("/api/report?format=markdown", "_blank");
        });
    }

    // Add Watchlist Modal Controls
    const modal = document.getElementById("modal-add-watchlist");
    const btnOpenModal = document.getElementById("btn-add-watchlist-modal");
    const btnCloseModal = document.getElementById("btn-close-wl-modal");
    const btnCancelModal = document.getElementById("btn-cancel-wl");
    const btnSaveModal = document.getElementById("btn-save-wl");

    if (btnOpenModal) btnOpenModal.addEventListener("click", () => modal.classList.add("active"));
    if (btnCloseModal) btnCloseModal.addEventListener("click", () => modal.classList.remove("active"));
    if (btnCancelModal) btnCancelModal.addEventListener("click", () => modal.classList.remove("active"));

    if (btnSaveModal) {
        btnSaveModal.addEventListener("click", async () => {
            const plate = document.getElementById("wl-in-plate").value.trim();
            if (!plate) {
                alert("Please enter a vehicle registration plate number.");
                return;
            }

            const payload = {
                plate_number: plate,
                person_name: document.getElementById("wl-in-name").value.trim(),
                category: document.getElementById("wl-in-cat").value,
                source_dept: document.getElementById("wl-in-source").value,
                fir_number: document.getElementById("wl-in-fir").value.trim(),
                severity: document.getElementById("wl-in-severity").value,
                notes: document.getElementById("wl-in-notes").value.trim()
            };

            try {
                const resp = await fetch("/api/watchlist", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                if (resp.ok) {
                    modal.classList.remove("active");
                    loadInitialData();
                    alert(`Target plate ${plate} added to active law enforcement watchlist.`);
                }
            } catch (err) {
                alert("Error saving watchlist item: " + err.message);
            }
        });
    }

    // Toggle USB Live Webcam Button
    const btnToggleWebcam = document.getElementById("btn-toggle-webcam");
    if (btnToggleWebcam) {
        btnToggleWebcam.addEventListener("click", async () => {
            btnToggleWebcam.disabled = true;
            try {
                const resp = await fetch("/api/webcam/toggle", { method: "POST" });
                const data = await resp.json();
                await checkWebcamStatus();

                // Force refresh video element on cam-val-001 tile
                const img = document.getElementById("stream-img-cam-val-001");
                if (img) {
                    img.src = `/api/stream/cam-val-001/live?t=${Date.now()}`;
                }

                const msg = data.streaming_webcam 
                    ? "Camera 1 (cam-val-001) is now LIVE from your USB Webcam!" 
                    : "Camera 1 (cam-val-001) switched back to highway surveillance video.";
                alert(msg);
            } catch (err) {
                alert("Error switching camera mode: " + err.message);
            } finally {
                btnToggleWebcam.disabled = false;
                if (window.lucide) window.lucide.createIcons();
            }
        });
    }
}

window.AppState = AppState;
