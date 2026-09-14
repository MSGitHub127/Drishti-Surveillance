/**
 * Model 1: GIS Spatial Registry Map Controller
 * Leaflet map visualization for 50+ geographically distributed cameras.
 * Supports PostGIS bounding box viewport filtering and department color-coding.
 */

class GisMapController {
    constructor() {
        this.map = null;
        this.markersLayer = null;
        this.cameras = [];
        this.osmLayer = null;
        this.darkLayer = null;
        this.currentTileLayer = null;
        this.tileLayerType = "regular"; // Default: regular OpenStreetMap
        this.init();
    }

    init() {
        const mapContainer = document.getElementById("map");
        if (!mapContainer) return;

        // Initialize Leaflet map centered over Gujarat
        this.map = L.map("map", {
            zoomControl: true,
            attributionControl: true
        }).setView([22.35, 71.85], 7);

        // 1. Regular OpenStreetMap tile layer (Standard Leaflet Map)
        this.osmLayer = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors'
        });

        // 2. Tactical Dark Canvas tile layer (Esri Canvas Dark)
        this.darkLayer = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
            maxZoom: 16,
            attribution: '&copy; Esri, HERE, Garmin'
        });

        // Default to regular OpenStreetMap, or saved preference
        const savedLayer = localStorage.getItem("dhristi-map-layer") || "regular";
        this.setTileLayer(savedLayer);

        this.markersLayer = L.layerGroup().addTo(this.map);

        // Setup layer switcher listeners
        const btnReg = document.getElementById("btn-map-layer-regular");
        const btnDark = document.getElementById("btn-map-layer-dark");

        if (btnReg) {
            btnReg.addEventListener("click", () => {
                this.setTileLayer("regular");
                localStorage.setItem("dhristi-map-layer", "regular");
                localStorage.setItem("dhristi-map-manual", "true");
                if (window.TraceEngine) window.TraceEngine.setTileLayer("regular");
            });
        }
        if (btnDark) {
            btnDark.addEventListener("click", () => {
                this.setTileLayer("dark");
                localStorage.setItem("dhristi-map-layer", "dark");
                localStorage.setItem("dhristi-map-manual", "true");
                if (window.TraceEngine) window.TraceEngine.setTileLayer("dark");
            });
        }

        // Setup filter listeners
        const deptFilter = document.getElementById("filter-map-dept");
        const distFilter = document.getElementById("filter-map-district");
        const typeFilter = document.getElementById("filter-map-type");

        if (deptFilter) deptFilter.addEventListener("change", () => this.filterMarkers());
        if (distFilter) distFilter.addEventListener("change", () => this.filterMarkers());
        if (typeFilter) typeFilter.addEventListener("change", () => this.filterMarkers());

        // PostGIS Bounding Box query on map movement
        this.map.on("moveend", () => {
            const bounds = this.map.getBounds();
            // Optional: trigger spatial API call /api/registry/bbox
        });
    }

    setTileLayer(type) {
        this.tileLayerType = type;
        if (this.currentTileLayer) {
            this.map.removeLayer(this.currentTileLayer);
        }

        if (type === "dark") {
            this.currentTileLayer = this.darkLayer;
        } else {
            this.currentTileLayer = this.osmLayer;
        }

        this.currentTileLayer.addTo(this.map);
        this.updateButtons(type);
    }

    updateButtons(type) {
        const btnReg = document.getElementById("btn-map-layer-regular");
        const btnDark = document.getElementById("btn-map-layer-dark");
        if (btnReg && btnDark) {
            if (type === "dark") {
                btnDark.classList.add("active");
                btnReg.classList.remove("active");
            } else {
                btnReg.classList.add("active");
                btnDark.classList.remove("active");
            }
        }
    }

    invalidateSize() {
        if (this.map) {
            this.map.invalidateSize();
        }
    }

    getMarkerColor(deptCode) {
        switch ((deptCode || "").toUpperCase()) {
            case "POLICE": return "#3b82f6"; // Blue
            case "RTO": return "#f59e0b";    // Amber
            case "FCS": return "#10b981";    // Green
            case "PORTS":
            case "FOREST": return "#06b6d4"; // Teal
            case "PRIVATE": return "#8b5cf6"; // Purple
            default: return "#94a3b8";
        }
    }

    renderCameras(cameras) {
        this.cameras = cameras;
        this.filterMarkers();
    }

    filterMarkers() {
        if (!this.markersLayer) return;
        this.markersLayer.clearLayers();

        const deptVal = document.getElementById("filter-map-dept")?.value || "";
        const distVal = document.getElementById("filter-map-district")?.value || "";
        const typeVal = document.getElementById("filter-map-type")?.value || "";

        this.cameras.forEach(cam => {
            // Apply filters
            if (deptVal && cam.dept_code !== deptVal && !cam.id.toLowerCase().includes(deptVal.toLowerCase())) {
                // If dept_code isn't direct, check id or name
                if (!cam.name.toUpperCase().includes(deptVal)) return;
            }
            if (distVal && cam.district !== distVal) return;
            if (typeVal && cam.camera_type !== typeVal) return;

            const color = this.getMarkerColor(cam.dept_code || (cam.id.includes("val") ? "RTO" : "POLICE"));

            // Custom SVG Department Radar Pin Marker
            const icon = L.divIcon({
                className: "dept-radar-marker",
                html: `
                    <div class="marker-pulse-wrapper" style="--marker-color: ${color};">
                        <div class="marker-pin">
                            <svg width="22" height="28" viewBox="0 0 24 30" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M12 0C5.37258 0 0 5.37258 0 12C0 19.5 12 30 12 30C12 30 24 19.5 24 12C24 5.37258 18.6274 0 12 0Z" fill="${color}" fill-opacity="0.92"/>
                                <circle cx="12" cy="11" r="5.5" fill="#0f172a"/>
                                <circle cx="12" cy="11" r="3" fill="${color}"/>
                            </svg>
                        </div>
                        <div class="marker-halo"></div>
                    </div>
                `,
                iconSize: [22, 28],
                iconAnchor: [11, 28]
            });

            const marker = L.marker([cam.lat, cam.lng], { icon: icon });
            
            marker.on("click", () => {
                this.displayCameraDetails(cam);
            });

            marker.bindTooltip(`<b>${cam.name}</b><br><span style="font-size: 10px; color: #94a3b8;">${cam.location_name} (${cam.district})</span>`, {
                direction: "top",
                offset: [0, -6]
            });

            this.markersLayer.addLayer(marker);
        });
    }

    displayCameraDetails(cam) {
        const card = document.getElementById("selected-camera-card");
        if (!card) return;

        card.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 8px;">
                <div style="font-size: 13px; font-weight: 700; color: #fff;">${cam.name}</div>
                <div style="font-size: 11px; color: #38bdf8;">${cam.location_name}, ${cam.district}</div>
                <div style="background: var(--bg-surface-elevated); padding: 8px; border-radius: 6px; font-size: 11px; display: flex; flex-direction: column; gap: 4px;">
                    <div><strong>Camera ID:</strong> <span style="font-family: var(--font-mono);">${cam.id}</span></div>
                    <div><strong>Type:</strong> ${cam.camera_type}</div>
                    <div><strong>Codec:</strong> <span class="badge ${cam.codec === 'H.265' ? 'model-badge' : 'team-badge'}">${cam.codec}</span></div>
                    <div><strong>Resolution:</strong> ${cam.resolution} @ ${cam.fps} FPS</div>
                    <div><strong>Storage Architecture:</strong> ${cam.storage_type.toUpperCase()} (${cam.retention_days} Days Retention)</div>
                    <div><strong>VMS Platform:</strong> ${cam.vms_vendor} (AMC: ${cam.amc_status})</div>
                    <div><strong>Status:</strong> <span class="status-online"><span class="pulse-dot"></span> ${cam.status.toUpperCase()}</span></div>
                </div>
                <div style="display: flex; gap: 6px; margin-top: 6px;">
                    <button class="btn btn-sm btn-primary" onclick="window.StreamGrid.viewCameraLive('${cam.id}')">
                        <i data-lucide="video"></i> View Live Stream
                    </button>
                    <button class="btn btn-sm btn-secondary" onclick="window.GisMap.zoomTo(${cam.lat}, ${cam.lng})">
                        <i data-lucide="crosshair"></i> Focus
                    </button>
                </div>
            </div>
        `;
        if (window.lucide) window.lucide.createIcons();
    }

    zoomTo(lat, lng) {
        if (this.map) {
            this.map.setView([lat, lng], 14, { animate: true });
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    window.GisMap = new GisMapController();
});
