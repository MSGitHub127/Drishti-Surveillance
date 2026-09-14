/**
 * Watchlist Correlation & Real-Time Alert Feed Controller
 * Test Scenario #2: Instant alert rendering, audio chime, and cooldown metrics.
 */

class AlertsController {
    constructor() {
        this.container = document.getElementById("alerts-container");
        this.alerts = [];
        this.counts = { critical: 0, high: 0, medium: 0 };
    }

    renderAlerts(alertsList) {
        this.alerts = alertsList || [];
        this.recalculateCounts();
        this.render();
    }

    addAlert(alertData) {
        alertData._isNew = true;
        this.alerts.unshift(alertData);
        this.recalculateCounts();
        this.render();
        // Remove animation flag after initial render
        setTimeout(() => {
            alertData._isNew = false;
        }, 1000);
    }

    recalculateCounts() {
        this.counts = { critical: 0, high: 0, medium: 0 };
        this.alerts.forEach(a => {
            const sev = (a.severity || "").toUpperCase();
            if (sev === "CRITICAL") this.counts.critical++;
            else if (sev === "HIGH") this.counts.high++;
            else this.counts.medium++;
        });

        document.getElementById("alert-stat-critical").textContent = this.counts.critical;
        document.getElementById("alert-stat-high").textContent = this.counts.high;
        document.getElementById("alert-stat-medium").textContent = this.counts.medium;
    }

    render() {
        if (!this.container) return;

        if (this.alerts.length === 0) {
            this.container.innerHTML = `
                <div class="empty-state" style="padding: 40px; text-align: center;">
                    <i data-lucide="shield-check" style="width: 48px; height: 48px; color: #22c55e; margin-bottom: 12px;"></i>
                    <div style="font-size: 15px; font-weight: 600; color: #fff;">No Security Alerts Active</div>
                    <div style="font-size: 12px; color: #94a3b8; margin-top: 4px;">Continuous correlation against eGujCop, VAHAN, and SARTHI active.</div>
                </div>
            `;
            if (window.lucide) window.lucide.createIcons();
            return;
        }

        this.container.innerHTML = this.alerts.map(a => `
            <div class="alert-card ${a.severity === 'CRITICAL' ? 'critical-alert' : 'high-alert'} ${a._isNew ? 'alert-item-enter' : ''}">
                <div class="alert-left">
                    <div class="alert-plate-box">${a.plate_number}</div>
                    <div class="alert-info-meta">
                        <div class="alert-title-line">
                            <span class="alert-cat">${a.category}</span>
                            <span class="alert-source-badge">${a.source_database || a.source_dept || 'eGujCop'}</span>
                            <span class="chip-pill ${a.severity === 'CRITICAL' ? 'pill-critical' : 'pill-high'}">${a.severity}</span>
                            ${a.match_type ? `<span class="chip-pill pill-neutral">${a.match_type}</span>` : ''}
                        </div>
                        <div class="alert-loc">
                            <i data-lucide="map-pin" style="width: 12px; height: 12px; display: inline-block; vertical-align: middle;"></i>
                            ${a.location_name} (${a.district}) &bull; Camera ID: <code>${a.camera_id}</code>
                        </div>
                        <div style="font-size: 11px; color: #cbd5e1;">
                            ${a.suspect_name ? `<strong>Suspect:</strong> ${a.suspect_name} &bull; ` : ''}
                            ${a.fir_reference || a.fir_number ? `<strong>FIR:</strong> ${a.fir_reference || a.fir_number} &bull; ` : ''}
                            ${a.notes ? `<em>${a.notes}</em>` : ''}
                        </div>
                        <div class="alert-time">Timestamp: <span style="font-family: var(--font-mono);">${a.event_timestamp || a.derived_timestamp}</span></div>
                    </div>
                </div>

                <div class="alert-actions">
                    <button class="btn btn-sm btn-primary" onclick="window.TraceEngine.searchPlate('${a.plate_number}')">
                        <i data-lucide="navigation"></i> Trace Route
                    </button>
                    ${!a.acknowledged ? `
                        <button class="btn btn-sm btn-secondary" onclick="window.AlertsModule.acknowledge('${a.id}')">
                            <i data-lucide="check"></i> Dispatch
                        </button>
                    ` : `
                        <span class="chip-pill pill-success"><i data-lucide="check-check"></i> ${a.escalation_status || 'DISPATCHED'}</span>
                    `}
                </div>
            </div>
        `).join("");

        if (window.lucide) window.lucide.createIcons();
    }

    async acknowledge(alertId) {
        try {
            const resp = await fetch(`/api/alerts/${alertId}/ack`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    acknowledged_by: window.AppState.currentRole,
                    escalation_status: "DISPATCHED"
                })
            });

            if (resp.ok) {
                const item = this.alerts.find(a => a.id === alertId);
                if (item) {
                    item.acknowledged = true;
                    item.escalation_status = "DISPATCHED";
                }
                this.render();
            }
        } catch (err) {
            console.error("Error acknowledging alert:", err);
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    window.AlertsModule = new AlertsController();
});
