"""
Technical Evaluation Output Report Generator
Generates formal evaluation reports for the Technical Committee:
- Detected vehicles and license plates with PTS-derived timestamps
- Cross-camera movement history for designated test vehicles
- Watchlist match correlation and automated alert summaries
- Formats: Markdown, JSON, CSV, and HTML printable report
"""

import json
import csv
import io
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Detection, Camera, Department, Alert, Watchlist
from app.config import settings

logger = logging.getLogger("cctv.report")

class EvaluationReportGenerator:

    @staticmethod
    async def generate_report_data(
        session: AsyncSession,
        plate_number: Optional[str] = None,
        limit: int = 200
    ) -> Dict[str, Any]:
        """Gathers all detection and alert telemetry required for the evaluation report."""
        query = (
            select(Detection, Camera, Department)
            .join(Camera, Detection.camera_id == Camera.id)
            .outerjoin(Department, Camera.dept_id == Department.id)
        )

        if plate_number:
            norm = plate_number.replace(" ", "").upper()
            query = query.where(Detection.normalized_plate == norm)

        query = query.order_by(Detection.pts_timestamp.asc()).limit(limit)
        res = await session.execute(query)
        rows = res.all()

        detections_data = []
        for det, cam, dept in rows:
            dept_name = dept.name if dept else "General"
            detections_data.append({
                "detection_id": det.id,
                "plate_number": det.plate_number,
                "confidence": round(det.confidence, 3),
                "pts_timestamp": det.pts_timestamp.isoformat(),
                "camera_id": cam.id,
                "camera_name": cam.name,
                "department": dept_name,
                "district": cam.district,
                "city": cam.city,
                "location_name": cam.location_name,
                "lat": cam.lat,
                "lng": cam.lng,
                "codec": cam.codec,
                "storage_type": cam.storage_type,
                "vehicle_type": det.vehicle_type
            })

        # Fetch alerts generated
        alert_query = select(Alert).order_by(Alert.event_timestamp.asc())
        if plate_number:
            alert_query = alert_query.where(Alert.plate_number == plate_number.replace(" ", "").upper())
        alert_res = await session.execute(alert_query)
        alerts_list = []
        for a in alert_res.scalars().all():
            alerts_list.append({
                "alert_code": a.alert_code,
                "plate_number": a.plate_number,
                "category": a.category,
                "severity": a.severity,
                "location": a.location_name,
                "district": a.district,
                "department": a.department,
                "timestamp": a.event_timestamp.isoformat(),
                "status": a.escalation_status
            })

        report = {
            "title": "Gujarat State Unified CCTV Integration & AI Surveillance - Technical Evaluation Report",
            "team_name": settings.TEAM_NAME,
            "system_version": settings.PROJECT_VERSION,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "evaluated_vehicle": plate_number or "ALL_ONBOARDED_FEEDS",
            "total_detections_recorded": len(detections_data),
            "total_watchlist_alerts": len(alerts_list),
            "detections": detections_data,
            "alerts": alerts_list
        }
        return report

    @staticmethod
    def export_markdown(data: Dict[str, Any]) -> str:
        """Renders report data as formatted GitHub Markdown."""
        md = []
        md.append(f"# {data['title']}\n")
        md.append(f"**Team**: {data['team_name']} | **Generated**: {data['generated_at']} | **Target Plate**: `{data['evaluated_vehicle']}`\n")
        md.append("## 1. Executive Summary\n")
        md.append(f"- **Total Detected Sighting Records**: {data['total_detections_recorded']}")
        md.append(f"- **Total Real-Time Watchlist Alerts Triggered**: {data['total_watchlist_alerts']}\n")

        md.append("## 2. Cross-Camera Movement & Sighting Timeline\n")
        md.append("| Step | Timestamp (PTS Monotonic) | Plate Number | Confidence | Camera ID | Location & District | Department | Coordinates |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        for idx, d in enumerate(data["detections"]):
            coords = f"{d['lat']:.4f}, {d['lng']:.4f}"
            md.append(f"| {idx+1} | `{d['pts_timestamp']}` | **{d['plate_number']}** | {d['confidence']*100:.1f}% | `{d['camera_id']}` | {d['location_name']}, {d['district']} | {d['department']} | `{coords}` |")

        md.append("\n## 3. Automated Real-Time Watchlist Alerts\n")
        md.append("| Alert Code | Plate Number | Category | Severity | Location | Department | Timestamp | Status |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        for a in data["alerts"]:
            md.append(f"| `{a['alert_code']}` | **{a['plate_number']}** | {a['category']} | **{a['severity']}** | {a['location']} | {a['department']} | `{a['timestamp']}` | `{a['status']}` |")

        md.append("\n---\n*Report compiled by Team Vayunotics GPH26 Evaluation Toolchain.*")
        return "\n".join(md)

    @staticmethod
    def export_csv(data: Dict[str, Any]) -> str:
        """Renders detections as CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Step", "PlateNumber", "PTS_Timestamp", "Confidence", "CameraID", "CameraName",
            "Department", "District", "City", "Location", "Latitude", "Longitude", "Codec", "StorageType"
        ])
        for idx, d in enumerate(data["detections"]):
            writer.writerow([
                idx + 1, d["plate_number"], d["pts_timestamp"], d["confidence"], d["camera_id"],
                d["camera_name"], d["department"], d["district"], d["city"], d["location_name"],
                d["lat"], d["lng"], d["codec"], d["storage_type"]
            ])
        return output.getvalue()
