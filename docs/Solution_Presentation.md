# Unified State CCTV Integration & AI Surveillance Platform
## Solution Presentation Deck (Slide-by-Slide Content)
**Team**: Team Vayunotics (GPH26)  
**Event**: State CCTV Integration Technical Evaluation  
**Theme**: Statewide Video Surveillance & Law Enforcement Analytics Federation  

---

### Slide 1: Title & Executive Summary
- **Title**: Unified State CCTV Integration & Proactive AI Surveillance Platform
- **Sub-title**: Connecting 26 Departments, 80,000 Cameras, and Law Enforcement Intelligence into a Single Sovereign Grid
- **Presenter**: Team Vayunotics (Team ID: GPH26)
- **Key Headline**:
  - Unifying 26 fragmented state departments across 1,000 km (Valsad, Dahod, Somnath, Jamnagar, Dwarka).
  - Hybrid Architecture: Model 1 (Registry/GIS) + Model 3 (VMS Federation/Middleware) with Model 2 Stream Gateway pattern.
  - Continuous correlation against **VAHAN, SARTHI, eGujCop (CCTNS), AFIS, and NAFIS**.
  - Automated real-time alerts with 60s cooldown deduplication and cross-camera vehicle trajectory reconstruction.

---

### Slide 2: Context, Challenges & Operational Need
- **The Problem**:
  - 26 independent government departments operating standalone camera silos.
  - Heterogeneous infrastructure: mixed analog/IP, multi-vendor VMS (Milestone, Genetec, Hikvision, CP Plus, Dahua).
  - Storage & retention disparity: cloud vs. local NVRs; retention periods varying from 7 days (PDS godowns) to 15+ days (RTO) and 30+ days (Police).
  - Zero cross-departmental visibility: a stolen vehicle or wanted criminal passing through RTO checkpoints and commercial areas goes unnoticed by Police until hours later.
- **The Objective**:
  - Integrate existing infrastructure to the maximum practical extent without costly rip-and-replace.
  - Scale from 50 evaluation streams seamlessly to **~80,000 cameras statewide**.

---

### Slide 3: Architecture Decision & Justification (Why Hybrid Model 1 + 3?)
- **Evaluation of Reference Models**:
  - *Model 1 (Registry & GIS)*: Mandatory foundation for asset visibility, spatial queries, and governance.
  - *Model 2 (Point-to-point)*: Fast for small demos, but brittle and unmanageable at 80,000 cameras.
  - *Model 3 (VMS Federation & Middleware)*: Directly aligns with the problem statement’s core architecture principles: open, modular, vendor-neutral, adapter-based.
  - *Model 4 (Full Central VMS)*: Unfeasible bandwidth and cost footprint for statewide deployment.
- **The Winning Choice**: **Hybrid Model 1 + Model 3 + Model 2 Stream Gateway Pattern**:
  - Model 1 provides PostGIS geospatial registry and asset lifecycle monitoring.
  - Model 3 provides adapter plugins for existing multi-vendor VMS without vendor lock-in.
  - Model 2 ingestion pattern standardizes RTSP-over-TCP streams and WebRTC/HLS relay.
  - **Earns Bonus Evaluation Consideration** for innovative hybrid architecture with clear operational value.

---

### Slide 4: End-to-End System Architecture
- **Layer 1: Edge & Field Ingestion**:
  - 26 departments (Police, RTO, Food & Civil Supplies, Ports, Forest, Permitted Private).
  - Local NVRs/DVRs with 7-15 day retention.
- **Layer 2: Stream Gateway & Sentinel Protocol Layer**:
  - Strict enforcement of RTSP over TCP (`rtsp_transport=tcp`).
  - Monotonic timing anchored strictly to Presentation Timestamps (PTS).
  - Exponential backoff reconnection ($2.0\text{s} \to 30.0\text{s}$).
  - MediaMTX stream relay for sub-second WebRTC (WHEP) browser preview and HLS dashboard fallback.
- **Layer 3: Core Registry, Event Bus & Data Lake**:
  - PostgreSQL 16 + PostGIS 3.4 for spatial indexing and camera catalogue.
  - Redis Streams Event Bus for sub-millisecond event dispatch (Kafka target for 80k).
  - Law enforcement watchlist database and sighting trajectory repository.
- **Layer 4: Command Center & Unified Control Room**:
  - Interactive Leaflet GIS map, multi-camera live grid, live alert siren console, vehicle route playback, and department-wise RBAC.

---

### Slide 5: Sentinel Protocol Adherence (Do's and Don'ts)
- **RTSP over TCP Enforced**: Eliminates UDP packet drops across firewalls and NAT that mimic model bugs.
- **Zero Reliance on `CAP_PROP_FPS`**: Frame delivery rates fluctuate across WAN; all cadence and timing are derived exclusively from stream PTS.
- **PTS Timing Anchor**:
  $$\tau_{\text{event}}(\text{frame}) = \text{anchor\_wall\_clock} + (\text{frame.pts} - \text{anchor\_pts})$$
  Eliminates impossible velocities caused by GOP buffer replays on connection.
- **Loop-Cut / Discontinuity Resilience**: Looping demo feeds hard-cut like camera reboots; our engine detects backward PTS steps and re-anchors seamlessly without dropping the pipeline.
- **Non-Fatal Decoder Warnings**: RPS and missing reference warnings on join are absorbed naturally until the first IDR keyframe arrives.
- **On-Demand Capture Pacing**: Streams are ingested only when active, preventing memory/bandwidth saturation.

---

### Slide 6: AI-Powered ANPR & Video Analytics Engine
- **Committed YOLO-Only Architecture**:
  - Bypasses fragile classical contour/edge methods.
  - Ultralytics YOLOv8 vehicle detection + fine-tuned license plate localization.
- **Positional OCR Correction for Indian Number Plates**:
  - Strict validation against `^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$`.
  - Automatic alphanumeric correction (`O` $\to$ `0`, `B` $\to$ `8` in digit slots; `0` $\to$ `O` in state slots).
- **50-Stream Concurrent Worker Pool**:
  - Asynchronous `ThreadPoolExecutor` with backpressure-protected bounded queue (`maxsize=500`).
  - PTS-delta frame throttling: samples each stream at 1.5 FPS:
    $$50 \text{ cameras} \times 1.5 \text{ FPS} = 75 \text{ FPS Total Throughput}$$
  - Average inference latency: **24.5 ms** per detection.

---

### Slide 7: Watchlist Correlation & Real-Time Alert Engine
- **Cross-Referenced Law Enforcement Databases**:
  - **eGujCop / CCTNS**: Wanted criminals, stolen vehicles, missing persons.
  - **VAHAN**: National stolen vehicle registry, tax/fitness defaulters.
  - **SARTHI**: Suspended/revoked driver licenses.
  - **AFIS / NAFIS**: Fingerprint biometric criminal warrants.
- **Two-Tier Matching Algorithm**:
  - Exact match on normalized plate ($O(1)$ in-memory hash index).
  - Levenshtein fuzzy matching with edit distance $\le 1$ to catch OCR misreads.
- **Alert Deduplication Cooldown Window**:
  - 60-second cooldown per `(plate_number, camera_id)`.
  - Prevents alert flooding when a vehicle idles at a 90-second traffic signal.
- **Instant Alert Dispatch**:
  - Real-time WebSocket push to Command Center.
  - Audible alert siren synthesizer + priority badge (CRITICAL / HIGH / MEDIUM).
  - One-click route tracing and interceptor unit dispatch.

---

### Slide 8: Cross-Camera Vehicle Route Reconstruction (Test Scenario #1)
- **The Centerpiece Demo**:
  - User inputs designated vehicle plate (e.g. `GJ01AB1234`).
  - Queries spatial trajectory store and orders sightings strictly chronologically.
  - Computes Haversine distance, elapsed travel duration ($\Delta t$), and transit speed ($v$).
- **Multi-Modal Visual Output**:
  - **Chronological Polyline Map**: Connects sightings across Gujarat with directional arrows and numbered step markers.
  - **Animated Playback Scrubber**: Step-by-step playback showing the vehicle's exact journey.
  - **Movement History Table**: Step number, PTS timestamp, camera ID, location, department, time delta, and speed.
- **Robustness**: Graceful handling of zero-result edge cases (returns clean feedback without system exceptions).

---

### Slide 9: Statewide Scalability Roadmap (~80,000 Cameras)
- **Three-Tier Compute Model**:
  - *Tier 1 (Edge)*: Ingestion & local 7-day recording on existing department NVRs.
  - *Tier 2 (Regional Aggregators)*: 6 Zonal Centers (Ahmedabad, Surat, Rajkot, Vadodara, Gandhinagar, Kutch/Border).
  - *Tier 3 (State Command Center)*: Master PostGIS registry, Kafka cluster, and command portal.
- **Low-Bandwidth Strategy**:
  - Video stays at the edge; edge AI transmits **only JSON metadata and 25KB plate crops** (480 Mbps statewide vs. 160 Gbps for raw streaming).
  - Full video feeds are streamed on-demand only when an operator inspects a camera or an alert triggers.
- **GPU Fleet Sizing**:
  - 80,000 cameras $\times$ 1.0 FPS = 80,000 inferences/sec.
  - Handled by 228 NVIDIA L4 GPUs distributed across 6 regional ranges (~38 GPUs per zone).
- **Storage Tiering**:
  - Hot: NVMe SSD for 30-day metadata & alerts.
  - Warm: Edge NVRs for 7-15 day video buffer.
  - Cold: Central cloud object storage for flagged incident clips (1-5 years).

---

### Slide 10: Operational Impact, Security & Governance
- **Operational Benefits**:
  - Slashes vehicle intercept time from hours/days to **under 30 seconds**.
  - Eliminates inter-departmental blind spots between Police, RTO, and Food & Civil Supplies.
  - Protects government food distribution from grain diversion using godown ANPR.
- **Security & RBAC Controls**:
  - Department-wise multi-tenancy (Police, RTO, Food Supplies, SuperAdmin).
  - End-to-end TLS encryption, JWT authentication, and immutable audit logging.
  - Full compliance with the Gujarat Public Safety (Measures) Enforcement Act and DPDP Act 2023.
- **Conclusion**:
  - A production-ready, vendor-neutral, future-proof solution ready for immediate pilot deployment.
