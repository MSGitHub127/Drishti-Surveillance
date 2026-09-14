/**
 * Model 3 & Model 2: Unified Real Multi-Camera Live Stream Relay Grid
 * Consumes real backend MJPEG streaming endpoints (/api/stream/{camera_id}/live)
 * and dynamically overlays real AI ANPR detection bounding boxes from WebSockets.
 * Strictly eliminates fake canvas animations and simulations.
 */

class StreamGridController {
    constructor() {
        this.container = document.getElementById("stream-grid-container");
        this.cameras = [];
        this.activeGridSize = 4;
        this.activeTiles = [];
        this.heartbeatIntervals = {};
        this.overlayTimeouts = {};
        this.initEventListeners();
    }

    initEventListeners() {
        document.querySelectorAll(".btn-layout").forEach(btn => {
            btn.addEventListener("click", () => {
                document.querySelectorAll(".btn-layout").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                this.activeGridSize = parseInt(btn.getAttribute("data-grid") || "4");
                this.rebuildGrid();
            });
        });
    }

    initGrid(cameras) {
        this.cameras = cameras || [];
        this.rebuildGrid();
    }

    rebuildGrid() {
        if (!this.container) return;
        this.container.innerHTML = "";

        // Clear existing heartbeat intervals
        Object.values(this.heartbeatIntervals).forEach(id => clearInterval(id));
        this.heartbeatIntervals = {};

        // Clear existing overlay timers
        Object.values(this.overlayTimeouts).forEach(id => clearTimeout(id));
        this.overlayTimeouts = {};

        // Adjust layout
        if (this.activeGridSize === 4) {
            this.container.style.gridTemplateColumns = "repeat(2, 1fr)";
            this.container.style.gridTemplateRows = "repeat(2, 1fr)";
        } else if (this.activeGridSize === 6) {
            this.container.style.gridTemplateColumns = "repeat(3, 1fr)";
            this.container.style.gridTemplateRows = "repeat(2, 1fr)";
        } else {
            this.container.style.gridTemplateColumns = "repeat(3, 1fr)";
            this.container.style.gridTemplateRows = "repeat(3, 1fr)";
        }

        let selectedCams = [];
        const preferredIds = ["cam-val-001", "cam-ahm-001", "cam-dah-001", "cam-jam-001", "cam-dwk-001", "cam-som-001"];
        for (const pid of preferredIds) {
            const found = this.cameras.find(c => c.id === pid);
            if (found && selectedCams.length < this.activeGridSize) {
                selectedCams.push(found);
            }
        }
        for (const cam of this.cameras) {
            if (selectedCams.length >= this.activeGridSize) break;
            if (!selectedCams.some(c => c.id === cam.id)) {
                selectedCams.push(cam);
            }
        }
        this.activeTiles = selectedCams;

        selectedCams.forEach((cam, idx) => {
            this.createTile(cam, idx);
        });

        if (window.lucide) window.lucide.createIcons();
    }

    createTile(camera, tileIndex) {
        const tile = document.createElement("div");
        tile.className = "stream-tile";
        tile.id = `stream-tile-${tileIndex}`;
        tile.setAttribute("data-camera-id", camera.id);

        tile.innerHTML = `
            <div class="tile-header">
                <div class="tile-title">
                    <select class="role-select cam-selector" data-tile="${tileIndex}">
                        ${this.cameras.map(c => `<option value="${c.id}" ${c.id === camera.id ? 'selected' : ''}>${c.name}</option>`).join("")}
                    </select>
                </div>
                <div style="display: flex; gap: 4px; align-items: center;">
                    ${camera.id === 'cam-val-001' ? `<span class="tile-badge badge-cam-source" id="badge-source-${camera.id}" style="color: #38bdf8;"><i data-lucide="video"></i> SURVEILLANCE FEED</span>` : ''}
                    <span class="tile-badge">${camera.codec || 'H.264'}</span>
                    <span class="tile-badge">${camera.resolution || '1080p'}</span>
                </div>
            </div>
            <div class="tile-video-area" id="video-area-${camera.id}">
                <div class="tile-media-wrapper">
                    <img id="stream-img-${camera.id}" class="tile-live-img" src="/api/stream/${camera.id}/live" alt="${camera.name}" onerror="setTimeout(() => { if (this) this.src = '/api/stream/${camera.id}/live?' + Date.now(); }, 2000)" />
                    <canvas id="overlay-cam-${camera.id}" class="tile-detection-overlay" width="640" height="360"></canvas>
                    <div class="tile-overlay-status"><span class="pulse-dot"></span> LIVE (TCP)</div>
                    <div class="tile-overlay-pts" id="pts-overlay-${camera.id}">PTS: 00:00:00.000 | ${camera.location_name || camera.district}</div>
                </div>
            </div>
        `;

        this.container.appendChild(tile);

        // Selector listener
        const selector = tile.querySelector(".cam-selector");
        if (selector) {
            selector.addEventListener("change", (e) => {
                const newCam = this.cameras.find(c => c.id === e.target.value);
                if (newCam) {
                    this.replaceTile(tileIndex, newCam);
                }
            });
        }

        // Start periodic heartbeat for demand-driven idle timeout prevention
        this.startHeartbeat(camera.id);
    }

    replaceTile(tileIndex, newCamera) {
        const oldCam = this.activeTiles[tileIndex];
        if (oldCam) {
            this.stopHeartbeat(oldCam.id);
            fetch(`/api/stream/${oldCam.id}/stop`, { method: "POST" }).catch(() => {});
        }

        this.activeTiles[tileIndex] = newCamera;
        const tile = document.getElementById(`stream-tile-${tileIndex}`);
        if (!tile) return;

        tile.setAttribute("data-camera-id", newCamera.id);
        const sel = tile.querySelector(".tile-title select");
        if (sel) sel.value = newCamera.id;

        const badges = tile.querySelectorAll(".tile-badge");
        if (badges[0]) badges[0].textContent = newCamera.codec || "H.264";
        if (badges[1]) badges[1].textContent = newCamera.resolution || "1080p";

        const videoArea = tile.querySelector(".tile-video-area");
        videoArea.id = `video-area-${newCamera.id}`;
        videoArea.innerHTML = `
            <div class="tile-media-wrapper">
                <img id="stream-img-${newCamera.id}" class="tile-live-img" src="/api/stream/${newCamera.id}/live" alt="${newCamera.name}" onerror="setTimeout(() => { if (this) this.src = '/api/stream/${newCamera.id}/live?' + Date.now(); }, 2000)" />
                <canvas id="overlay-cam-${newCamera.id}" class="tile-detection-overlay" width="640" height="360"></canvas>
                <div class="tile-overlay-status"><span class="pulse-dot"></span> LIVE (TCP)</div>
                <div class="tile-overlay-pts" id="pts-overlay-${newCamera.id}">PTS: 00:00:00.000 | ${newCamera.location_name || newCamera.district}</div>
            </div>
        `;

        this.startHeartbeat(newCamera.id);
    }

    startHeartbeat(cameraId) {
        this.stopHeartbeat(cameraId);
        this.heartbeatIntervals[cameraId] = setInterval(() => {
            fetch(`/api/stream/${cameraId}/heartbeat`, { method: "POST" }).catch(() => {});
        }, 12000);
    }

    stopHeartbeat(cameraId) {
        if (this.heartbeatIntervals[cameraId]) {
            clearInterval(this.heartbeatIntervals[cameraId]);
            delete this.heartbeatIntervals[cameraId];
        }
    }

    handleDetection(detectionData) {
        if (!detectionData || !detectionData.camera_id) return;

        const cameraId = detectionData.camera_id;
        const canvas = document.getElementById(`overlay-cam-${cameraId}`);
        const ptsEl = document.getElementById(`pts-overlay-${cameraId}`);

        if (ptsEl && detectionData.derived_timestamp) {
            const timePart = detectionData.derived_timestamp.split("T")[1]?.replace("Z", "") || "";
            ptsEl.textContent = `PTS: ${timePart} | ${detectionData.location_name || cameraId}`;
        }

        // Trigger camera tile alert flash to attract operator attention
        const tileEl = document.querySelector(`[data-camera-id="${cameraId}"]`);
        if (tileEl) {
            tileEl.classList.add("tile-alert-flash");
            setTimeout(() => {
                tileEl.classList.remove("tile-alert-flash");
            }, 1800);
        }

        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Draw Real AI Bounding Box & High-Visibility Tactical Reticle
        if (detectionData.bbox && Array.isArray(detectionData.bbox) && detectionData.bbox.length === 4) {
            const [x1, y1, x2, y2] = detectionData.bbox;
            const origW = detectionData.frame_width || 1280.0;
            const origH = detectionData.frame_height || 720.0;
            const scaleX = canvas.width / origW;
            const scaleY = canvas.height / origH;

            const bx = Math.max(0, x1 * scaleX);
            const by = Math.max(0, y1 * scaleY);
            const bw = Math.min(canvas.width - bx, (x2 - x1) * scaleX);
            const bh = Math.min(canvas.height - by, (y2 - y1) * scaleY);

            const isAlert = detectionData.is_alert || (detectionData.watchlist_match && detectionData.watchlist_match.matched);
            const accentColor = isAlert ? "#ef4444" : "#00f0ff";
            const glowColor = isAlert ? "rgba(239, 68, 68, 0.8)" : "rgba(0, 240, 255, 0.8)";

            // 1. Glowing Bounding Reticle
            ctx.shadowColor = glowColor;
            ctx.shadowBlur = 10;
            ctx.strokeStyle = accentColor;
            ctx.lineWidth = 2.0;
            ctx.strokeRect(bx, by, bw, bh);
            ctx.shadowBlur = 0;

            // 2. Tactical 4-Corner Target Brackets
            const cornerLen = Math.max(8, Math.min(18, bw / 3, bh / 3));
            ctx.strokeStyle = isAlert ? "#f87171" : "#38bdf8";
            ctx.lineWidth = 3.5;
            ctx.lineCap = "square";

            // Top-Left
            ctx.beginPath();
            ctx.moveTo(bx, by + cornerLen);
            ctx.lineTo(bx, by);
            ctx.lineTo(bx + cornerLen, by);
            ctx.stroke();

            // Top-Right
            ctx.beginPath();
            ctx.moveTo(bx + bw - cornerLen, by);
            ctx.lineTo(bx + bw, by);
            ctx.lineTo(bx + bw, by + cornerLen);
            ctx.stroke();

            // Bottom-Left
            ctx.beginPath();
            ctx.moveTo(bx, by + bh - cornerLen);
            ctx.lineTo(bx, by + bh);
            ctx.lineTo(bx + cornerLen, by + bh);
            ctx.stroke();

            // Bottom-Right
            ctx.beginPath();
            ctx.moveTo(bx + bw - cornerLen, by + bh);
            ctx.lineTo(bx + bw, by + bh);
            ctx.lineTo(bx + bw, by + bh - cornerLen);
            ctx.stroke();

            // 3. Authentic Indian HSRP Plate Badge directly above bounding box
            const plateStr = detectionData.plate || "DETECTED";
            const vType = (detectionData.vehicle_type || "VEHICLE").toUpperCase();
            const confPct = Math.round((detectionData.confidence || 0.90) * 100);

            ctx.font = "800 13px 'JetBrains Mono', monospace";
            const plateMetrics = ctx.measureText(plateStr);
            const plateW = plateMetrics.width + 12;
            const indW = 24;
            const metaStr = ` ${vType} • ${confPct}% `;
            ctx.font = "600 10px 'Google Sans', sans-serif";
            const metaMetrics = ctx.measureText(metaStr);
            const metaW = metaMetrics.width + 8;

            const badgeTotalW = indW + plateW + metaW;
            const badgeH = 22;
            const badgeX = Math.max(2, Math.min(canvas.width - badgeTotalW - 2, bx));
            const badgeY = Math.max(2, by - badgeH - 4);

            // Left: Blue "IND" Tab
            ctx.fillStyle = "#1e3a8a";
            ctx.fillRect(badgeX, badgeY, indW, badgeH);
            ctx.fillStyle = "#ffffff";
            ctx.font = "bold 9px 'Google Sans', sans-serif";
            ctx.fillText("IND", badgeX + 4, badgeY + 14);

            // Middle: High-Contrast License Plate
            ctx.fillStyle = isAlert ? "#fef08a" : "#ffffff";
            ctx.fillRect(badgeX + indW, badgeY, plateW, badgeH);
            ctx.strokeStyle = "rgba(0,0,0,0.4)";
            ctx.lineWidth = 1;
            ctx.strokeRect(badgeX + indW, badgeY, plateW, badgeH);
            ctx.fillStyle = "#000000";
            ctx.font = "800 13px 'JetBrains Mono', monospace";
            ctx.fillText(plateStr, badgeX + indW + 6, badgeY + 16);

            // Right: Vehicle Class & Confidence Chip
            ctx.fillStyle = isAlert ? "#991b1b" : "#0f172a";
            ctx.fillRect(badgeX + indW + plateW, badgeY, metaW, badgeH);
            ctx.fillStyle = isAlert ? "#fecaca" : "#38bdf8";
            ctx.font = "600 10px 'Google Sans', sans-serif";
            ctx.fillText(metaStr, badgeX + indW + plateW + 3, badgeY + 15);
        }

        // Smooth animated fade-out after 3.2s, clear canvas at 3.6s
        if (this.overlayTimeouts[cameraId]) clearTimeout(this.overlayTimeouts[cameraId]);
        canvas.classList.remove("fade-out");
        this.overlayTimeouts[cameraId] = setTimeout(() => {
            canvas.classList.add("fade-out");
            setTimeout(() => {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                canvas.classList.remove("fade-out");
            }, 400);
        }, 3200);
    }

    viewCameraLive(cameraId) {
        const tabBtn = document.querySelector('[data-tab="tab-streams"]');
        if (tabBtn) tabBtn.click();

        const cam = this.cameras.find(c => c.id === cameraId);
        if (cam) {
            this.replaceTile(0, cam);
        }
    }

    initCctvInspectionModal() {
        const btnOpen = document.getElementById("btn-open-cctv-inspect");
        const modal = document.getElementById("modal-inspect-cctv");
        const btnClose = document.getElementById("btn-close-inspect-modal");
        const fileInput = document.getElementById("inspect-cctv-file");
        const dropZone = document.getElementById("inspect-drop-zone");

        if (btnOpen && modal) {
            btnOpen.addEventListener("click", () => {
                modal.classList.add("active");
            });
        }
        const btnCloseFooter = document.getElementById("btn-close-inspect-modal-footer");
        if (btnClose && modal) {
            btnClose.addEventListener("click", () => {
                modal.classList.remove("active");
            });
        }
        if (btnCloseFooter && modal) {
            btnCloseFooter.addEventListener("click", () => {
                modal.classList.remove("active");
            });
        }
        if (modal) {
            modal.addEventListener("click", (e) => {
                if (e.target === modal) modal.classList.remove("active");
            });
        }
        if (dropZone && fileInput) {
            dropZone.addEventListener("click", () => fileInput.click());
            dropZone.addEventListener("dragover", (e) => {
                e.preventDefault();
                dropZone.classList.add("dragover");
            });
            dropZone.addEventListener("dragleave", () => {
                dropZone.classList.remove("dragover");
            });
            dropZone.addEventListener("drop", (e) => {
                e.preventDefault();
                dropZone.classList.remove("dragover");
                if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    this.executeCctvInspect(e.dataTransfer.files[0]);
                }
            });
            fileInput.addEventListener("change", (e) => {
                if (e.target.files && e.target.files.length > 0) {
                    this.executeCctvInspect(e.target.files[0]);
                }
            });
        }
    }

    async executeCctvInspect(file) {
        const resultContainer = document.getElementById("inspect-results-area");
        const loadingEl = document.getElementById("inspect-loading");
        const loadingText = document.getElementById("inspect-loading-text");
        
        const isVideo = file.type.startsWith("video/") || 
            /\.(mp4|avi|mov|mkv|webm|m4v)$/i.test(file.name);

        if (loadingText) {
            loadingText.textContent = isVideo
                ? "Analyzing CCTV Video Frames & Tracking License Plates..."
                : "Executing Multi-Scale Vehicle Localization & Deep OCR...";
        }

        if (loadingEl) loadingEl.style.display = "block";
        if (resultContainer) resultContainer.style.display = "none";

        const formData = new FormData();
        formData.append("file", file);

        try {
            const endpoint = isVideo ? "/api/anpr/inspect-video" : "/api/anpr/inspect-image";
            const resp = await fetch(endpoint, {
                method: "POST",
                body: formData
            });
            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                throw new Error(errData.detail || `HTTP ${resp.status}`);
            }
            const data = await resp.json();
            if (isVideo) {
                this.renderCctvVideoResults(data, file);
            } else {
                this.renderCctvInspectionResults(data);
            }
        } catch (err) {
            alert("CCTV Inspection Error: " + err.message);
        } finally {
            if (loadingEl) loadingEl.style.display = "none";
        }
    }

    renderCctvInspectionResults(data) {
        const resultContainer = document.getElementById("inspect-results-area");
        const imageView = document.getElementById("inspect-image-view");
        const videoView = document.getElementById("inspect-video-view");
        if (!resultContainer) return;
        resultContainer.style.display = "flex";
        if (imageView) imageView.style.display = "grid";
        if (videoView) videoView.style.display = "none";

        const imgEl = document.getElementById("inspect-annotated-img");
        if (imgEl && data.annotated_image) {
            imgEl.src = data.annotated_image;
        }

        const statsEl = document.getElementById("inspect-meta-stats");
        if (statsEl) {
            statsEl.innerHTML = `
                <div style="display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap;">
                    <span class="chip-pill pill-neutral">Media: <strong>CCTV Snapshot</strong></span>
                    <span class="chip-pill pill-neutral">Plates Detected: <strong>${data.total_detected}</strong></span>
                    <span class="chip-pill pill-neutral">Latency: <strong>${data.latency_ms} ms</strong></span>
                    ${data.watchlist_alert ? '<span class="chip-pill pill-critical"><i data-lucide="shield-alert"></i> WATCHLIST TARGET FLAGGED</span>' : '<span class="chip-pill pill-success"><i data-lucide="shield-check"></i> VERIFIED CLEAR</span>'}
                </div>
            `;
        }

        const listEl = document.getElementById("inspect-plates-list");
        if (listEl) {
            if (!data.detections || data.detections.length === 0) {
                listEl.innerHTML = `<div class="empty-state" style="padding: 20px;">No vehicle license plates detected in this image.</div>`;
            } else {
                listEl.innerHTML = data.detections.map(d => `
                    <div style="background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 12px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <div style="display: flex; align-items: center; gap: 12px;">
                            <div class="alert-plate-box" style="font-size: 15px; padding: 4px 10px;">${d.normalized_plate}</div>
                            <div>
                                <div style="font-size: 12px; font-weight: 700; color: #fff;">${d.vehicle_type || 'Vehicle'} • ${Math.round(d.confidence * 100)}% Confidence</div>
                                <div style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono);">Raw OCR: "${d.plate_text || d.normalized_plate}"</div>
                            </div>
                        </div>
                        <div>
                            ${d.watchlist_match && d.watchlist_match.matched ? `
                                <span class="chip-pill pill-critical">WANTED (${d.watchlist_match.category})</span>
                            ` : `
                                <span class="chip-pill pill-success">CLEAN</span>
                            `}
                        </div>
                    </div>
                `).join("");
            }
        }
        if (window.lucide) window.lucide.createIcons();
    }

    renderCctvVideoResults(data, file) {
        const resultContainer = document.getElementById("inspect-results-area");
        const imageView = document.getElementById("inspect-image-view");
        const videoView = document.getElementById("inspect-video-view");
        if (!resultContainer) return;
        resultContainer.style.display = "flex";
        if (imageView) imageView.style.display = "none";
        if (videoView) videoView.style.display = "flex";

        const meta = data.video_metadata || {};
        const statsEl = document.getElementById("inspect-meta-stats");
        if (statsEl) {
            statsEl.innerHTML = `
                <div style="display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap;">
                    <span class="chip-pill pill-neutral">Media: <strong>CCTV Video Clip</strong></span>
                    <span class="chip-pill pill-neutral">Duration: <strong>${meta.duration_sec || 0}s (${meta.sampled_frames || 0} sampled frames)</strong></span>
                    <span class="chip-pill pill-neutral">Unique Vehicles: <strong>${data.unique_plates ? data.unique_plates.length : 0}</strong></span>
                    <span class="chip-pill pill-neutral">Processing Time: <strong>${data.latency_ms} ms</strong></span>
                    ${data.watchlist_alert ? '<span class="chip-pill pill-critical"><i data-lucide="shield-alert"></i> WATCHLIST TARGET FLAGGED</span>' : '<span class="chip-pill pill-success"><i data-lucide="shield-check"></i> VERIFIED CLEAR</span>'}
                </div>
            `;
        }

        const keyframeImg = document.getElementById("inspect-video-keyframe");
        const keyframeLabel = document.getElementById("inspect-keyframe-label");
        const platesListEl = document.getElementById("inspect-video-plates-list");
        const timelineEl = document.getElementById("inspect-video-timeline");

        if (data.unique_plates && data.unique_plates.length > 0) {
            if (keyframeImg && data.unique_plates[0].best_thumbnail) {
                keyframeImg.src = data.unique_plates[0].best_thumbnail;
                keyframeImg.style.display = "block";
            }
            if (keyframeLabel) {
                keyframeLabel.textContent = `Forensic Keyframe: ${data.unique_plates[0].plate} (${data.unique_plates[0].vehicle_type}) @ ${data.unique_plates[0].first_seen_sec}s`;
            }

            if (platesListEl) {
                platesListEl.innerHTML = data.unique_plates.map((up, idx) => `
                    <div class="cctv-video-plate-card" data-idx="${idx}" style="background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: border-color 0.2s;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <div class="alert-plate-box" style="font-size: 14px; padding: 3px 8px;">${up.plate}</div>
                            <div>
                                <div style="font-size: 12px; font-weight: 700; color: #fff;">${up.vehicle_type} • ${Math.round(up.best_confidence * 100)}% Conf</div>
                                <div style="font-size: 11px; color: var(--accent-cyan); font-family: var(--font-mono);">
                                    Sighted: ${up.first_seen_sec}s &rarr; ${up.last_seen_sec}s (${up.sightings_count} hits)
                                </div>
                            </div>
                        </div>
                        <div>
                            ${up.watchlist_match && up.watchlist_match.matched ? `
                                <span class="chip-pill pill-critical">WANTED (${up.watchlist_match.category})</span>
                            ` : `
                                <span class="chip-pill pill-success">CLEAN</span>
                            `}
                        </div>
                    </div>
                `).join("");

                platesListEl.querySelectorAll(".cctv-video-plate-card").forEach(card => {
                    card.addEventListener("click", () => {
                        const idx = parseInt(card.dataset.idx);
                        const item = data.unique_plates[idx];
                        if (item && item.best_thumbnail && keyframeImg) {
                            keyframeImg.src = item.best_thumbnail;
                            if (keyframeLabel) {
                                keyframeLabel.textContent = `Forensic Keyframe: ${item.plate} (${item.vehicle_type}) @ ${item.first_seen_sec}s`;
                            }
                        }
                    });
                });
            }
        } else {
            if (platesListEl) {
                platesListEl.innerHTML = `<div class="empty-state" style="padding: 16px;">No vehicles or license plates detected in uploaded video footage.</div>`;
            }
        }

        if (timelineEl) {
            if (!data.timeline || data.timeline.length === 0) {
                timelineEl.innerHTML = `<div style="font-size: 12px; color: var(--text-muted); padding: 8px;">No timeline sightings recorded.</div>`;
            } else {
                timelineEl.innerHTML = data.timeline.map(t => `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: rgba(255,255,255,0.02); border-radius: 4px; font-size: 11px;">
                        <span style="font-family: var(--font-mono); color: var(--accent-cyan); font-weight: 600;">[${t.timestamp_str || t.timestamp_sec + 's'}]</span>
                        <span style="font-family: var(--font-mono); font-weight: 700; color: #fff;">${t.plate}</span>
                        <span style="color: var(--text-muted);">${t.vehicle_type} (${Math.round(t.confidence * 100)}%)</span>
                    </div>
                `).join("");
            }
        }

        if (window.lucide) window.lucide.createIcons();
    }
}

document.addEventListener("DOMContentLoaded", () => {
    window.StreamGrid = new StreamGridController();
    window.StreamGrid.initCctvInspectionModal();
});
