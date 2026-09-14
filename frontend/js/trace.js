/**
 * Test Scenario #1: Cross-Camera Vehicle Movement Tracing & Route Reconstruction
 * Reconstructs the complete route traversed by any designated vehicle registration number,
 * drawing chronological polyline vectors, step-by-step playback, and movement history tables.
 */

class TraceEngineController {
    constructor() {
        this.traceMap = null;
        this.polylineLayer = null;
        this.markersLayer = null;
        this.currentTrajectory = [];
        this.currentStep = 0;
        this.isPlaying = false;
        this.playInterval = null;

        this.init();
    }

    init() {
        this.initMap();
        this.initEventListeners();
    }

    initMap() {
        const container = document.getElementById("trace-map");
        if (!container) return;

        this.traceMap = L.map("trace-map", {
            zoomControl: true,
            attributionControl: false
        }).setView([22.35, 71.85], 7);

        // Clean dark GIS basemap without watermark
        L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
            maxZoom: 16,
            attribution: ""
        }).addTo(this.traceMap);

        this.polylineLayer = L.layerGroup().addTo(this.traceMap);
        this.markersLayer = L.layerGroup().addTo(this.traceMap);
    }

    invalidateMapSize() {
        if (this.traceMap) {
            this.traceMap.invalidateSize();
        }
    }

    initEventListeners() {
        const btnRun = document.getElementById("btn-run-trace");
        const input = document.getElementById("trace-plate-input");

        if (btnRun) {
            btnRun.addEventListener("click", () => {
                const plate = input.value.trim();
                if (plate) this.executeTrace(plate);
            });
        }

        if (input) {
            input.addEventListener("keypress", (e) => {
                if (e.key === "Enter") {
                    const plate = input.value.trim();
                    if (plate) this.executeTrace(plate);
                }
            });
        }

        // Quick chip buttons
        document.querySelectorAll(".chip").forEach(chip => {
            chip.addEventListener("click", () => {
                const plate = chip.getAttribute("data-plate");
                input.value = plate;
                this.executeTrace(plate);
            });
        });

        // Playback controls
        const btnPlay = document.getElementById("btn-playback-play");
        const btnFwd = document.getElementById("btn-playback-step-fwd");
        const btnBack = document.getElementById("btn-playback-step-back");

        if (btnPlay) {
            btnPlay.addEventListener("click", () => this.togglePlayback());
        }
        if (btnFwd) {
            btnFwd.addEventListener("click", () => this.stepForward());
        }
        if (btnBack) {
            btnBack.addEventListener("click", () => this.stepBackward());
        }

        // Download CSV
        const btnCsv = document.getElementById("btn-download-trace-csv");
        if (btnCsv) {
            btnCsv.addEventListener("click", () => {
                const plate = input.value.trim();
                window.open(`/api/report?plate=${encodeURIComponent(plate)}&format=csv`, "_blank");
            });
        }
    }

    searchPlate(plateNumber) {
        // Switch to trace tab
        const tabBtn = document.querySelector('[data-tab="tab-trace"]');
        if (tabBtn) tabBtn.click();

        const input = document.getElementById("trace-plate-input");
        if (input) input.value = plateNumber;

        setTimeout(() => this.executeTrace(plateNumber), 300);
    }

    async executeTrace(plateNumber) {
        const normPlate = plateNumber.replace(/\s+/g, "").toUpperCase();
        console.log(`[TraceEngine] Reconstructing route for: ${normPlate}`);

        // Stop any running playback
        this.stopPlayback();

        try {
            const resp = await fetch(`/api/trace?plate=${encodeURIComponent(normPlate)}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            const data = await resp.json();
            this.displayTraceResults(data);
        } catch (err) {
            console.error("Error executing route trace:", err);
            alert("Trace reconstruction error: " + err.message);
        }
    }

    displayTraceResults(data) {
        // 1. Update Metrics Cards
        document.getElementById("metric-sightings").textContent = data.total_sightings;
        document.getElementById("metric-first-seen").textContent = data.first_seen ? data.first_seen.replace("T", " ").substring(0, 19) : "--";
        document.getElementById("metric-last-seen").textContent = data.last_seen ? data.last_seen.replace("T", " ").substring(0, 19) : "--";
        document.getElementById("metric-distance").textContent = `${data.total_distance_km} km`;
        document.getElementById("metric-speed").textContent = `${data.average_speed_kmh} km/h`;

        const wlStatusEl = document.getElementById("metric-watchlist-status");
        if (data.active_watchlist_match) {
            wlStatusEl.innerHTML = `<span class="chip-pill pill-critical" style="font-size: 12px;"><i data-lucide="shield-alert" style="width: 14px; height: 14px;"></i> ${data.active_watchlist_match.category.toUpperCase()} (${data.active_watchlist_match.source_dept})</span>`;
        } else {
            wlStatusEl.innerHTML = `<span class="chip-pill pill-neutral">NOT FLAGGED</span>`;
        }
        if (window.lucide) window.lucide.createIcons();

        // 2. Handle Zero-Result Gracefully
        if (data.total_sightings === 0) {
            this.clearMap();
            document.getElementById("trace-table-body").innerHTML = `
                <tr>
                    <td colspan="7" class="text-center" style="padding: 24px; color: #94a3b8;">
                        <i data-lucide="help-circle" style="width: 24px; height: 24px; margin-bottom: 6px; display: inline-block;"></i><br>
                        <strong>Zero Sightings Recorded</strong><br>
                        Vehicle registration <code>${data.plate_number}</code> has not been detected across any onboarded camera feeds.
                    </td>
                </tr>
            `;
            if (window.lucide) window.lucide.createIcons();
            document.getElementById("playback-step-counter").textContent = "Step 0 / 0";
            return;
        }

        // 3. Populate Movement History Table
        this.currentTrajectory = data.trajectory;
        this.currentStep = 0;

        const tbody = document.getElementById("trace-table-body");
        tbody.innerHTML = data.trajectory.map(pt => `
            <tr id="trace-row-${pt.step_number}" onclick="window.TraceEngine.goToStep(${pt.step_number - 1})">
                <td class="num-col"><strong style="color: #38bdf8;">${pt.step_number}</strong></td>
                <td><span style="font-family: var(--font-mono); font-size: 11px;">${pt.timestamp.replace("T", " ").substring(0, 19)}</span></td>
                <td><code>${pt.camera_id}</code></td>
                <td><strong>${pt.location_name}</strong><br><span style="font-size: 10px; color: #94a3b8;">${pt.district}</span></td>
                <td><span class="chip-pill pill-neutral">${pt.department}</span></td>
                <td class="num-col">${pt.time_delta_sec > 0 ? `+${pt.time_delta_sec}s (${pt.distance_km_from_prev} km)` : 'Initial'}</td>
                <td class="num-col">${pt.estimated_speed_kmh > 0 ? `<strong>${pt.estimated_speed_kmh}</strong> km/h` : '-'}</td>
            </tr>
        `).join("");

        // 4. Render Route on Leaflet Map
        this.renderRouteOnMap(data.trajectory);
        this.updateStepUI();
    }

    renderRouteOnMap(trajectory) {
        this.clearMap();
        if (!this.traceMap || trajectory.length === 0) return;

        const latlngs = trajectory.map(pt => [pt.lat, pt.lng]);

        // Draw connecting polyline vector with pulsating animated glow
        const polyline = L.polyline(latlngs, {
            color: "#38bdf8",
            weight: 4,
            opacity: 0.85,
            dashArray: "8, 6"
        });
        this.polylineLayer.addLayer(polyline);

        // Place numbered step markers
        trajectory.forEach(pt => {
            const isFirst = pt.step_number === 1;
            const isLast = pt.step_number === trajectory.length;
            const markerColor = isFirst ? "#22c55e" : (isLast ? "#ef4444" : "#3b82f6");

            const icon = L.divIcon({
                className: "custom-trace-step",
                html: `
                    <div style="
                        width: 24px; height: 24px; 
                        background: ${markerColor}; 
                        color: #fff; 
                        border: 2px solid #ffffff; 
                        border-radius: 50%; 
                        display: flex; align-items: center; justify-content: center; 
                        font-family: monospace; font-size: 11px; font-weight: bold;
                        box-shadow: 0 0 10px ${markerColor};
                    ">${pt.step_number}</div>
                `,
                iconSize: [24, 24],
                iconAnchor: [12, 12]
            });

            const marker = L.marker([pt.lat, pt.lng], { icon: icon });
            marker.bindPopup(`
                <div style="font-size: 12px; color: #111;">
                    <strong>Step ${pt.step_number}: ${pt.location_name}</strong><br>
                    District: ${pt.district}<br>
                    Time: ${pt.timestamp.replace("T", " ")}<br>
                    Speed: ${pt.estimated_speed_kmh} km/h
                </div>
            `);

            marker.on("click", () => {
                this.goToStep(pt.step_number - 1);
            });

            this.markersLayer.addLayer(marker);
        });

        // Fit map bounds to encompass the entire route
        if (trajectory.length === 1) {
            this.traceMap.setView([trajectory[0].lat, trajectory[0].lng], 14);
        } else if (trajectory.length > 1) {
            this.traceMap.fitBounds(polyline.getBounds(), { padding: [40, 40] });
        }
    }

    clearMap() {
        if (this.polylineLayer) this.polylineLayer.clearLayers();
        if (this.markersLayer) this.markersLayer.clearLayers();
    }

    goToStep(index) {
        if (index < 0 || index >= this.currentTrajectory.length) return;
        this.currentStep = index;
        this.updateStepUI();

        const pt = this.currentTrajectory[index];
        if (this.traceMap) {
            this.traceMap.panTo([pt.lat, pt.lng], { animate: true });
        }
    }

    stepForward() {
        if (this.currentStep < this.currentTrajectory.length - 1) {
            this.goToStep(this.currentStep + 1);
        }
    }

    stepBackward() {
        if (this.currentStep > 0) {
            this.goToStep(this.currentStep - 1);
        }
    }

    togglePlayback() {
        if (this.isPlaying) {
            this.stopPlayback();
        } else {
            this.startPlayback();
        }
    }

    startPlayback() {
        if (this.currentTrajectory.length === 0) return;
        this.isPlaying = true;
        const btn = document.getElementById("btn-playback-play");
        if (btn) btn.innerHTML = `<i data-lucide="pause"></i> Pause`;
        if (window.lucide) window.lucide.createIcons();

        if (this.currentStep >= this.currentTrajectory.length - 1) {
            this.currentStep = 0;
        }

        this.playInterval = setInterval(() => {
            if (this.currentStep < this.currentTrajectory.length - 1) {
                this.stepForward();
            } else {
                this.stopPlayback();
            }
        }, 1500);
    }

    stopPlayback() {
        this.isPlaying = false;
        if (this.playInterval) {
            clearInterval(this.playInterval);
            this.playInterval = null;
        }
        const btn = document.getElementById("btn-playback-play");
        if (btn) btn.innerHTML = `<i data-lucide="play"></i> Animate`;
        if (window.lucide) window.lucide.createIcons();
    }

    updateStepUI() {
        const total = this.currentTrajectory.length;
        const current = total > 0 ? this.currentStep + 1 : 0;
        document.getElementById("playback-step-counter").textContent = `Step ${current} / ${total}`;

        // Highlight corresponding table row
        document.querySelectorAll("#trace-table-body tr").forEach(tr => tr.classList.remove("row-active"));
        const activeRow = document.getElementById(`trace-row-${current}`);
        if (activeRow) {
            activeRow.classList.add("row-active");
            activeRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    window.TraceEngine = new TraceEngineController();
});
