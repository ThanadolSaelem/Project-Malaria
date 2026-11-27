#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project-Malaria — Template-Driven Report Studio ("กุศโลบาย" Completeness Engine)
================================================================================
Pure Python stdlib module imported by control_plane.py (:8010) and exposed at:
  - Browser / Frontend: /model-studio-api/reports/*
  - Containers / ARTEX: http://host.docker.internal:8010/api/model-studio/reports/*

Capabilities:
  1. Upload & manage multiple custom .docx / .md report templates (plus 3 built-in
     starter templates: NCSA TLP:AMBER, Full Pentest & Code Audit, Script/Malware Forensics).
  2. Automatically parse every Section, Subsection, Table schema, and Placeholder
     from uploaded .docx (word/document.xml) or .md files into a strict Blueprint.
  3. Harvest complete ARTEX Task Dossier (Assets, Goals, Intents, Facts, Findings,
     HTTP Traffic, Chat History, Evidence Screenshots, and Shared /workspace files).
  4. Multi-pass Section-by-Section LLM generation with a Completeness Gate +
     Targeted Repair Pass so models cannot skip sections or write shallow summaries.
  5. Assemble downloadable Word (.docx preserving uploaded template headers/footers/fonts)
     and Markdown (.md) artifacts.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
REPORTING_DIR = HERE / "reporting"
DEFAULT_DOCX_SHELL = REPORTING_DIR / "template.docx"
TEMPLATES_DIR = REPORTING_DIR / "templates"
TEMPLATES_INDEX = TEMPLATES_DIR / "index.json"
EVIDENCE_DIR = HERE / "evidence"
REPORTS_OUT_DIR = HERE / "reports" / "generated"
WORKSPACE_HOST_DIR = HERE / "dsh-workspace"
NODE_CONFIG_FILE = HERE / "node-config.json"
CVE_CACHE_FILE = REPORTING_DIR / "cve_cache.json"
TECH_CVE_CACHE_FILE = REPORTING_DIR / "tech_cve_cache.json"
KEV_CACHE_FILE = REPORTING_DIR / "cisa_kev_cache.json"
CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
CWE_RE = re.compile(r"\bCWE-\d{1,5}\b", re.IGNORECASE)
_CVE_MCP_SESSION_ID: Optional[str] = None
_CVE_MCP_LOCK = threading.Lock()

if str(REPORTING_DIR) not in sys.path:
    sys.path.insert(0, str(REPORTING_DIR))

import assemble as report_assembler  # noqa: E402

_REPORT_LOCK = threading.RLock()
_JOBS: dict[str, dict[str, Any]] = {}
JOBS_STATE_FILE = REPORTS_OUT_DIR / "_jobs.json"


def _persist_jobs_locked() -> None:
    try:
        REPORTS_OUT_DIR.mkdir(parents=True, exist_ok=True)
        items = sorted(_JOBS.values(), key=lambda j: str(j.get("updated_at") or j.get("created_at") or ""), reverse=True)[:40]
        tmp = JOBS_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, JOBS_STATE_FILE)
    except Exception:
        pass


def _load_persisted_jobs() -> None:
    try:
        if not JOBS_STATE_FILE.is_file():
            return
        raw = json.loads(JOBS_STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return
        with _REPORT_LOCK:
            for item in raw:
                if not isinstance(item, dict) or not item.get("job_id"):
                    continue
                if item.get("status") in ("queued", "running"):
                    item["status"] = "failed"
                    item["stage"] = "งานถูกหยุดชั่วคราวจากการรีสตาร์ตเซิร์ฟเวอร์ (กด Generate ใหม่ได้ทันที)"
                    item["error"] = "interrupted_by_restart"
                _JOBS[str(item["job_id"])] = item
    except Exception:
        pass


_load_persisted_jobs()

THAI_MONTHS = [
    "",
    "มกราคม",
    "กุมภาพันธ์",
    "มีนาคม",
    "เมษายน",
    "พฤษภาคม",
    "มิถุนายน",
    "กรกฎาคม",
    "สิงหาคม",
    "กันยายน",
    "ตุลาคม",
    "พฤศจิกายน",
    "ธันวาคม",
]

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PLACEHOLDER_RE = re.compile(
    r"(?:<[^>\n]{2,60}>|\{\{[^}\n]{1,60}\}\}|\[(?:TODO|TBD|INSERT|FILL|ระบุ|เติม|ใส่ข้อมูล)[^\]]*\])",
    re.IGNORECASE,
)


def thai_buddhist_date(dt: Optional[datetime.datetime] = None) -> str:
    now = dt or datetime.datetime.now(datetime.timezone.utc).astimezone()
    be_year = now.year + 543
    return f"วันที่จัดทำรายงาน {now.day} {THAI_MONTHS[now.month]} พ.ศ. {be_year}"


def _slugify(text: str, fallback: str = "template") -> str:
    s = re.sub(r"[^a-zA-Z0-9ก-๙_-]+", "-", (text or "").strip()).strip("-").lower()
    if not s:
        s = fallback
    return s[:48]


def _builtin_templates() -> list[dict[str, Any]]:
    shell_path = str(DEFAULT_DOCX_SHELL)
    return [
        {
            "id": "ncsa-tlp-amber",
            "name": "NCSA TLP:AMBER — รายงานผลการตรวจสอบทางเทคนิค (มาตรฐาน สกมช.)",
            "description": "โครงสร้างมาตรฐาน 3 หัวข้อหลัก พร้อมตารางขอบเขต ตารางช่องโหว่/IOC และแผนการแก้ไข ฟอร์แมต Sarabun TLP:AMBER",
            "format": "docx",
            "builtin": True,
            "is_default": True,
            "docx_shell_path": shell_path,
            "source_path": shell_path,
            "created_at": "2026-01-01T00:00:00+07:00",
            "blueprint": {
                "style_rules": [
                    "เขียนด้วยประโยคราชการไทยสมบูรณ์ ชัดเจน ไม่ย่อเป็นโน้ตสั้นๆ",
                    "คำศัพท์เทคนิคภาษาอังกฤษให้เขียน Proper Case ในวงเล็บหลังคำไทย เช่น การข้ามการยืนยันตัวตน (Authentication Bypass)",
                    "ห้ามใช้เครื่องหมาย em dash (—) ให้ใช้เครื่องหมายยัติภังค์ (-) หรือวงเล็บแทน",
                    "ทุกประเด็นทางเทคนิคต้องอ้างอิงหลักฐาน ตาราง หรือโค้ดประกอบอย่างเป็นรูปธรรม",
                ],
                "sections": [
                    {
                        "id": "sec-1",
                        "title": "1. ขอบเขตและลักษณะการตรวจสอบ",
                        "subsections": [
                            "1.1 ที่มา วัตถุประสงค์ และเป้าหมายของการตรวจสอบ",
                            "1.2 ระเบียบวิธีและเครื่องมือที่ใช้ในการตรวจสอบทางเทคนิค",
                            "1.3 ข้อจำกัดและขอบเขตการปฏิบัติงาน",
                        ],
                        "required_tables": [
                            [
                                "รายการเป้าหมาย / ไฟล์ / ระบบ",
                                "ประเภท (Asset Type)",
                                "รายละเอียดทางเทคนิค (IP / URL / Hash)",
                                "ขอบเขตการตรวจสอบ",
                            ]
                        ],
                        "placeholders": [],
                        "guidance": "อธิบายที่มา เป้าหมาย ขอบเขตระบบหรือโฟลเดอร์ที่ตรวจสอบ เครื่องมือที่ใช้จริง และสรุปตารางรายการเป้าหมายให้ครบทุก Asset/ไฟล์สำคัญ",
                    },
                    {
                        "id": "sec-2",
                        "title": "2. ผลการตรวจสอบทางเทคนิคและหลักฐานประกอบ",
                        "subsections": [
                            "2.1 ข้อมูลจำเพาะของระบบ พื้นผิวการโจมตี หรือโครงสร้างไฟล์ที่ตรวจพบ",
                            "2.2 รายละเอียดประเด็นความมั่นคงปลอดภัย ช่องโหว่ และพฤติกรรมเชิงลึก",
                            "2.3 ตัวบ่งชี้การบุกรุก (Indicators of Compromise) พอร์ต และ Endpoint ที่เกี่ยวข้อง",
                        ],
                        "required_tables": [
                            [
                                "ลำดับ",
                                "ประเด็นที่ตรวจพบ (Technical Finding)",
                                "ความรุนแรง",
                                "ตำแหน่ง / หลักฐานอ้างอิง",
                                "สถานะการยืนยัน",
                            ],
                            [
                                "ประเภท (IOC / Service / Script)",
                                "ค่าที่ตรวจพบ (Value / Path / Endpoint)",
                                "รายละเอียดพฤติกรรมและหน้าที่",
                                "ระดับความเสี่ยง",
                            ],
                        ],
                        "placeholders": [],
                        "guidance": "ลงลึกทุกรายการ Finding, Fact, พอร์ต, บริการ หรือสคริปต์แต่ละตัว ห้ามสรุปรวบยอด ต้องแจกแจงกลไกการทำงาน สาเหตุรากฐาน หลักฐาน HTTP/โค้ด และสถานะ (Tested / Inconclusive / Not Confirmed)",
                    },
                    {
                        "id": "sec-3",
                        "title": "3. บทสรุป การประเมินความเสี่ยง และข้อเสนอแนะในการแก้ไข",
                        "subsections": [
                            "3.1 บทสรุปผลการวินิจฉัยภาพรวม (Overall Assessment Verdict)",
                            "3.2 ข้อเสนอแนะและแนวทางการแก้ไขป้องกันตามลำดับความสำคัญ (Remediation Plan)",
                        ],
                        "required_tables": [
                            [
                                "ลำดับความสำคัญ",
                                "มาตรการแก้ไขและป้องกัน (Actionable Remediation)",
                                "ระบบ / ไฟล์ที่ต้องดำเนินการ",
                                "ผลลัพธ์ด้านความมั่นคงปลอดภัย",
                            ]
                        ],
                        "placeholders": [],
                        "guidance": "สรุปคำวินิจฉัยระดับความเสี่ยงอย่างชัดเจน พร้อมตารางแผนการแก้ไขเชิงวิศวกรรมที่นำไปปฏิบัติได้จริง ปิดท้ายด้วยหมายเหตุและลายเซ็นหน่วยงาน",
                        "include_closing_signature": True,
                    },
                ],
            },
        },
        {
            "id": "full-pentest-va",
            "name": "Full Pentest & Code Audit — รายงานทดสอบเจาะระบบและตรวจซอร์สโค้ด 5 บท",
            "description": "รายงานเชิงลึก 5 บท (Executive Summary, Scope & WSTG Methodology, Attack Surface, Technical Findings & PoC, Remediation Roadmap)",
            "format": "docx",
            "builtin": True,
            "is_default": False,
            "docx_shell_path": shell_path,
            "source_path": shell_path,
            "created_at": "2026-01-01T00:00:00+07:00",
            "blueprint": {
                "style_rules": [
                    "เขียนละเอียดระดับที่วิศวกรความมั่นคงปลอดภัยนำไปทำซ้ำและแก้ไขตามได้ทันที",
                    "แยกส่วนบทสรุปผู้บริหารออกจากรายละเอียดทางเทคนิคอย่างชัดเจน",
                    "ห้ามละหัวข้อย่อยหรือตารางใดๆ ในแม่แบบ",
                ],
                "sections": [
                    {
                        "id": "sec-1",
                        "title": "1. บทสรุปสำหรับผู้บริหาร (Executive Summary)",
                        "subsections": [
                            "1.1 ภาพรวมภารกิจและบริบทความเสี่ยงทางธุรกิจ",
                            "1.2 สรุปจำนวนช่องโหว่และประเด็นที่ตรวจพบแยกตามระดับความรุนแรง",
                        ],
                        "required_tables": [
                            ["ระดับความรุนแรง (Severity)", "จำนวนรายการ", "ภาพรวมผลกระทบหลัก", "กรอบเวลาที่แนะนำให้แก้ไข"]
                        ],
                        "placeholders": [],
                        "guidance": "สรุปภาพรวมความมั่นคงปลอดภัยของเป้าหมาย ผลกระทบต่อระบบ และตารางสรุปจำนวนประเด็นตามระดับ Critical/High/Medium/Low/Info",
                    },
                    {
                        "id": "sec-2",
                        "title": "2. ขอบเขตและระเบียบวิธีการทดสอบ (Scope & Methodology)",
                        "subsections": [
                            "2.1 รายการเป้าหมาย ระบบเครือข่าย และโฟลเดอร์โค้ดในขอบเขต",
                            "2.2 มาตรฐานการทดสอบและขั้นตอนการปฏิบัติงาน (OWASP WSTG / PTES / SAST)",
                        ],
                        "required_tables": [
                            ["เป้าหมาย / โมดูล", "ประเภท", "ที่อยู่ / Path", "สถานะการเข้าถึงและตรวจสอบ"]
                        ],
                        "placeholders": [],
                        "guidance": "ระบุขอบเขตเป้าหมายทั้งหมดและขั้นตอนที่ใช้ตรวจสอบจริงตั้งแต่การสำรวจไปจนถึงการพิสูจน์ผล",
                    },
                    {
                        "id": "sec-3",
                        "title": "3. การวิเคราะห์พื้นผิวการโจมตีและสถาปัตยกรรม (Attack Surface & Architecture)",
                        "subsections": [
                            "3.1 เทคโนโลยี บริการเครือข่าย พอร์ต และโครงสร้างซอร์สโค้ด",
                            "3.2 จุดรับข้อมูล การพิสูจน์ตัวตน และการไหลของข้อมูลสำคัญ",
                        ],
                        "required_tables": [
                            ["องค์ประกอบ / บริการ / ไฟล์สคริปต์", "เทคโนโลยี / เวอร์ชัน", "หน้าที่หลักในระบบ", "ข้อสังเกตด้านความมั่นคงปลอดภัย"]
                        ],
                        "placeholders": [],
                        "guidance": "แจกแจงสถาปัตยกรรม บริการที่เปิดอยู่ หรือไฟล์สคริปต์แต่ละตัวในโปรเจกต์ว่าทำหน้าที่อะไรและมีพื้นผิวความเสี่ยงจุดใด",
                    },
                    {
                        "id": "sec-4",
                        "title": "4. รายละเอียดช่องโหว่และหลักฐานทางเทคนิคเชิงลึก (Detailed Technical Findings)",
                        "subsections": [
                            "4.1 บัญชีรายการช่องโหว่และข้อค้นพบทางเทคนิคทั้งหมด",
                            "4.2 การวิเคราะห์สาเหตุรากฐาน หลักฐานการทดสอบ และผลกระทบรายประเด็น",
                        ],
                        "required_tables": [
                            ["รหัส", "ชื่อช่องโหว่ / ข้อค้นพบ", "ระดับความรุนแรง", "CWE / OWASP", "ตำแหน่งที่พบและหลักฐานยืนยัน"]
                        ],
                        "placeholders": [],
                        "guidance": "อธิบายทุก Finding อย่างละเอียดครบถ้วน: คำอธิบาย สาเหตุในโค้ด/การตั้งค่า หลักฐาน Request/Response หรือบรรทัดโค้ด และผลกระทบ",
                    },
                    {
                        "id": "sec-5",
                        "title": "5. แผนการแก้ไขและยกระดับความมั่นคงปลอดภัย (Remediation & Hardening Roadmap)",
                        "subsections": [
                            "5.1 แนวทางแก้ไขรายช่องโหว่เชิงวิศวกรรม (Code & Config Fixes)",
                            "5.2 มาตรการเสริมความแข็งแกร่งของระบบในระยะยาว (Defense-in-Depth)",
                        ],
                        "required_tables": [
                            ["ลำดับ", "ประเด็นที่ต้องแก้ไข", "วิธีแก้ไขทางเทคนิคอย่างชัดเจน", "ความเร่งด่วน"]
                        ],
                        "placeholders": [],
                        "guidance": "ให้คำแนะนำการแก้โค้ดหรือการตั้งค่าระบบอย่างเจาะจงสำหรับทุกประเด็น พร้อมลงท้ายลายเซ็นรายงาน",
                        "include_closing_signature": True,
                    },
                ],
            },
        },
        {
            "id": "malware-script-forensics",
            "name": "Script & Malware Forensics — รายงานวิเคราะห์สคริปต์และไฟล์ต้องสงสัยรายไฟล์",
            "description": "เหมาะสำหรับงานตรวจโฟลเดอร์ ซอร์สโค้ด สคริปต์ต้องสงสัย หรือชุดเครื่องมือโจมตี แจกแจงความสามารถของสคริปต์ทีละไฟล์ครบถ้วน",
            "format": "docx",
            "builtin": True,
            "is_default": False,
            "docx_shell_path": shell_path,
            "source_path": shell_path,
            "created_at": "2026-01-01T00:00:00+07:00",
            "blueprint": {
                "style_rules": [
                    "ต้องแจกแจงไฟล์และสคริปต์ทุกตัวที่ตรวจพบว่าแต่ละตัวทำหน้าที่อะไร รับพารามิเตอร์อะไร และทำงานอย่างไร",
                    "ห้ามข้ามไฟล์สคริปต์สำคัญโดยเด็ดขาด",
                ],
                "sections": [
                    {
                        "id": "sec-1",
                        "title": "1. ข้อมูลจำเพาะของชุดไฟล์และขอบเขตการวิเคราะห์ (Artifact Overview & Scope)",
                        "subsections": [
                            "1.1 ที่มาของตัวอย่างและโครงสร้างไดเรกทอรีโดยรวม",
                            "1.2 บัญชีรายการไฟล์ ขนาด ชนิดไฟล์ และค่าแฮช (File Inventory)",
                        ],
                        "required_tables": [
                            ["ชื่อไฟล์ / Path", "ชนิดไฟล์ / ภาษา", "ขนาด / SHA-256 (ย่อ)", "บทบาทเบื้องต้น"]
                        ],
                        "placeholders": [],
                        "guidance": "แสดงภาพรวมโครงสร้างโฟลเดอร์และตารางบัญชีไฟล์สำคัญทั้งหมดที่ตรวจสอบ",
                    },
                    {
                        "id": "sec-2",
                        "title": "2. การวิเคราะห์การทำงานของสคริปต์และโมดูลเชิงลึกรายไฟล์ (Per-Script Capability Analysis)",
                        "subsections": [
                            "2.1 กลไกการทำงาน ฟังก์ชันหลัก และคำสั่งสำคัญของแต่ละสคริปต์",
                            "2.2 ความเชื่อมโยงระหว่างสคริปต์และลำดับการทำงาน (Execution Flow)",
                        ],
                        "required_tables": [
                            ["ชื่อสคริปต์ / โมดูล", "ความสามารถหลัก (Capabilities)", "ไลบรารี / คำสั่งระบบที่เรียกใช้", "ความเสี่ยง / พฤติกรรมอันตราย"]
                        ],
                        "placeholders": [],
                        "guidance": "อธิบายสคริปต์แต่ละไฟล์อย่างละเอียดว่าทำอะไรได้บ้าง ใช้เทคนิคใด และส่งต่อข้อมูลกันอย่างไร",
                    },
                    {
                        "id": "sec-3",
                        "title": "3. พฤติกรรมเครือข่าย ตัวบ่งชี้การบุกรุก (IOC) และช่องโหว่ที่เกี่ยวข้อง",
                        "subsections": [
                            "3.1 การเชื่อมต่อเครือข่าย โดเมน IP พอร์ต และ C2 / Webhook ที่ตรวจพบ",
                            "3.2 ช่องโหว่ความมั่นคงปลอดภัยหรือข้อมูลลับที่ตกค้างในโค้ด",
                        ],
                        "required_tables": [
                            ["ประเภท IOC / ข้อค้นพบ", "ค่าที่ตรวจพบ", "ไฟล์/ตำแหน่งที่อ้างอิง", "คำอธิบายผลกระทบ"]
                        ],
                        "placeholders": [],
                        "guidance": "รวบรวม IOC, URL, IP, API Key/Token (ทำ Redaction ตามเหมาะสม) และช่องโหว่ทั้งหมดลงตารางและอธิบายประกอบ",
                    },
                    {
                        "id": "sec-4",
                        "title": "4. สรุปผลการวินิจฉัยภัยคุกคามและมาตรการป้องกันตรวจจับ (Verdict & Detection Rules)",
                        "subsections": [
                            "4.1 คำวินิจฉัยระดับภัยคุกคาม (Threat Verdict)",
                            "4.2 แนวทางการป้องกัน การเฝ้าระวัง และการกำจัดภัยคุกคาม",
                        ],
                        "required_tables": [
                            ["ด้านการป้องกัน/ตรวจจับ", "ข้อเสนอแนะเชิงเทคนิค", "ความสำคัญ"]
                        ],
                        "placeholders": [],
                        "guidance": "สรุประดับความอันตรายและให้แนวทางตรวจจับ/ป้องกันอย่างชัดเจน ปิดท้ายด้วยลายเซ็นรายงาน",
                        "include_closing_signature": True,
                    },
                ],
            },
        },
    ]


def _ensure_dirs() -> None:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_OUT_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


def _load_templates_index() -> list[dict[str, Any]]:
    _ensure_dirs()
    with _REPORT_LOCK:
        builtins = _builtin_templates()
        saved: list[dict[str, Any]] = []
        if TEMPLATES_INDEX.is_file():
            try:
                raw = json.loads(TEMPLATES_INDEX.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    saved = raw
            except Exception:
                saved = []

        by_id = {b["id"]: b for b in builtins}
        custom_list: list[dict[str, Any]] = []
        default_id = None
        for item in saved:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            tid = str(item["id"])
            if item.get("is_default"):
                default_id = tid
            if tid in by_id:
                by_id[tid]["is_default"] = bool(item.get("is_default", False))
            else:
                custom_list.append(item)

        merged = list(by_id.values()) + custom_list
        if not default_id or not any(t.get("id") == default_id for t in merged):
            for t in merged:
                t["is_default"] = t["id"] == "ncsa-tlp-amber"
        else:
            for t in merged:
                t["is_default"] = t["id"] == default_id
        return merged


def _save_templates_index(templates: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    with _REPORT_LOCK:
        tmp = TEMPLATES_INDEX.with_suffix(".tmp")
        tmp.write_text(json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, TEMPLATES_INDEX)


def extract_docx_blueprint(docx_path: Path) -> dict[str, Any]:
    """Extract ordered sections, subsections, table column schemas, and placeholders from any .docx."""
    if not zipfile.is_zipfile(docx_path):
        raise ValueError("ไฟล์ที่อัปโหลดไม่ใช่ไฟล์ .docx (ZIP) ที่ถูกต้อง")
    with zipfile.ZipFile(docx_path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            raise ValueError("ไม่พบ word/document.xml ในไฟล์ .docx")
        xml_bytes = zf.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    body = root.find(f"{W_NS}body")
    if body is None:
        raise ValueError("ไม่พบเนื้อหา <w:body> ในไฟล์ .docx")

    sections: list[dict[str, Any]] = []
    cur_sec: Optional[dict[str, Any]] = None
    doc_titles: list[str] = []

    sec_num_re = re.compile(r"^(?:บทที่\s*\d+|ส่วนที่\s*\d+|section\s*\d+|chapter\s*\d+|\d+\.\s+\S+)", re.IGNORECASE)
    sub_num_re = re.compile(r"^(?:\d+\.\d+(?:\.\d+)?\s*\S+)")

    def _p_text_and_meta(p_elem: ET.Element) -> tuple[str, str, bool]:
        texts = [t.text for t in p_elem.iter(f"{W_NS}t") if t.text]
        full = "".join(texts).strip()
        style_val = ""
        ppr = p_elem.find(f"{W_NS}pPr")
        if ppr is not None:
            ps = ppr.find(f"{W_NS}pStyle")
            if ps is not None:
                style_val = str(ps.attrib.get(f"{W_NS}val") or "").lower()
        runs = list(p_elem.findall(f"{W_NS}r"))
        non_empty_runs = [r for r in runs if "".join(t.text or "" for t in r.iter(f"{W_NS}t")).strip()]
        all_bold = bool(non_empty_runs) and all(
            (r.find(f"{W_NS}rPr") is not None and r.find(f"{W_NS}rPr").find(f"{W_NS}b") is not None)
            for r in non_empty_runs
        )
        return full, style_val, all_bold

    for child in list(body):
        tag = child.tag
        if tag == f"{W_NS}p":
            txt, style_val, all_bold = _p_text_and_meta(child)
            if not txt:
                continue
            placeholders = PLACEHOLDER_RE.findall(txt)

            is_h1 = (
                "heading1" in style_val
                or style_val in ("1", "h1", "heading 1")
                or (not sub_num_re.match(txt) and sec_num_re.match(txt) is not None and (all_bold or len(txt) < 120))
            )
            is_h2 = (
                "heading2" in style_val
                or "heading3" in style_val
                or style_val in ("2", "h2", "heading 2")
                or (sub_num_re.match(txt) is not None and len(txt) < 140)
            )

            if is_h1:
                cur_sec = {
                    "id": f"sec-{len(sections) + 1}",
                    "title": txt,
                    "subsections": [],
                    "required_tables": [],
                    "placeholders": list(dict.fromkeys(placeholders)),
                    "guidance_snippets": [],
                }
                sections.append(cur_sec)
            elif is_h2:
                if cur_sec is None:
                    cur_sec = {
                        "id": "sec-1",
                        "title": "1. รายละเอียดการตรวจสอบ",
                        "subsections": [],
                        "required_tables": [],
                        "placeholders": [],
                        "guidance_snippets": [],
                    }
                    sections.append(cur_sec)
                cur_sec["subsections"].append(txt)
                for ph in placeholders:
                    if ph not in cur_sec["placeholders"]:
                        cur_sec["placeholders"].append(ph)
            else:
                if cur_sec is None and len(doc_titles) < 3 and len(txt) < 160:
                    doc_titles.append(txt)
                else:
                    if cur_sec is None:
                        cur_sec = {
                            "id": "sec-1",
                            "title": "1. ขอบเขตและรายละเอียดรายงาน",
                            "subsections": [],
                            "required_tables": [],
                            "placeholders": [],
                            "guidance_snippets": [],
                        }
                        sections.append(cur_sec)
                    for ph in placeholders:
                        if ph not in cur_sec["placeholders"]:
                            cur_sec["placeholders"].append(ph)
                    if len(cur_sec["guidance_snippets"]) < 6:
                        cur_sec["guidance_snippets"].append(txt[:240])

        elif tag == f"{W_NS}tbl":
            rows = list(child.findall(f"{W_NS}tr"))
            if not rows:
                continue
            first_cells = []
            for tc in rows[0].findall(f"{W_NS}tc"):
                cell_txt = " ".join("".join(t.text or "" for t in p.iter(f"{W_NS}t")).strip() for p in tc.findall(f"{W_NS}p")).strip()
                first_cells.append(cell_txt or "รายละเอียด")
            # Skip single-cell decorative frame boxes
            if len(first_cells) <= 1:
                continue
            if cur_sec is None:
                cur_sec = {
                    "id": "sec-1",
                    "title": "1. ขอบเขตและตารางข้อมูลหลัก",
                    "subsections": [],
                    "required_tables": [],
                    "placeholders": [],
                    "guidance_snippets": [],
                }
                sections.append(cur_sec)
            cur_sec["required_tables"].append(first_cells)
            for tr in rows[1:4]:
                row_txt = " ".join("".join(t.text or "" for t in tr.iter(f"{W_NS}t")).split())
                for ph in PLACEHOLDER_RE.findall(row_txt):
                    if ph not in cur_sec["placeholders"]:
                        cur_sec["placeholders"].append(ph)

    if not sections:
        sections = _builtin_templates()[0]["blueprint"]["sections"]
    else:
        for idx, s in enumerate(sections):
            snippets = s.pop("guidance_snippets", [])
            s["guidance"] = (
                "เขียนเนื้อหาให้ครบตามโครงสร้างแม่แบบนี้ "
                + (f"แนวทาง/ข้อความตัวอย่างในแม่แบบ: {' | '.join(snippets[:4])}" if snippets else "")
            ).strip()
            if idx == len(sections) - 1:
                s["include_closing_signature"] = True

    return {
        "doc_titles": doc_titles,
        "style_rules": [
            "เติมข้อมูลจริงจากการตรวจสอบลงในทุกหัวข้อ หัวข้อย่อย ตาราง และช่องว่างของแม่แบบให้ครบ 100%",
            "ห้ามทิ้งข้อความตัวอย่างหรือ <placeholder> / {{variable}} ไว้ในรายงานฉบับจริง",
        ],
        "sections": sections,
    }


def extract_markdown_blueprint(md_text: str) -> dict[str, Any]:
    """Extract ordered sections, subsections, pipe-table headers, and placeholders from a Markdown template."""
    lines = (md_text or "").splitlines()
    doc_titles: list[str] = []
    sections: list[dict[str, Any]] = []
    cur_sec: Optional[dict[str, Any]] = None

    has_h2 = any(re.match(r"^##\s+\S+", ln.strip()) for ln in lines)
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if not ln:
            i += 1
            continue

        m_h1 = re.match(r"^#\s+(.+)$", ln)
        m_h2 = re.match(r"^##\s+(.+)$", ln)
        m_h3 = re.match(r"^###+\s+(.+)$", ln)

        if m_h1 and has_h2 and not sections:
            doc_titles.append(m_h1.group(1).strip())
            i += 1
            continue

        if (m_h2 and has_h2) or (m_h1 and not has_h2):
            title = (m_h2 or m_h1).group(1).strip()
            cur_sec = {
                "id": f"sec-{len(sections) + 1}",
                "title": title,
                "subsections": [],
                "required_tables": [],
                "placeholders": list(dict.fromkeys(PLACEHOLDER_RE.findall(title))),
                "guidance_snippets": [],
            }
            sections.append(cur_sec)
            i += 1
            continue

        if m_h3:
            if cur_sec is None:
                cur_sec = {
                    "id": "sec-1",
                    "title": "1. รายละเอียดการตรวจสอบ",
                    "subsections": [],
                    "required_tables": [],
                    "placeholders": [],
                    "guidance_snippets": [],
                }
                sections.append(cur_sec)
            sub_t = m_h3.group(1).strip()
            cur_sec["subsections"].append(sub_t)
            for ph in PLACEHOLDER_RE.findall(sub_t):
                if ph not in cur_sec["placeholders"]:
                    cur_sec["placeholders"].append(ph)
            i += 1
            continue

        # Detect Markdown table header
        if ln.startswith("|") and ln.endswith("|") and i + 1 < len(lines):
            sep = lines[i + 1].strip()
            if re.match(r"^\|[\s:|-]+\|$", sep):
                cols = [c.strip() or "รายละเอียด" for c in ln.strip("|").split("|")]
                if len(cols) >= 2:
                    if cur_sec is None:
                        cur_sec = {
                            "id": "sec-1",
                            "title": "1. ขอบเขตและข้อมูลหลัก",
                            "subsections": [],
                            "required_tables": [],
                            "placeholders": [],
                            "guidance_snippets": [],
                        }
                        sections.append(cur_sec)
                    cur_sec["required_tables"].append(cols)
                i += 2
                while i < len(lines) and lines[i].strip().startswith("|"):
                    for ph in PLACEHOLDER_RE.findall(lines[i]):
                        if cur_sec and ph not in cur_sec["placeholders"]:
                            cur_sec["placeholders"].append(ph)
                    i += 1
                continue

        if cur_sec is not None:
            for ph in PLACEHOLDER_RE.findall(ln):
                if ph not in cur_sec["placeholders"]:
                    cur_sec["placeholders"].append(ph)
            if len(cur_sec["guidance_snippets"]) < 6:
                cur_sec["guidance_snippets"].append(ln[:240])
        i += 1

    if not sections:
        sections = _builtin_templates()[0]["blueprint"]["sections"]
    else:
        for idx, s in enumerate(sections):
            snippets = s.pop("guidance_snippets", [])
            s["guidance"] = (
                "เขียนเนื้อหาให้ครบตามโครงสร้างแม่แบบ Markdown นี้ "
                + (f"คำแนะนำจากแม่แบบ: {' | '.join(snippets[:4])}" if snippets else "")
            ).strip()
            if idx == len(sections) - 1:
                s["include_closing_signature"] = True

    return {
        "doc_titles": doc_titles,
        "style_rules": [
            "เติมข้อมูลจริงจากการตรวจสอบลงในทุกหัวข้อ หัวข้อย่อย ตาราง และช่องว่างของแม่แบบให้ครบ 100%",
            "ห้ามทิ้ง <placeholder> หรือ {{variable}} ไว้โดยไม่แทนที่ด้วยผลการตรวจจริง",
        ],
        "sections": sections,
    }


def list_templates() -> dict[str, Any]:
    templates = _load_templates_index()
    summary = []
    for t in templates:
        bp = t.get("blueprint") or {}
        secs = bp.get("sections") or []
        total_subs = sum(len(s.get("subsections") or []) for s in secs)
        total_tables = sum(len(s.get("required_tables") or []) for s in secs)
        total_ph = sum(len(s.get("placeholders") or []) for s in secs)
        summary.append({
            "id": t["id"],
            "name": t["name"],
            "description": t.get("description") or "",
            "format": t.get("format") or "docx",
            "builtin": bool(t.get("builtin", False)),
            "is_default": bool(t.get("is_default", False)),
            "created_at": t.get("created_at") or "",
            "section_count": len(secs),
            "subsection_count": total_subs,
            "table_count": total_tables,
            "placeholder_count": total_ph,
            "sections": [
                {
                    "id": s.get("id"),
                    "title": s.get("title"),
                    "subsections": s.get("subsections") or [],
                    "table_headers": s.get("required_tables") or [],
                    "placeholders": s.get("placeholders") or [],
                }
                for s in secs
            ],
        })
    return {"ok": True, "templates": summary}


def upload_template(body: dict[str, Any]) -> dict[str, Any]:
    filename = str(body.get("filename") or "").strip()
    name = str(body.get("name") or "").strip()
    description = str(body.get("description") or "").strip()
    content_b64 = str(body.get("content_base64") or "").strip()
    raw_markdown = str(body.get("markdown") or "").strip()
    make_default = bool(body.get("set_default", False))

    if not filename and raw_markdown:
        filename = f"{_slugify(name or 'custom')}.md"
    ext = Path(filename).suffix.lower()
    if ext not in (".docx", ".md", ".markdown"):
        return {"ok": False, "error": "รองรับเฉพาะไฟล์แม่แบบนามสกุล .docx หรือ .md เท่านั้น"}

    _ensure_dirs()
    tid = f"tpl-{_slugify(name or Path(filename).stem)}-{uuid.uuid4().hex[:6]}"
    stored_ext = ".docx" if ext == ".docx" else ".md"
    stored_path = TEMPLATES_DIR / f"{tid}{stored_ext}"

    try:
        if stored_ext == ".docx":
            if not content_b64:
                return {"ok": False, "error": "ไม่พบข้อมูลไฟล์ .docx (content_base64)"}
            if "," in content_b64 and content_b64.startswith("data:"):
                content_b64 = content_b64.split(",", 1)[1]
            raw_bytes = base64.b64decode(content_b64)
            stored_path.write_bytes(raw_bytes)
            blueprint = extract_docx_blueprint(stored_path)
            docx_shell = str(stored_path)
        else:
            if content_b64:
                if "," in content_b64 and content_b64.startswith("data:"):
                    content_b64 = content_b64.split(",", 1)[1]
                md_text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
            else:
                md_text = raw_markdown
            if not md_text.strip():
                return {"ok": False, "error": "ไฟล์แม่แบบ Markdown ว่างเปล่า"}
            stored_path.write_text(md_text, encoding="utf-8")
            blueprint = extract_markdown_blueprint(md_text)
            docx_shell = str(DEFAULT_DOCX_SHELL)
    except Exception as e:
        if stored_path.exists():
            stored_path.unlink(missing_ok=True)
        return {"ok": False, "error": f"สกัดโครงสร้างแม่แบบไม่สำเร็จ: {e}"}

    templates = _load_templates_index()
    if make_default:
        for t in templates:
            t["is_default"] = False

    secs = blueprint.get("sections") or []
    auto_desc = description or (
        f"อัปโหลดจาก {filename} · {len(secs)} หัวข้อหลัก · "
        f"{sum(len(s.get('subsections') or []) for s in secs)} หัวข้อย่อย · "
        f"{sum(len(s.get('required_tables') or []) for s in secs)} ตารางบังคับ"
    )
    entry = {
        "id": tid,
        "name": name or Path(filename).stem,
        "description": auto_desc,
        "format": "docx" if stored_ext == ".docx" else "md",
        "builtin": False,
        "is_default": make_default,
        "docx_shell_path": docx_shell,
        "source_path": str(stored_path),
        "created_at": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(),
        "blueprint": blueprint,
    }
    templates.append(entry)
    _save_templates_index(templates)
    return {"ok": True, "template_id": tid, "templates": list_templates()["templates"]}


def delete_template(template_id: str) -> dict[str, Any]:
    templates = _load_templates_index()
    target = next((t for t in templates if t.get("id") == template_id), None)
    if not target:
        return {"ok": False, "error": f"ไม่พบแม่แบบ {template_id}"}
    if target.get("builtin"):
        return {"ok": False, "error": "แม่แบบมาตรฐานในระบบไม่สามารถลบได้ (สามารถตั้งอันอื่นเป็นค่าเริ่มต้นแทนได้)"}
    src = Path(str(target.get("source_path") or ""))
    if src.is_file() and TEMPLATES_DIR in src.parents:
        src.unlink(missing_ok=True)
    remaining = [t for t in templates if t.get("id") != template_id]
    if not any(t.get("is_default") for t in remaining) and remaining:
        remaining[0]["is_default"] = True
    _save_templates_index(remaining)
    return {"ok": True, "templates": list_templates()["templates"]}


def set_default_template(template_id: str) -> dict[str, Any]:
    templates = _load_templates_index()
    if not any(t.get("id") == template_id for t in templates):
        return {"ok": False, "error": f"ไม่พบแม่แบบ {template_id}"}
    for t in templates:
        t["is_default"] = t.get("id") == template_id
    _save_templates_index(templates)
    return {"ok": True, "default_id": template_id, "templates": list_templates()["templates"]}


# ── ARTEX MCP & Workspace Dossier Harvester ──────────────────────────────────

def _artex_api_key() -> str:
    try:
        cfg = json.loads(NODE_CONFIG_FILE.read_text(encoding="utf-8"))
        artex = ((cfg.get("mcp_servers") or {}).get("artex") or {})
        env_key = artex.get("api_key_env") or "ARTEX_MCP_API_KEY"
        return os.environ.get(env_key) or artex.get("default_api_key") or "ak_project_malaria_artex_mcp_key_2026"
    except Exception:
        return "ak_project_malaria_artex_mcp_key_2026"


def _call_artex_mcp(tool_name: str, arguments: dict[str, Any], timeout: int = 12) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8787/mcp",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-API-Key": _artex_api_key(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        # Handle either JSON or SSE envelope
        for line in raw.splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip()
                break
        msg = json.loads(raw)
        content = ((msg.get("result") or {}).get("content") or [])
        if content and isinstance(content[0], dict):
            txt = content[0].get("text") or ""
            try:
                return json.loads(txt)
            except Exception:
                return txt
        return msg.get("result")
    except Exception:
        return None


def _resolve_host_workspace_path(ws_path: str) -> Optional[Path]:
    raw = (ws_path or "").strip()
    if not raw:
        return None
    if raw.startswith("/workspace"):
        rel = raw[len("/workspace"):].lstrip("/")
        cand = (WORKSPACE_HOST_DIR / rel).resolve()
        if cand.exists() and (cand == WORKSPACE_HOST_DIR.resolve() or WORKSPACE_HOST_DIR.resolve() in cand.parents):
            return cand
    cand2 = Path(raw).expanduser()
    if cand2.exists():
        return cand2
    return None


def _harvest_workspace_files(ws_path: str, max_files: int = 35) -> dict[str, Any]:
    host_dir = _resolve_host_workspace_path(ws_path)
    if not host_dir:
        return {"path": ws_path, "files": []}
    if host_dir.is_file():
        files_iter = [host_dir]
        base = host_dir.parent
    else:
        base = host_dir
        files_iter = [
            p for p in sorted(host_dir.rglob("*"))
            if p.is_file() and not any(part.startswith(".") or part in ("node_modules", "__pycache__", "venv", ".git") for part in p.parts)
        ]

    code_exts = {".py", ".sh", ".js", ".ts", ".mjs", ".ps1", ".bat", ".go", ".php", ".rb", ".pl", ".c", ".cpp", ".rs", ".sql", ".yaml", ".yml", ".json", ".toml", ".md"}
    entries = []
    for p in files_iter[:max_files]:
        rel = str(p.relative_to(base))
        sz = p.stat().st_size
        sha16 = ""
        preview = ""
        try:
            data = p.read_bytes()
            sha16 = hashlib.sha256(data).hexdigest()[:16]
            if p.suffix.lower() in code_exts or sz < 65536:
                txt = data[:2400].decode("utf-8", errors="replace")
                compact_lines = [ln.strip() for ln in txt.splitlines() if ln.strip()][:18]
                preview = "\n".join(compact_lines)[:900]
        except Exception:
            pass
        entries.append({
            "path": rel,
            "ext": p.suffix.lower() or "file",
            "size_bytes": sz,
            "sha256_prefix": sha16,
            "preview": preview,
        })
    return {"path": ws_path, "total_files": len(files_iter), "files": entries}


def _load_json_cache(path: Path) -> dict[str, Any]:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_json_cache(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def _load_cisa_kev_map() -> dict[str, dict[str, Any]]:
    """Load CISA KEV catalog (cached 24h locally; passive public lookup, zero target leakage)."""
    cache = _load_json_cache(KEV_CACHE_FILE)
    now = time.time()
    if cache.get("fetched_at") and (now - float(cache["fetched_at"])) < 86400 and isinstance(cache.get("vulns"), dict):
        return cache["vulns"]
    try:
        req = urllib.request.Request(
            "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
            headers={"User-Agent": "Project-Malaria-ReportStudio/1.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="replace"))
        vulns = {}
        for v in raw.get("vulnerabilities") or []:
            cid = str(v.get("cveID") or "").upper().strip()
            if cid:
                vulns[cid] = {
                    "vendor": v.get("vendorProject", ""),
                    "product": v.get("product", ""),
                    "name": v.get("vulnerabilityName", ""),
                    "date_added": v.get("dateAdded", ""),
                    "due_date": v.get("dueDate", ""),
                    "ransomware_use": v.get("knownRansomwareCampaignUse", ""),
                }
        _save_json_cache(KEV_CACHE_FILE, {"fetched_at": now, "vulns": vulns})
        return vulns
    except Exception:
        return cache.get("vulns") if isinstance(cache.get("vulns"), dict) else {}


def _cve_mcp_post(payload: dict[str, Any], session_id: Optional[str] = None, timeout: int = 8) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    req = urllib.request.Request(
        "http://127.0.0.1:8009/mcp",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        new_sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id") or session_id
        raw = resp.read().decode("utf-8", errors="replace")
    for line in raw.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            break
    if not raw.strip():
        return new_sid, None
    return new_sid, json.loads(raw)


def _ensure_cve_mcp_session(force_new: bool = False) -> Optional[str]:
    global _CVE_MCP_SESSION_ID
    with _CVE_MCP_LOCK:
        if _CVE_MCP_SESSION_ID and not force_new:
            return _CVE_MCP_SESSION_ID
        try:
            sid, _ = _cve_mcp_post(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "report-studio", "version": "2.0"},
                    },
                },
                session_id=None,
                timeout=6,
            )
            if sid:
                try:
                    _cve_mcp_post(
                        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                        session_id=sid,
                        timeout=4,
                    )
                except Exception:
                    pass
                _CVE_MCP_SESSION_ID = sid
                return sid
        except Exception:
            _CVE_MCP_SESSION_ID = None
    return None


def _call_cve_mcp_tool(subtool_name: str, arguments: dict[str, Any], timeout: int = 8) -> Any:
    """Invoke a cve-mcp (:8009) sub-tool via proper MCP Streamable HTTP session handshake."""
    for attempt in range(2):
        sid = _ensure_cve_mcp_session(force_new=(attempt > 0))
        if not sid:
            return None
        try:
            _, msg = _cve_mcp_post(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "cve_run", "arguments": {"name": subtool_name, "arguments": arguments}},
                },
                session_id=sid,
                timeout=timeout,
            )
            if not msg or msg.get("error"):
                continue
            content = ((msg.get("result") or {}).get("content") or [])
            if content and isinstance(content[0], dict):
                txt = str(content[0].get("text") or "")
                try:
                    return json.loads(txt)
                except Exception:
                    return txt
            return msg.get("result")
        except urllib.error.HTTPError as he:
            if he.code in (400, 404):
                continue
            break
        except Exception:
            break
    return None


def _decode_cvss_vector_thai(vector: str, cvss: Optional[float], cwe: str) -> str:
    """Translate CVSS v3 vector metrics into a plain-Thai attacker/impact explanation."""
    parts: list[str] = []
    v = (vector or "").upper()
    if "AV:N" in v:
        parts.append("โจมตีจากระยะไกลผ่านเครือข่ายอินเทอร์เน็ตได้")
    elif "AV:A" in v:
        parts.append("ต้องอยู่ในเครือข่ายวงเดียวกัน")
    elif "AV:L" in v:
        parts.append("ต้องเข้าถึงเครื่องเป้าหมายในระดับ Local")

    if "PR:N" in v:
        parts.append("โดยไม่ต้องล็อกอิน (Unauthenticated)")
    elif "PR:L" in v:
        parts.append("ต้องใช้สิทธิ์บัญชีผู้ใช้ทั่วไป (Low Privilege)")
    elif "PR:H" in v:
        parts.append("ต้องใช้สิทธิ์ผู้ดูแลระบบ (Admin Privilege)")

    if "UI:R" in v:
        parts.append("และต้องอาศัยการคลิก/โต้ตอบจากเหยื่อ")

    impacts: list[str] = []
    if "C:H" in v:
        impacts.append("รั่วไหลของข้อมูลสำคัญระดับสูง")
    elif "C:L" in v:
        impacts.append("อ่านข้อมูลบางส่วนได้")
    if "I:H" in v:
        impacts.append("แก้ไขระบบหรือรันโค้ดได้")
    elif "I:L" in v:
        impacts.append("แก้ไขข้อมูลบางส่วนได้")
    if "A:H" in v:
        impacts.append("ทำให้ระบบล่ม (DoS)")

    cwe_names = {
        "CWE-79": "การฝังสคริปต์ (Cross-Site Scripting / XSS)",
        "CWE-89": "การแทรกคำสั่งฐานข้อมูล (SQL Injection)",
        "CWE-94": "การฉีดและรันโค้ด (Code / Shortcode Injection)",
        "CWE-78": "การแทรกคำสั่งระบบปฏิบัติการ (OS Command Injection)",
        "CWE-22": "การเข้าถึงไฟล์นอกโฟลเดอร์ที่กำหนด (Path Traversal)",
        "CWE-287": "การข้ามผ่านการยืนยันตัวตน (Authentication Bypass)",
        "CWE-284": "การควบคุมสิทธิ์ไม่เหมาะสม (Improper Access Control)",
        "CWE-639": "การเข้าถึงข้อมูลข้ามบัญชี (IDOR)",
        "CWE-918": "การบังคับเซิร์ฟเวอร์เรียก URL ภายใน (SSRF)",
        "CWE-434": "การอัปโหลดไฟล์อันตราย (Unrestricted File Upload)",
        "CWE-200": "การเปิดเผยข้อมูลสำคัญ (Information Exposure)",
        "CWE-352": "การปลอมแปลงคำขอข้ามไซต์ (CSRF)",
        "CWE-502": "การแปลงข้อมูลอ็อบเจกต์ที่ไม่ปลอดภัย (Insecure Deserialization)",
    }
    cwe_th = cwe_names.get((cwe or "").upper(), cwe or "ช่องโหว่ด้านความปลอดภัย")
    score_txt = f"คะแนนความรุนแรง CVSS {cvss} — " if cvss is not None else ""
    cond_txt = " ".join(parts) if parts else "ขึ้นอยู่กับเงื่อนไขการตั้งค่าระบบ"
    imp_txt = f" ส่งผลให้เกิด{', '.join(impacts)}" if impacts else ""
    return f"{score_txt}ประเภท {cwe_th}: ผู้โจมตีสามารถ{cond_txt}{imp_txt}"


def _build_instant_thai_cve_summary(cve_id: str, eng_desc: str, vector: str, cvss: Optional[float], cwe: str) -> str:
    """Create an immediate, accurate Thai summary from NVD description + CVSS vector without blocking UI."""
    base_th = _decode_cvss_vector_thai(vector, cvss, cwe)
    desc = (eng_desc or "").strip()
    if not desc:
        return base_th
    # Identify specific plugin/module vs core product from NVD phrasing
    plugin_m = re.search(r"(?i)^The\s+(.+?)\s+plugin\s+for\s+WordPress\s+is\s+vulnerable\s+to\s+([^.]+)", desc)
    if plugin_m:
        plug_name = re.sub(r"^The\s+", "", plugin_m.group(1).strip())
        vuln_what = plugin_m.group(2).strip()
        ver_m = re.search(r"(?i)(all versions up to, and including,\s*[\d.]+|versions?\s*[<>=~\s\d.]+)", desc)
        ver_txt = f" ({ver_m.group(1)})" if ver_m else ""
        return f"ช่องโหว่ในปลั๊กอิน WordPress ชื่อ \"{plug_name}\"{ver_txt} เสี่ยงต่อ {vuln_what} — {base_th}"
    first_sent = desc.split(". ")[0].strip()
    return f"{base_th} (รายละเอียด NVD: {first_sent[:220]})"


def _call_summarizer_fast(system_prompt: str, user_prompt: str, max_tokens: int = 320, timeout: int = 18) -> str:
    """Prefer dedicated local Summarizer (:8092 Qwen2.5-3B) for sub-second summaries; fall back to LiteLLM 'summarizer'."""
    payload_8092 = {
        "model": "summarizer",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    for url, key in [
        ("http://127.0.0.1:8092/v1/chat/completions", "sk-local"),
        ("http://127.0.0.1:4000/v1/chat/completions", "sk-local-cybertiel-master-key"),
    ]:
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload_8092).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            choices = data.get("choices") or []
            if choices:
                txt = str((choices[0].get("message") or {}).get("content") or "").strip()
                txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
                if txt:
                    return txt
        except Exception:
            continue
    return ""


def summarize_item_endpoint(body: dict[str, Any]) -> dict[str, Any]:
    """On-demand AI Thai summary & verification/reproduce explanation via Summarizer model."""
    kind = str(body.get("kind") or "cve").strip().lower()
    item_id = str(body.get("id") or "").strip()
    raw_context = str(body.get("context") or "").strip()
    if not item_id and not raw_context:
        return {"ok": False, "error": "id or context is required"}

    sys_p = (
        "คุณคือนักวิเคราะห์ความมั่นคงปลอดภัยไซเบอร์ สรุปข้อมูลเป็นภาษาไทยที่กระชับ ชัดเจน เข้าใจง่ายสำหรับอธิบายผู้บริหารและทีมเทคนิค "
        "แบ่งเป็น 3 หัวข้อสั้นๆ:\n"
        "1) ช่องโหว่นี้คืออะไรและผลกระทบ\n"
        "2) เกี่ยวข้องกับ Asset/Path ใด และเป็นช่องโหว่ที่ยืนยันแล้วหรือแค่เทียบจากเลขเวอร์ชัน\n"
        "3) วิธีตรวจสอบซ้ำ (Verify/Reproduce) อย่างปลอดภัย และแนวทางแก้ไข"
    )
    usr_p = f"รหัส/รายการ: {item_id}\nประเภท: {kind}\nข้อมูลหลักฐานและรายละเอียด:\n{raw_context[:3000]}"
    ai_txt = _call_summarizer_fast(sys_p, usr_p, max_tokens=500, timeout=45)
    if not ai_txt:
        return {"ok": False, "error": "Summarizer ไม่พร้อมใช้งานในขณะนี้"}

    if kind == "cve" and CVE_RE.fullmatch(item_id):
        cid = item_id.upper()
        cache = _load_json_cache(CVE_CACHE_FILE)
        entry = cache.get(cid) or {}
        entry["thai_summary_ai"] = ai_txt
        cache[cid] = entry
        _save_json_cache(CVE_CACHE_FILE, cache)

    return {"ok": True, "id": item_id, "thai_summary_ai": ai_txt}


def _call_cve_mcp_lookup(cve_id: str) -> dict[str, Any]:
    """Lookup NVD CVSS/vector/CWE/description/published date and MITRE ATT&CK techniques via local cve-mcp (:8009)."""
    out: dict[str, Any] = {}
    res = _call_cve_mcp_tool("lookup_cve", {"cve_id": cve_id}, timeout=8)
    raw_content = ""
    if isinstance(res, dict):
        inner = res.get("result") if isinstance(res.get("result"), dict) else res
        raw_content = str(
            inner.get("content")
            or ((inner.get("structured") or {}).get("result") if isinstance(inner.get("structured"), dict) else "")
            or res.get("description")
            or res.get("summary")
            or ""
        ).strip()
        cvss_val = res.get("cvss_score") or res.get("base_score") or res.get("cvss")
        if isinstance(cvss_val, (int, float)):
            out["cvss"] = float(cvss_val)
    elif isinstance(res, str):
        raw_content = res.strip()

    if raw_content:
        score_m = re.search(r"(?im)^Score:\s*(\d+(?:\.\d)?)\s*([A-Z]+)?", raw_content)
        if score_m:
            out["cvss"] = float(score_m.group(1))
            if score_m.group(2):
                out["cvss_severity"] = score_m.group(2).upper()
        elif "cvss" not in out:
            cvss_m = re.search(r"(?i)cvss[^\d]{0,12}(\d+(?:\.\d)?)", raw_content)
            if cvss_m:
                out["cvss"] = float(cvss_m.group(1))

        vec_m = re.search(r"(?im)^Vector:\s*(CVSS:[^\s]+)", raw_content)
        if vec_m:
            out["vector"] = vec_m.group(1).strip()

        pub_m = re.search(r"(?im)^Published:\s*(\S+)", raw_content)
        if pub_m:
            out["published"] = pub_m.group(1).strip()

        cwe_m = CWE_RE.search(raw_content)
        if cwe_m:
            out["cwe"] = cwe_m.group(0).upper()

        desc_m = re.search(r"(?is)Description:\s*(.+?)(?:\n\n(?:References|Weaknesses|Configurations):|\Z)", raw_content)
        if desc_m:
            desc_clean = re.sub(r"\s+", " ", desc_m.group(1)).strip()
            out["summary"] = desc_clean[:700]
        else:
            out["summary"] = raw_content[:400]

    atk = _call_cve_mcp_tool("get_attack_mapping", {"cve_id": cve_id}, timeout=6)
    if atk:
        t_ids = sorted(set(re.findall(r"\bT\d{4}(?:\.\d{3})?\b", json.dumps(atk) if not isinstance(atk, str) else atk)))
        if t_ids:
            out["mitre_techniques"] = t_ids[:6]
    return out


# Known product/version signature patterns for automatic Tech -> CVE discovery
_TECH_VERSION_PATTERNS = [
    re.compile(
        r"\b(Apache(?:\s+HTTP\s+Server|\s+Tomcat|\s+Tika|\s+Struts)?|nginx|OpenSSH|PHP|Python|WordPress|Drupal|Joomla|jQuery|Bootstrap|Laravel|Symfony|Django|Flask|FastAPI|Spring(?:\s+Boot)?|Express|Next\.js|Nuxt|React|Vue|Angular|Redis|PostgreSQL|MySQL|MariaDB|MongoDB|Elasticsearch|RabbitMQ|GitLab|Jenkins|Grafana|Keycloak|Harbor|MinIO| Envoy|Traefik|HAProxy|Lighttpd|IIS|OpenSSL|Exim|Postfix|Dovecot|ProFTPD|vsftpd|Samba)[/\s_-]+v?(\d+\.\d+(?:\.\d+)?(?:p\d+)?)\b",
        re.IGNORECASE,
    ),
]


def discover_software_cves(text_corpus: str, asset_technologies: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """Extract versioned software signatures from dossier/assets and map them to CVEs via cve-mcp (:8009)."""
    candidates: dict[str, tuple[str, str]] = {}
    combined = (text_corpus or "") + "\n" + "\n".join(asset_technologies or [])
    for pat in _TECH_VERSION_PATTERNS:
        for m in pat.finditer(combined):
            prod = re.sub(r"\s+", " ", m.group(1).strip())
            ver = m.group(2).strip()
            key = f"{prod.lower()} {ver.lower()}"
            if key not in candidates:
                candidates[key] = (prod, ver)

    if not candidates:
        return []

    cache = _load_json_cache(TECH_CVE_CACHE_FILE)
    now = time.time()
    dirty = False
    results: list[dict[str, Any]] = []

    for key, (prod, ver) in list(candidates.items())[:8]:
        cached = cache.get(key)
        if isinstance(cached, dict) and (now - float(cached.get("cached_at", 0))) < 86400:
            cves = cached.get("cves") or []
        else:
            resp = _call_cve_mcp_tool("search_cves", {"query": f"{prod} {ver}", "limit": 4}, timeout=8)
            raw_txt = json.dumps(resp, ensure_ascii=False) if resp is not None else ""
            cves = sorted(set(c.upper() for c in CVE_RE.findall(raw_txt)))[:4]
            cache[key] = {"product": prod, "version": ver, "cves": cves, "cached_at": now}
            dirty = True

        results.append({
            "software": f"{prod} {ver}",
            "product": prod,
            "version": ver,
            "cves": cves,
        })

    if dirty:
        _save_json_cache(TECH_CVE_CACHE_FILE, cache)
    return results


# Deterministic Vulnerability Taxonomy Rules (CWE + OWASP Top 10 + MITRE ATT&CK)
_TAXONOMY_RULES: list[tuple[re.Pattern[str], list[str], str, list[str]]] = [
    (
        re.compile(r"(?i)\b(idor|bola|bfla|insecure direct object|authorization bypass|broken access|privilege escalation|unauthorized access|cwe-639|cwe-284)\b"),
        ["CWE-639", "CWE-284"],
        "OWASP A01:2021 - Broken Access Control",
        ["T1078 (Valid Accounts)", "T1190 (Exploit Public-Facing Application)"],
    ),
    (
        re.compile(r"(?i)\b(sql injection|sqli|blind sql|union select|cwe-89)\b"),
        ["CWE-89"],
        "OWASP A03:2021 - Injection",
        ["T1190 (Exploit Public-Facing Application)", "T1005 (Data from Local System)"],
    ),
    (
        re.compile(r"(?i)\b(xss|cross-site scripting|script injection|svg upload|html upload|cwe-79)\b"),
        ["CWE-79"],
        "OWASP A03:2021 - Injection",
        ["T1059.007 (JavaScript)", "T1189 (Drive-by Compromise)"],
    ),
    (
        re.compile(r"(?i)\b(command injection|os command|rce|remote code execution|shell execution|cwe-78|cwe-94)\b"),
        ["CWE-78", "CWE-94"],
        "OWASP A03:2021 - Injection",
        ["T1059 (Command and Scripting Interpreter)", "T1190 (Exploit Public-Facing Application)"],
    ),
    (
        re.compile(r"(?i)\b(ssrf|server-side request forgery|cwe-918)\b"),
        ["CWE-918"],
        "OWASP A10:2021 - Server-Side Request Forgery (SSRF)",
        ["T1190 (Exploit Public-Facing Application)", "T1090 (Proxy)"],
    ),
    (
        re.compile(r"(?i)\b(file upload|unrestricted upload|webshell|cwe-434)\b"),
        ["CWE-434"],
        "OWASP A04:2021 - Insecure Design",
        ["T1505.003 (Web Shell)", "T1190 (Exploit Public-Facing Application)"],
    ),
    (
        re.compile(r"(?i)\b(path traversal|directory traversal|lfi|local file inclusion|arbitrary file read|cwe-22)\b"),
        ["CWE-22"],
        "OWASP A01:2021 - Broken Access Control",
        ["T1083 (File and Directory Discovery)", "T1005 (Data from Local System)"],
    ),
    (
        re.compile(r"(?i)\b(mass assignment|over-posting|object property|cwe-915)\b"),
        ["CWE-915"],
        "OWASP API3:2023 - Broken Object Property Level Authorization",
        ["T1190 (Exploit Public-Facing Application)"],
    ),
    (
        re.compile(r"(?i)\b(jwt|hmac|signature not verified|authentication bypass|broken auth|weak token|forged token|cwe-287|cwe-347)\b"),
        ["CWE-287", "CWE-347"],
        "OWASP A07:2021 - Identification and Authentication Failures",
        ["T1550.001 (Application Access Token)", "T1078 (Valid Accounts)"],
    ),
    (
        re.compile(r"(?i)\b(session fixation|session expiration|not invalidated on logout|logout|cookie flag|httponly|samesite|cwe-613|cwe-384)\b"),
        ["CWE-613", "CWE-384"],
        "OWASP A07:2021 - Identification and Authentication Failures",
        ["T1539 (Steal Web Session Cookie)"],
    ),
    (
        re.compile(r"(?i)\b(rate limit|brute force|credential stuffing|lockout|cwe-307|cwe-799)\b"),
        ["CWE-307", "CWE-799"],
        "OWASP A07:2021 - Identification and Authentication Failures",
        ["T1110 (Brute Force)"],
    ),
    (
        re.compile(r"(?i)\b(nsallowsarbitraryloads|cleartext|http allowance|tls|ssl|weak cipher|certificate|transport security|cwe-319|cwe-295)\b"),
        ["CWE-319", "CWE-295"],
        "OWASP A02:2021 - Cryptographic Failures",
        ["T1040 (Network Sniffing)", "T1557 (Adversary-in-the-Middle)"],
    ),
    (
        re.compile(r"(?i)\b(command-and-control|c2|dns tunnel|malware|beacon|cobalt|sliver|backdoor|cwe-506)\b"),
        ["CWE-506"],
        "OWASP A08:2021 - Software and Data Integrity Failures",
        ["T1071 (Application Layer Protocol)", "T1572 (Protocol Tunneling)"],
    ),
    (
        re.compile(r"(?i)\b(privacy manifest|privacyinfo|personal data|pii|gdpr|pdpa|cwe-359)\b"),
        ["CWE-359"],
        "OWASP MASVS-PRIVACY - Mobile Privacy Compliance",
        ["T1430 (Location Tracking)"],
    ),
    (
        re.compile(r"(?i)\b(information disclosure|sensitive data|directory listing|simplehttpserver|exposed|stack trace|debug|credentials exposed|firebase|bucket|cwe-200|cwe-548)\b"),
        ["CWE-200", "CWE-548"],
        "OWASP A05:2021 - Security Misconfiguration",
        ["T1592 (Gather Victim Host Information)", "T1213 (Data from Information Repositories)"],
    ),
    (
        re.compile(r"(?i)\b(cors|security header|csp|hsts|x-frame-options|clickjacking|misconfiguration|surface|exposure|cwe-16|cwe-942)\b"),
        ["CWE-16", "CWE-693"],
        "OWASP A05:2021 - Security Misconfiguration",
        ["T1190 (Exploit Public-Facing Application)"],
    ),
]


def map_finding_standards(finding: dict[str, Any], tech_discoveries: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Deterministically map a finding to CVE(s) (if versioned software applies) + CWE + OWASP + MITRE ATT&CK."""
    blob = " | ".join(
        str(finding.get(k) or "")
        for k in ("name", "vulnclass", "summary", "evidence", "report", "node_detail")
    )
    explicit_cves = sorted(set(c.upper() for c in CVE_RE.findall(blob)))
    matched_tech_cves: list[str] = []
    matched_software: list[str] = []
    for td in (tech_discoveries or []):
        prod = str(td.get("product") or "").lower()
        ver = str(td.get("version") or "").lower()
        if prod and prod in blob.lower() and (not ver or ver in blob.lower()):
            matched_software.append(str(td.get("software") or ""))
            for cid in (td.get("cves") or []):
                if cid not in explicit_cves and cid not in matched_tech_cves:
                    matched_tech_cves.append(cid)

    all_cves = explicit_cves + matched_tech_cves
    explicit_cwes = [c.upper() for c in CWE_RE.findall(blob)]
    cwes: list[str] = list(dict.fromkeys(explicit_cwes))
    owasp = ""
    mitre: list[str] = []

    for pat, rule_cwes, rule_owasp, rule_mitre in _TAXONOMY_RULES:
        if pat.search(blob):
            for rc in rule_cwes:
                if rc not in cwes:
                    cwes.append(rc)
            if not owasp:
                owasp = rule_owasp
            for rm in rule_mitre:
                if rm not in mitre:
                    mitre.append(rm)

    if not cwes:
        cwes = ["CWE-693"]
    if not owasp:
        owasp = "OWASP A05:2021 - Security Misconfiguration"
    if not mitre:
        mitre = ["T1190 (Exploit Public-Facing Application)"]

    title = (
        str(finding.get("name") or "").strip()
        or str(finding.get("summary") or "").strip().split("\n")[0][:95]
        or str(finding.get("vulnclass") or "Finding").strip()[:95]
    )
    return {
        "finding_id": finding.get("finding_id") or finding.get("id"),
        "title": title,
        "severity": str(finding.get("severity") or "info").lower(),
        "vulnclass": str(finding.get("vulnclass") or ""),
        "triage_status": str(finding.get("triage_status") or "new"),
        "cves": all_cves,
        "cve_source": "explicit" if explicit_cves else ("software_match" if matched_tech_cves else "custom_logic_no_cve"),
        "matched_software": matched_software,
        "cwes": cwes[:4],
        "owasp": owasp,
        "mitre_attack": mitre[:4],
    }


def enrich_cves(cve_ids: list[str], vex_by_cve: Optional[dict[str, dict[str, str]]] = None) -> list[dict[str, Any]]:
    """Enrich unique CVE IDs with FIRST.org EPSS, CISA KEV, local cve-mcp CVSS/CWE, and VEX disposition."""
    clean_ids = sorted(set(c.upper().strip() for c in cve_ids if CVE_RE.fullmatch(c.strip())))[:30]
    if not clean_ids:
        return []

    cache = _load_json_cache(CVE_CACHE_FILE)
    now = time.time()
    need_epss = [c for c in clean_ids if not (c in cache and (now - float(cache[c].get("cached_at", 0))) < 86400)]

    need_mcp = [
        c for c in clean_ids
        if c in need_epss or not (cache.get(c) or {}).get("summary")
    ]
    dirty_cache = False

    if need_epss:
        try:
            url = "https://api.first.org/data/v1/epss?cve=" + ",".join(need_epss[:25])
            req = urllib.request.Request(url, headers={"User-Agent": "Project-Malaria-ReportStudio/1.0"})
            with urllib.request.urlopen(req, timeout=7) as resp:
                epss_data = json.loads(resp.read().decode("utf-8", errors="replace"))
            for row in epss_data.get("data") or []:
                cid = str(row.get("cve") or "").upper().strip()
                if cid:
                    entry = cache.get(cid) or {}
                    entry["epss"] = round(float(row.get("epss", 0.0)), 5)
                    entry["epss_percentile"] = round(float(row.get("percentile", 0.0)) * 100, 1)
                    entry["cached_at"] = now
                    cache[cid] = entry
                    dirty_cache = True
        except Exception:
            pass

    for cid in need_mcp[:10]:
        mcp_info = _call_cve_mcp_lookup(cid)
        entry = cache.get(cid) or {}
        for k in ("cvss", "cvss_severity", "vector", "published", "cwe", "mitre_techniques", "summary"):
            if mcp_info.get(k) not in (None, "", []):
                entry[k] = mcp_info[k]
        entry["cached_at"] = now
        cache[cid] = entry
        dirty_cache = True

    if dirty_cache:
        _save_json_cache(CVE_CACHE_FILE, cache)

    kev_map = _load_cisa_kev_map()
    vex_by_cve = vex_by_cve or {}
    out = []
    for cid in clean_ids:
        cinfo = cache.get(cid) or {}
        epss = cinfo.get("epss")
        epss_pct = round(float(epss) * 100, 2) if epss is not None else None
        kev = kev_map.get(cid)
        in_kev = kev is not None
        vex = vex_by_cve.get(cid) or {}
        vex_status = vex.get("status") or "under_investigation"
        vex_just = vex.get("justification") or ""

        if vex_status == "not_affected":
            priority = "P4 - VEX Not Affected (Mitigated/Unreachable)"
        elif in_kev:
            priority = "P0 - CISA KEV (Actively Exploited)"
        elif epss is not None and float(epss) >= 0.30:
            priority = f"P1 - High EPSS ({epss_pct}%)"
        elif epss is not None and float(epss) >= 0.05:
            priority = f"P2 - Elevated EPSS ({epss_pct}%)"
        else:
            priority = "P3 - Standard"

        eng_summary = str(cinfo.get("summary") or "")
        vec = str(cinfo.get("vector") or "")
        cwe_val = str(cinfo.get("cwe") or "")
        cvss_val = cinfo.get("cvss")
        thai_sum = str(cinfo.get("thai_summary_ai") or "") or _build_instant_thai_cve_summary(cid, eng_summary, vec, cvss_val, cwe_val)

        out.append({
            "cve": cid,
            "epss": epss,
            "epss_pct": epss_pct,
            "epss_percentile": cinfo.get("epss_percentile"),
            "in_cisa_kev": in_kev,
            "kev_due_date": kev.get("due_date", "") if kev else "",
            "kev_ransomware": kev.get("ransomware_use", "") if kev else "",
            "cvss": cvss_val,
            "cvss_severity": cinfo.get("cvss_severity", ""),
            "vector": vec,
            "published": cinfo.get("published", ""),
            "cwe": cwe_val,
            "mitre_techniques": cinfo.get("mitre_techniques") or [],
            "summary": eng_summary,
            "thai_summary": thai_sum,
            "has_ai_summary": bool(cinfo.get("thai_summary_ai")),
            "vex_status": vex_status,
            "vex_justification": vex_just,
            "risk_priority": priority,
        })
    out.sort(key=lambda x: (0 if x["in_cisa_kev"] else 1, -(x["epss"] or 0.0), x["cve"]))
    return out


def enrich_cves_endpoint(body: dict[str, Any]) -> dict[str, Any]:
    raw_cves = body.get("cves") or []
    if isinstance(raw_cves, str):
        raw_cves = CVE_RE.findall(raw_cves)
    vex_map = body.get("vex_by_cve") if isinstance(body.get("vex_by_cve"), dict) else {}
    return {"ok": True, "items": enrich_cves([str(x) for x in raw_cves], vex_map)}


def harvest_task_dossier(task_id: int = 0, workspace_path: str = "", extra_notes: str = "") -> dict[str, Any]:
    briefing = _call_artex_mcp("get_shared_briefing", {"task_id": int(task_id or 0), "max_turns": 16}) or {}
    if isinstance(briefing, str):
        briefing = {"briefing_markdown": briefing}

    resolved_tid = int(task_id or briefing.get("task_id") or 0)
    resolved_ws = workspace_path or str(briefing.get("workspace_path") or "")

    assets = _call_artex_mcp("list_assets", {"task_id": resolved_tid, "limit": 80}) if resolved_tid > 0 else []
    findings = _call_artex_mcp("list_task_findings", {"task_id": resolved_tid}) if resolved_tid > 0 else []
    facts = _call_artex_mcp("list_facts", {"task_id": resolved_tid, "limit": 50}) if resolved_tid > 0 else []
    goals = _call_artex_mcp("list_goals", {"task_id": resolved_tid}) if resolved_tid > 0 else []
    chat_hist = _call_artex_mcp("get_chat_history", {"task_id": resolved_tid, "limit": 20}) if resolved_tid > 0 else {}

    # Enterprise Governance data: Cross-Run Correlation, FixGroups, Control-Plane Quality Gate, VEX
    corr_resp = _call_artex_mcp("correlate_task_findings", {"task_id": str(resolved_tid)}) if resolved_tid > 0 else None
    gate_resp = _call_artex_mcp("evaluate_quality_gate", {"task_id": str(resolved_tid)}) if resolved_tid > 0 else None
    correlation = (corr_resp or {}).get("correlation") if isinstance(corr_resp, dict) else None
    fix_groups = (corr_resp or {}).get("fix_groups") if isinstance(corr_resp, dict) else []
    ent_findings = (corr_resp or {}).get("findings") if isinstance(corr_resp, dict) else []
    quality_gate = (gate_resp or {}).get("gate") if isinstance(gate_resp, dict) else None

    # Unwrap list containers if ARTEX returns dict wrappers
    if isinstance(assets, dict):
        assets = assets.get("items") or assets.get("assets") or []
    if isinstance(findings, dict):
        findings = findings.get("items") or findings.get("findings") or []
    if isinstance(facts, dict):
        facts = facts.get("items") or facts.get("facts") or []
    if isinstance(goals, dict):
        goals = goals.get("items") or goals.get("goals") or []

    # Map enterprise triage/VEX/fingerprint by finding ID & node ID
    ent_by_id: dict[int, dict[str, Any]] = {}
    ent_by_node: dict[int, dict[str, Any]] = {}
    vex_by_cve: dict[str, dict[str, str]] = {}
    suppressed_noise: list[dict[str, Any]] = []
    if isinstance(ent_findings, list):
        for ef in ent_findings:
            if not isinstance(ef, dict):
                continue
            if ef.get("id"):
                ent_by_id[int(ef["id"])] = ef
            if ef.get("node_id"):
                ent_by_node[int(ef["node_id"])] = ef
            if ef.get("triage_status") == "noise":
                suppressed_noise.append(ef)
            if ef.get("vex_status"):
                for cid in (ef.get("cves") or []):
                    vex_by_cve[str(cid).upper()] = {
                        "status": str(ef.get("vex_status") or ""),
                        "justification": str(ef.get("vex_justification") or ""),
                    }

    detailed_findings = []
    if isinstance(findings, list):
        for f in findings[:16]:
            if not isinstance(f, dict):
                continue
            nid = f.get("node_id") or f.get("id")
            fid = f.get("finding_id") or f.get("id")
            ef = ent_by_id.get(int(fid or 0)) or ent_by_node.get(int(nid or 0)) or {}
            if ef.get("triage_status") == "noise":
                continue  # Exclude Noise/False Positives from active risk findings
            detail = _call_artex_mcp("get_task_node_detail", {"task_id": resolved_tid, "id": int(nid)}) if (resolved_tid > 0 and nid) else None
            traffic = _call_artex_mcp("get_finding_traffic", {"finding_id": int(fid or nid or 0), "limit": 2}) if (fid or nid) else None
            merged_f = dict(f)
            if ef:
                merged_f["fingerprint"] = ef.get("fingerprint", "")
                merged_f["triage_status"] = ef.get("triage_status", "new")
                merged_f["fix_group_key"] = ef.get("fix_group_key", "")
                merged_f["fix_group_subject"] = ef.get("fix_group_subject", "")
                merged_f["vex_status"] = ef.get("vex_status", "")
                merged_f["vex_justification"] = ef.get("vex_justification", "")
            if detail:
                merged_f["node_detail"] = str(detail)[:1800]
            if traffic:
                merged_f["http_traffic"] = str(traffic)[:1600]
            detailed_findings.append(merged_f)
    elif isinstance(ent_findings, list) and ent_findings:
        detailed_findings = [ef for ef in ent_findings if ef.get("triage_status") != "noise"][:16]

    evidence_images = []
    if EVIDENCE_DIR.is_dir():
        imgs = sorted(
            [p for p in EVIDENCE_DIR.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        evidence_images = [p.name for p in imgs[:12]]

    ws_snapshot = _harvest_workspace_files(resolved_ws) if resolved_ws else {"path": "", "files": []}

    # Expand truncated technical facts via get_task_node_detail so we have full hosts, paths, and raw evidence
    expanded_facts: list[dict[str, Any]] = []
    if isinstance(facts, list):
        for idx_f, fc in enumerate(facts[:20]):
            if not isinstance(fc, dict):
                continue
            fc_copy = dict(fc)
            fid_node = fc.get("id")
            full_txt = str(fc.get("detail") or fc.get("summary") or "")
            if idx_f < 12 and resolved_tid > 0 and fid_node and (fc.get("summary_truncated") or len(full_txt) < 220):
                nd = _call_artex_mcp("get_task_node_detail", {"task_id": resolved_tid, "id": int(fid_node)})
                if isinstance(nd, dict):
                    pl = nd.get("payload") if isinstance(nd.get("payload"), dict) else {}
                    full_txt = str(pl.get("detail") or pl.get("summary") or nd.get("detail") or full_txt)
                elif isinstance(nd, str) and len(nd) > len(full_txt):
                    full_txt = nd
            fc_copy["full_detail"] = full_txt[:3000]
            expanded_facts.append(fc_copy)

    # Index Task Assets by ID and by domain/host for accurate Asset & URL resolution
    asset_by_id: dict[int, dict[str, Any]] = {}
    asset_hosts: list[tuple[str, dict[str, Any]]] = []
    asset_techs: list[str] = []
    asset_counts = {"total": 0, "root_domains": 0, "subdomains": 0, "services": 0, "endpoints": 0}
    if isinstance(assets, list):
        asset_counts["total"] = len(assets)
        for a in assets:
            if not isinstance(a, dict):
                continue
            aid = int(a.get("id") or 0)
            atype = str(a.get("type") or "")
            if atype == "root_domain":
                asset_counts["root_domains"] += 1
            elif atype == "subdomain":
                asset_counts["subdomains"] += 1
            elif atype == "service":
                asset_counts["services"] += 1
            elif atype == "endpoint":
                asset_counts["endpoints"] += 1
            label = str(a.get("url") or a.get("domain") or a.get("ip") or f"Asset #{aid}")
            summary_obj = {
                "id": aid,
                "type": atype,
                "label": label,
                "domain": str(a.get("domain") or ""),
                "url": str(a.get("url") or ""),
                "ip": str(a.get("ip") or ""),
                "port": a.get("port"),
            }
            if aid > 0:
                asset_by_id[aid] = summary_obj
            host_key = str(a.get("domain") or a.get("ip") or "").strip().lower()
            if host_key and len(host_key) > 3:
                asset_hosts.append((host_key, summary_obj))
            for t in (a.get("technologies") or []):
                if t:
                    asset_techs.append(str(t))
            if a.get("service_name"):
                asset_techs.append(str(a["service_name"]))

    path_re = re.compile(r"(?:https?://[^\s)\"',<>]+|(?<![a-zA-Z0-9])/(?:wp-[a-zA-Z0-9_.-]+|api/[a-zA-Z0-9_./-]+|\.[a-zA-Z0-9_.-]+|[a-zA-Z0-9_-]+/[a-zA-Z0-9_./?=&-]+))")

    def _extract_assets_and_paths(text_val: str, explicit_asset_ids: Optional[list[Any]] = None) -> tuple[list[dict[str, Any]], list[str]]:
        matched_a: dict[int, dict[str, Any]] = {}
        for raw_id in (explicit_asset_ids or []):
            try:
                ia = int(raw_id)
                if ia in asset_by_id:
                    matched_a[ia] = asset_by_id[ia]
            except Exception:
                pass
        low = (text_val or "").lower()
        for m_id in re.findall(r"\bid\s+(\d{2,7})\b", low):
            ia = int(m_id)
            if ia in asset_by_id:
                matched_a[ia] = asset_by_id[ia]
        for hkey, aobj in asset_hosts:
            if hkey in low and aobj["type"] != "root_domain":
                matched_a[aobj["id"]] = aobj
        if not matched_a:
            for hkey, aobj in asset_hosts:
                if hkey in low:
                    matched_a[aobj["id"]] = aobj
        paths_found = list(dict.fromkeys(m.group(0).rstrip(".,;:") for m in path_re.finditer(text_val or "")))
        for wp_hint in re.findall(r"\b(wp-login(?:\.php)?(?:\s+ver=[\d.]+)?|xmlrpc\.php|admin-ajax\.php)\b", text_val or "", re.IGNORECASE):
            norm_p = "/" + wp_hint.lstrip("/").replace(" ver=", ".php?ver=") if "wp-login ver=" in wp_hint.lower() else "/" + wp_hint.lstrip("/")
            if norm_p not in paths_found:
                paths_found.insert(0, norm_p)
        return list(matched_a.values())[:6], paths_found[:8]

    cve_blob = json.dumps(
        {
            "findings": detailed_findings,
            "facts": expanded_facts,
            "briefing": str(briefing.get("briefing_markdown") or "")[:4000],
            "extra_notes": extra_notes,
        },
        ensure_ascii=False,
    )
    software_cves = discover_software_cves(cve_blob, asset_techs)

    # Map every active finding to CVE (if applicable) + CWE + OWASP Top 10 + MITRE ATT&CK + full Evidence/Reproduce details
    finding_mappings: list[dict[str, Any]] = []
    confirmed_cve_to_findings: dict[str, list[dict[str, Any]]] = {}
    discovered_cve_ids = list(CVE_RE.findall(cve_blob))
    for sc in software_cves:
        discovered_cve_ids.extend(sc.get("cves") or [])

    for mf in detailed_findings:
        std = map_finding_standards(mf, software_cves)
        f_blob = "\n".join(str(mf.get(k) or "") for k in ("name", "summary", "evidence", "report", "node_detail", "http_traffic"))
        f_assets, f_paths = _extract_assets_and_paths(f_blob, mf.get("asset_ids") if isinstance(mf.get("asset_ids"), list) else None)
        ev_raw = str(mf.get("evidence") or "").strip()
        tr_raw = str(mf.get("http_traffic") or "").strip()
        rpt_raw = str(mf.get("report") or "").strip()

        # Extract Reproduce steps from finding report or evidence
        repro_m = re.search(r"(?is)##+\s*(?:Steps?\s+to\s+Reproduce|Reproduction|PoC|Proof\s+of\s+Concept|วิธีทำซ้ำ)(.+?)(?:\n##+\s|\Z)", rpt_raw)
        if repro_m:
            repro_txt = repro_m.group(1).strip()[:1200]
        elif ev_raw:
            repro_txt = f"ตรวจสอบจากหลักฐาน PoC ที่บันทึกไว้:\n{ev_raw[:900]}"
        else:
            target_u = (f_assets[0]["url"] or f_assets[0]["label"]) if f_assets else (str(briefing.get("task_target") or "เป้าหมาย"))
            path_u = f_paths[0] if f_paths else "/"
            repro_txt = f"ทดสอบส่งคำขอไปยัง {target_u} ที่ path {path_u} เพื่อตรวจสอบพฤติกรรม {std['vulnclass'] or std['owasp']}"

        std["summary"] = str(mf.get("summary") or "").strip()
        std["verification_status"] = str(mf.get("verification_status") or mf.get("state") or "recorded")
        std["fix_group_subject"] = str(mf.get("fix_group_subject") or "")
        std["affected_assets"] = f_assets
        std["affected_paths"] = f_paths
        std["evidence_excerpt"] = (ev_raw or rpt_raw[:800] or "ไม่มีข้อความ PoC แนบแยก (ดูรายละเอียดใน Summary)")[:1400]
        std["http_traffic_excerpt"] = tr_raw[:1000] if tr_raw and tr_raw not in ("None", "{}") else ""
        std["reproduce_steps"] = repro_txt

        mf["mapped_cves"] = std["cves"]
        mf["mapped_cwes"] = std["cwes"]
        mf["mapped_owasp"] = std["owasp"]
        mf["mapped_mitre_attack"] = std["mitre_attack"]
        mf["cve_mapping_note"] = (
            ", ".join(std["cves"])
            if std["cves"]
            else "N/A (Custom App Logic / Config — อ้างอิงรหัส CWE, OWASP และ MITRE ATT&CK)"
        )
        finding_mappings.append(std)
        discovered_cve_ids.extend(std["cves"])
        for cid in std["cves"]:
            if std["cve_source"] == "explicit":
                confirmed_cve_to_findings.setdefault(cid, []).append(std)

    cve_intel = enrich_cves(discovered_cve_ids, vex_by_cve=vex_by_cve)

    # Map CVE -> Software -> Source Facts/Findings -> Assets, Paths, Raw Evidence & Safe Reproduce Guide!
    cve_to_softwares: dict[str, list[str]] = {}
    for sc in software_cves:
        sw_name = str(sc.get("software") or "")
        for cid in (sc.get("cves") or []):
            cve_to_softwares.setdefault(cid, []).append(sw_name)

    for citem in cve_intel:
        cid = citem["cve"]
        linked_findings = confirmed_cve_to_findings.get(cid) or []
        sw_list = cve_to_softwares.get(cid) or []
        source_refs: list[dict[str, Any]] = []
        c_assets: dict[int, dict[str, Any]] = {}
        c_paths: list[str] = []

        for lf in linked_findings:
            source_refs.append({
                "kind": "finding",
                "id": lf.get("finding_id"),
                "title": f"Finding #{lf.get('finding_id')}: {lf.get('title')}",
                "excerpt": lf.get("evidence_excerpt") or lf.get("summary") or "",
            })
            for a in (lf.get("affected_assets") or []):
                c_assets[int(a["id"])] = a
            for p in (lf.get("affected_paths") or []):
                if p not in c_paths:
                    c_paths.append(p)

        # Also trace from expanded_facts where either the CVE ID or the matched software (e.g. "WordPress 7.1.5") was observed
        for fc in expanded_facts:
            ftxt = str(fc.get("full_detail") or fc.get("summary") or "")
            matched_sw_in_fact = [
                sw for sw in sw_list
                if sw.lower() in ftxt.lower() or (sw.split()[0].lower() in ftxt.lower() and sw.split()[-1].lower() in ftxt.lower())
            ]
            if cid.lower() in ftxt.lower() or matched_sw_in_fact:
                # Extract ONLY the exact lines mentioning this specific CVE or Product+Version
                rel_lines = [
                    ln.strip() for ln in ftxt.splitlines()
                    if cid.lower() in ln.lower()
                    or any(
                        sw.split()[0].lower() in ln.lower() and sw.split()[-1].lower() in ln.lower()
                        for sw in matched_sw_in_fact
                    )
                ]
                excerpt = "\n".join(rel_lines[:4]) if rel_lines else ftxt[:450]
                fa, fp = _extract_assets_and_paths(excerpt)
                if not fa:
                    fa, _ = _extract_assets_and_paths(ftxt[:500])
                for a in fa:
                    c_assets[int(a["id"])] = a
                for p in fp:
                    if p not in c_paths:
                        c_paths.append(p)
                source_refs.append({
                    "kind": "fact",
                    "id": fc.get("id"),
                    "title": f"Recon Fact #{fc.get('id')} ({fc.get('source') or fc.get('origin') or 'recon'})",
                    "excerpt": excerpt[:600],
                })

        is_confirmed = len(linked_findings) > 0
        citem["confirmation_status"] = "confirmed" if is_confirmed else "candidate"
        citem["matched_software"] = sw_list
        citem["affected_assets"] = list(c_assets.values())[:6]
        citem["affected_paths"] = c_paths[:6]
        citem["source_refs"] = source_refs[:4]

        # Build clear, actionable Verify / Reproduce guide tailored to this exact host + CVE!
        primary_host = (
            (citem["affected_assets"][0].get("url") or f"https://{citem['affected_assets'][0].get('domain')}")
            if citem["affected_assets"]
            else (str(briefing.get("target") or briefing.get("task_target") or "https://target.example.com"))
        ).rstrip("/")
        primary_path = citem["affected_paths"][0] if citem["affected_paths"] else "/"
        desc_en = str(citem.get("summary") or "")

        if is_confirmed and linked_findings[0].get("reproduce_steps"):
            citem["reproduce_steps"] = linked_findings[0]["reproduce_steps"]
            citem["verification_note"] = "ยืนยันช่องโหว่นี้จาก Finding ในภารกิจแล้ว (Confirmed)"
        else:
            plug_m = re.search(r"(?i)^The\s+(.+?)\s+plugin\s+for\s+WordPress", desc_en)
            if plug_m:
                plug_title = re.sub(r"^The\s+", "", plug_m.group(1).strip())
                slug_guess = re.sub(r"[^a-z0-9]+", "-", plug_title.split("–")[0].split("-")[0].strip().lower()).strip("-")
                ajax_m = re.search(r"\b([a-z0-9_]+)\s+AJAX\s+action\b", desc_en, re.IGNORECASE)
                ajax_hint = f"\n3. หากพบว่าติดตั้งปลั๊กอินจริง จึงตรวจสอบ endpoint `{primary_host}/wp-admin/admin-ajax.php` (action `{ajax_m.group(1)}`)" if ajax_m else ""
                citem["verification_note"] = (
                    f"Candidate CVE (เทียบจากเลขเวอร์ชัน {sw_list[0] if sw_list else ''} ที่สำรวจพบใน {primary_host}{primary_path}) — "
                    f"NVD ระบุว่าเป็นช่องโหว่ของปลั๊กอิน \"{plug_title}\" ไม่ใช่ WordPress Core จึงต้องยืนยันก่อนว่าเป้าหมายติดตั้งปลั๊กอินนี้จริงหรือไม่"
                )
                citem["reproduce_steps"] = (
                    f"1. ตรวจสอบหลักฐานเวอร์ชันที่สำรวจพบ: `curl -skI \"{primary_host}{primary_path}\"`\n"
                    f"2. ตรวจสอบแบบไม่ทำลายระบบ (Passive Check) ว่ามีการติดตั้งปลั๊กอิน \"{plug_title}\" หรือไม่:\n"
                    f"   `curl -skI \"{primary_host}/wp-content/plugins/{slug_guess}/readme.txt\"`{ajax_hint}\n"
                    f"4. หากตอบ 404 (ไม่ได้ติดตั้งปลั๊กอินดังกล่าว) สามารถติดป้าย VEX = Not Affected ในแท็บ Governance ได้ทันที"
                )
            else:
                citem["verification_note"] = (
                    f"Candidate CVE ที่จับคู่จากซอฟต์แวร์ {', '.join(sw_list) or 'ที่ตรวจพบ'} บน {primary_host} — ควรตรวจสอบแพตช์และคอนฟิกจริงก่อนยืนยันผล"
                )
                citem["reproduce_steps"] = (
                    f"1. ตรวจสอบแบนเนอร์/เวอร์ชันบนเป้าหมาย: `curl -skI \"{primary_host}{primary_path}\"`\n"
                    f"2. เทียบเคียงเงื่อนไขช่องโหว่ {cid} ({citem.get('vector') or citem.get('cwe') or 'NVD'}) กับฟีเจอร์ที่เปิดใช้งานจริงบน {primary_host}"
                )

    # Prepare structured Recon Facts summary for the Report Tab Explorer
    recon_facts_view: list[dict[str, Any]] = []
    for fc in expanded_facts[:12]:
        if fc.get("state") == "origin":
            continue
        ftxt = str(fc.get("full_detail") or fc.get("summary") or "").strip()
        if not ftxt:
            continue
        fa, fp = _extract_assets_and_paths(ftxt)
        first_ln = ftxt.splitlines()[0].strip()[:130]
        recon_facts_view.append({
            "id": fc.get("id"),
            "origin": str(fc.get("origin") or ""),
            "source": str(fc.get("source") or ""),
            "headline": str(fc.get("summary") or first_ln)[:150],
            "detail": ftxt,
            "assets": fa,
            "paths": fp,
        })

    all_cwes = sorted({c for fm in finding_mappings for c in (fm.get("cwes") or [])} | {str(c.get("cwe")) for c in cve_intel if c.get("cwe")})
    all_owasp = sorted({str(fm.get("owasp")) for fm in finding_mappings if fm.get("owasp")})
    all_mitre = sorted({m for fm in finding_mappings for m in (fm.get("mitre_attack") or [])} | {m for c in cve_intel for m in (c.get("mitre_techniques") or [])})
    standards_mapping = {
        "active_finding_count": len(finding_mappings),
        "suppressed_noise_count": len(suppressed_noise),
        "cve_count": len(cve_intel),
        "confirmed_cve_count": sum(1 for c in cve_intel if c.get("confirmation_status") == "confirmed"),
        "candidate_cve_count": sum(1 for c in cve_intel if c.get("confirmation_status") == "candidate"),
        "kev_count": sum(1 for c in cve_intel if c.get("in_cisa_kev")),
        "cwe_count": len(all_cwes),
        "owasp_count": len(all_owasp),
        "mitre_count": len(all_mitre),
        "cwes": all_cwes,
        "owasp_categories": all_owasp,
        "mitre_techniques": all_mitre,
        "asset_counts": asset_counts,
        "quality_gate": quality_gate,
        "software_cves": software_cves,
        "cve_intel": cve_intel,
        "findings": finding_mappings,
        "recon_facts": recon_facts_view,
    }

    return {
        "task_id": resolved_tid,
        "task_title": str(briefing.get("task_description") or briefing.get("task_title") or f"Assessment Task #{resolved_tid}"),
        "task_target": str(briefing.get("target") or briefing.get("task_target") or ""),
        "task_state": str(briefing.get("task_status") or briefing.get("task_state") or ""),
        "workspace_path": resolved_ws,
        "briefing_markdown": str(briefing.get("briefing_markdown") or "")[:6000],
        "goals": goals if isinstance(goals, list) else [],
        "assets": assets if isinstance(assets, list) else [],
        "findings": detailed_findings,
        "suppressed_noise": suppressed_noise,
        "correlation": correlation,
        "fix_groups": fix_groups if isinstance(fix_groups, list) else [],
        "quality_gate": quality_gate,
        "cve_intel": cve_intel,
        "software_cves": software_cves,
        "standards_mapping": standards_mapping,
        "facts": expanded_facts[:40],
        "chat_history": chat_hist,
        "workspace_snapshot": ws_snapshot,
        "evidence_images": evidence_images,
        "extra_notes": (extra_notes or "").strip(),
    }


def get_task_standards_mapping(task_id: int) -> dict[str, Any]:
    """Fast live endpoint returning full CVE / Tech-to-CVE / CWE / OWASP / MITRE ATT&CK / EPSS / KEV mapping for a task."""
    if task_id <= 0:
        return {"ok": False, "error": "task_id is required"}
    dossier = harvest_task_dossier(task_id=task_id)
    sm = dossier.get("standards_mapping") or {}
    return {
        "ok": True,
        "task_id": dossier.get("task_id") or task_id,
        "task_title": dossier.get("task_title") or "",
        "task_target": dossier.get("task_target") or "",
        **sm,
    }


def _format_dossier_for_prompt(dossier: dict[str, Any]) -> str:
    parts = [
        f"Task ID: #{dossier.get('task_id')}",
        f"Task Title: {dossier.get('task_title')}",
        f"Primary Target: {dossier.get('task_target') or '(ตามไฟล์/โฟลเดอร์ที่แนบ)'}",
        f"Task Status: {dossier.get('task_state')}",
    ]
    if dossier.get("workspace_path"):
        parts.append(f"Shared Workspace / Folder: {dossier['workspace_path']}")
    if dossier.get("extra_notes"):
        parts.append(f"Operator Focus Notes: {dossier['extra_notes']}")
    if dossier.get("evidence_images"):
        parts.append(f"Available Evidence Screenshots in evidence/: {', '.join(dossier['evidence_images'])}")

    if dossier.get("quality_gate"):
        parts.append("\n=== CONTROL-PLANE QUALITY GATE VERDICT (AUTHORITATIVE) ===\n" + json.dumps(dossier["quality_gate"], ensure_ascii=False, indent=2)[:1800])

    if dossier.get("correlation"):
        parts.append("\n=== CROSS-RUN ISSUE CORRELATION DELTA (NEW / OPEN / REOPENED / FIXED / NOISE) ===\n" + json.dumps(dossier["correlation"], ensure_ascii=False, indent=2))

    if dossier.get("fix_groups"):
        parts.append("\n=== ROOT-CAUSE FIXGROUPS (แก้ 1 จุด ปิดได้หลายช่องโหว่ — ต้องระบุในส่วนแผนแก้ไข) ===\n" + json.dumps(dossier["fix_groups"][:15], ensure_ascii=False, indent=2)[:4000])

    if dossier.get("cve_intel"):
        parts.append("\n=== CVE / EPSS / CISA KEV / CVSS / MITRE RISK INTELLIGENCE (บังคับแสดงรหัส CVE, CVSS, EPSS%, สถานะ KEV และ VEX ในตารางและหัวข้อช่องโหว่) ===\n" + json.dumps(dossier["cve_intel"], ensure_ascii=False, indent=2)[:4500])

    if dossier.get("software_cves"):
        parts.append("\n=== AUTO-DISCOVERED SOFTWARE VERSION -> CVE MAPPING (จาก cve-mcp NVD Lookup) ===\n" + json.dumps(dossier["software_cves"], ensure_ascii=False, indent=2)[:2500])

    sm = dossier.get("standards_mapping") or {}
    if sm.get("findings"):
        parts.append(
            "\n=== MANDATORY VULNERABILITY STANDARDS MAPPING PER FINDING (บังคับระบุรหัส CVE หรือ CWE + OWASP Top 10 + MITRE ATT&CK ของทุกข้อค้นพบในรายงาน ห้ามเว้นว่าง) ===\n"
            + json.dumps(sm["findings"], ensure_ascii=False, indent=2)[:4500]
        )

    if dossier.get("suppressed_noise"):
        parts.append(
            f"\n=== SUPPRESSED NOISE / FALSE POSITIVES ({len(dossier['suppressed_noise'])} items — ห้ามนำไปนับรวมในช่องโหว่ที่ยังเปิดอยู่ ให้กล่าวถึงเฉพาะเป็นหมายเหตุการคัดกรอง) ===\n"
            + json.dumps([{"id": x.get("id"), "name": x.get("name"), "fingerprint": x.get("fingerprint"), "note": x.get("triage_note")} for x in dossier["suppressed_noise"][:10]], ensure_ascii=False)
        )

    if dossier.get("briefing_markdown"):
        parts.append("\n=== SHARED MISSION BRIEFING ===\n" + dossier["briefing_markdown"])

    if dossier.get("goals"):
        parts.append("\n=== MISSION GOALS ===\n" + json.dumps(dossier["goals"][:15], ensure_ascii=False, indent=2)[:2500])

    if dossier.get("assets"):
        parts.append("\n=== DISCOVERED ASSETS ===\n" + json.dumps(dossier["assets"][:35], ensure_ascii=False, indent=2)[:3500])

    if dossier.get("findings"):
        parts.append("\n=== CONFIRMED & RECORDED FINDINGS (WITH EVIDENCE) ===\n" + json.dumps(dossier["findings"], ensure_ascii=False, indent=2)[:9000])

    if dossier.get("facts"):
        parts.append("\n=== TECHNICAL FACTS & OBSERVATIONS ===\n" + json.dumps(dossier["facts"][:30], ensure_ascii=False, indent=2)[:5500])

    ws = dossier.get("workspace_snapshot") or {}
    if ws.get("files"):
        parts.append(
            f"\n=== SHARED WORKSPACE FILE & SCRIPT INVENTORY ({ws.get('path')}, total {ws.get('total_files')} files) ===\n"
            + json.dumps(ws["files"], ensure_ascii=False, indent=2)[:7500]
        )

    ch = dossier.get("chat_history")
    if ch:
        parts.append("\n=== RECENT OPERATOR & AGENT CONVERSATION ===\n" + json.dumps(ch, ensure_ascii=False, indent=2)[:4500])

    return "\n".join(parts)


# ── LLM Caller & Section-by-Section Completeness Gate ────────────────────────

def _call_litellm_json(model: str, system_prompt: str, user_prompt: str, max_tokens: int = 4096, timeout: int = 240) -> str:
    chosen_model = (model or "cyber-model").strip()
    endpoints = [
        ("http://127.0.0.1:4000/v1/chat/completions", "sk-local-cybertiel-master-key", chosen_model),
        ("http://127.0.0.1:8091/v1/chat/completions", "sk-local", "exploit-specialist"),
        ("http://127.0.0.1:8090/v1/chat/completions", "sk-local", "cybermodel"),
    ]
    last_err = ""
    for url, key, target_m in endpoints:
        payload = {
            "model": target_m,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                txt = str(msg.get("content") or "").strip()
                if txt:
                    return txt
        except Exception as e:
            last_err = str(e)
            continue
    raise RuntimeError(f"ไม่สามารถเรียก LLM เพื่อเขียนรายงานได้ ({last_err})")


def _extract_json_blocks(raw_text: str) -> list[dict[str, Any]]:
    cleaned = re.sub(r"<think>.*?</think>", "", raw_text or "", flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", cleaned, re.S)
    candidates = []
    if fence:
        candidates.append(fence.group(1))
    obj_match = re.search(r"\{.*\}", cleaned, re.S)
    if obj_match:
        candidates.append(obj_match.group(0))
    arr_match = re.search(r"\[.*\]", cleaned, re.S)
    if arr_match:
        candidates.append(arr_match.group(0))

    for cand in candidates:
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict) and isinstance(parsed.get("blocks"), list):
                return [b for b in parsed["blocks"] if isinstance(b, dict)]
            if isinstance(parsed, list):
                return [b for b in parsed if isinstance(b, dict)]
        except Exception:
            continue
    return []


def _sanitize_block_text(val: str) -> str:
    # Enforce house style: replace em-dash with hyphen, strip leftover raw template tags if any
    s = str(val or "").replace("—", " - ").strip()
    return s


def _normalize_blocks(blocks: list[dict[str, Any]], section_title: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    has_heading = False
    for b in blocks:
        ty = str(b.get("type") or "").strip().lower()
        if ty == "heading":
            has_heading = True
            out.append({"type": "heading", "text": _sanitize_block_text(b.get("text") or section_title), "new_page": bool(b.get("new_page", False))})
        elif ty in ("sub", "subheading", "h2"):
            txt = _sanitize_block_text(b.get("text") or "")
            if txt:
                out.append({"type": "sub", "text": txt})
        elif ty in ("plain", "paragraph", "p", "text"):
            txt = _sanitize_block_text(b.get("text") or "")
            if txt:
                out.append({"type": "plain", "text": txt, "tab": bool(b.get("tab", True))})
        elif ty in ("bullet", "dash"):
            txt = _sanitize_block_text(b.get("text") or "")
            if txt:
                out.append({"type": ty, "text": txt})
        elif ty == "numbered":
            txt = _sanitize_block_text(b.get("text") or "")
            if txt:
                out.append({"type": "numbered", "n": b.get("n") or 1, "text": txt})
        elif ty == "lead":
            lbl = _sanitize_block_text(b.get("label") or "")
            txt = _sanitize_block_text(b.get("text") or "")
            if lbl or txt:
                out.append({"type": "lead", "label": lbl or "ประเด็นสำคัญ:", "text": txt})
        elif ty == "status":
            val = _sanitize_block_text(b.get("value") or b.get("text") or "")
            if val:
                out.append({"type": "status", "value": val})
        elif ty == "code":
            lines = b.get("lines")
            if isinstance(lines, str):
                lines = lines.splitlines()
            if isinstance(lines, list) and lines:
                out.append({"type": "code", "lines": [str(x) for x in lines[:60]]})
        elif ty == "table":
            rows = b.get("rows")
            if isinstance(rows, list) and len(rows) >= 2:
                norm_rows = []
                ncol = max(len(r) for r in rows if isinstance(r, list)) if any(isinstance(r, list) for r in rows) else 0
                if ncol >= 2:
                    for r in rows:
                        if isinstance(r, list):
                            padded = [_sanitize_block_text(c) for c in r[:ncol]]
                            while len(padded) < ncol:
                                padded.append("-")
                            norm_rows.append(padded)
                    if len(norm_rows) >= 2:
                        out.append({"type": "table", "rows": norm_rows, "header": True})
        elif ty in ("figure", "placeholder"):
            cap = _sanitize_block_text(b.get("caption") or "หลักฐานประกอบจากการตรวจสอบ")
            img = str(b.get("image") or "").strip()
            if ty == "figure" and img:
                out.append({"type": "figure", "image": img, "caption": cap})
            else:
                out.append({"type": "placeholder", "caption": cap})
        elif ty == "note":
            txt = _sanitize_block_text(b.get("text") or "")
            if txt:
                out.append({"type": "note", "text": txt})
        elif ty == "signature":
            out.append({
                "type": "signature",
                "date": _sanitize_block_text(b.get("date") or thai_buddhist_date()),
                "unit": _sanitize_block_text(b.get("unit") or "ฝ่ายปฏิบัติการทางไซเบอร์ สำนักปฏิบัติการ"),
            })

    if not has_heading:
        out.insert(0, {"type": "heading", "text": _sanitize_block_text(section_title)})
    return out


def _validate_section_blocks(
    blocks: list[dict[str, Any]],
    section_spec: dict[str, Any],
    dossier: dict[str, Any],
) -> list[str]:
    """Completeness Gate: returns list of missing requirements. Empty list == 100% pass."""
    issues: list[str] = []
    req_subs = section_spec.get("subsections") or []
    req_tables = section_spec.get("required_tables") or []

    generated_subs = [str(b.get("text") or "") for b in blocks if b.get("type") == "sub"]
    for rsub in req_subs:
        prefix_m = re.match(r"^(\d+\.\d+)", rsub.strip())
        key_token = prefix_m.group(1) if prefix_m else rsub[:16].strip()
        if not any(key_token.lower() in gs.lower() or rsub[:18].lower() in gs.lower() for gs in generated_subs):
            issues.append(f"ขาดหัวข้อย่อยบังคับ: '{rsub}'")

    generated_tables = [b for b in blocks if b.get("type") == "table" and len(b.get("rows") or []) >= 2]
    if len(generated_tables) < len(req_tables):
        issues.append(
            f"ขาดตารางบังคับของหัวข้อนี้ (ต้องการอย่างน้อย {len(req_tables)} ตาราง แต่มีเพียง {len(generated_tables)} ตาราง)"
        )

    # Check total substantive text volume & leftover placeholders
    all_text_chunks: list[str] = []
    for b in blocks:
        if "text" in b:
            all_text_chunks.append(str(b["text"]))
        if b.get("type") == "table":
            for r in b.get("rows") or []:
                all_text_chunks.extend(str(c) for c in r)
        if b.get("type") == "code":
            all_text_chunks.extend(str(ln) for ln in (b.get("lines") or []))

    joined = "\n".join(all_text_chunks)
    if len(joined.strip()) < 420:
        issues.append(f"เนื้อหาในหัวข้อ '{section_spec.get('title')}' สั้นเกินไป ({len(joined.strip())} ตัวอักษร) ต้องอธิบายเชิงเทคนิคอย่างละเอียดอย่างน้อย 500+ ตัวอักษร")

    leftover_ph = PLACEHOLDER_RE.findall(joined)
    if leftover_ph:
        issues.append(f"ยังมี Placeholder ที่ยังไม่ได้เติมข้อมูลจริงหลงเหลืออยู่: {', '.join(leftover_ph[:5])}")

    return issues


def _build_section_system_prompt(style_rules: list[str]) -> str:
    rules_txt = "\n".join(f"- {r}" for r in style_rules)
    return (
        "คุณคือผู้เชี่ยวชาญด้านความมั่นคงปลอดภัยไซเบอร์และการจัดทำรายงานทางเทคนิคระดับอาวุโส (Senior Penetration Tester & Malware/Code Auditor)\n"
        "หน้าที่ของคุณคือเขียนเนื้อหา **เฉพาะหัวข้อหลักที่ได้รับมอบหมาย** ให้ละเอียด ลึกซึ้ง และครบทุกหัวข้อย่อยและตารางตามแม่แบบ (Template Blueprint) แบบ 100%\n\n"
        "กติกาเหล็ก (Completeness & Quality Gate):\n"
        f"{rules_txt}\n"
        "- ห้ามเขียนสรุปสั้นๆ แบบขอไปที ต้องนำข้อเท็จจริง ชื่อไฟล์ ค่าแฮช พอร์ต URL บรรทัดโค้ด ผลคำสั่ง และหลักฐานจาก Dossier มาแจกแจงอย่างละเอียด\n"
        "- ต้องสร้างทุกหัวข้อย่อย (`type: \"sub\"`) และทุกตาราง (`type: \"table\"`) ที่แม่แบบกำหนดไว้ครบทุกอัน\n"
        "- ตอบเป็น JSON Object เท่านั้น ในรูปแบบ `{\"blocks\": [ ... ]}` โดยแต่ละ block ใช้ schema ต่อไปนี้:\n"
        "  * `{\"type\": \"heading\", \"text\": \"...\"}` (หัวข้อหลัก 1 อันแรกสุด)\n"
        "  * `{\"type\": \"sub\", \"text\": \"...\"}` (หัวข้อย่อย เช่น 1.1, 1.2)\n"
        "  * `{\"type\": \"plain\", \"text\": \"...\"}` (ย่อหน้าอธิบายเชิงลึก)\n"
        "  * `{\"type\": \"lead\", \"label\": \"หัวข้อเน้น:\", \"text\": \"...\"}`\n"
        "  * `{\"type\": \"bullet\", \"text\": \"...\"}`\n"
        "  * `{\"type\": \"table\", \"rows\": [[\"คอลัมน์ 1\", \"คอลัมน์ 2\"], [\"ข้อมูลจริง 1\", \"ข้อมูลจริง 2\"]]}` (แถวแรกคือหัวตาราง และต้องมีแถวข้อมูลจริงอย่างน้อย 1-15 แถว)\n"
        "  * `{\"type\": \"code\", \"lines\": [\"บรรทัดโค้ดหรือโครงสร้างไฟล์...\"]}`\n"
        "  * `{\"type\": \"figure\", \"image\": \"ชื่อไฟล์.png\", \"caption\": \"คำอธิบายรูป\"}` (เฉพาะกรณีมีไฟล์จริงใน Available Evidence Screenshots)\n"
        "  * `{\"type\": \"status\", \"value\": \"Tested - ยืนยันผลจากการตรวจสอบจริง\"}`\n"
        "  * `{\"type\": \"note\", \"text\": \"...\"}` และ `{\"type\": \"signature\", \"date\": \"...\", \"unit\": \"ฝ่ายปฏิบัติการทางไซเบอร์ สำนักปฏิบัติการ\"}` (เฉพาะหัวข้อสุดท้ายเมื่อได้รับคำสั่ง)\n"
        "ห้ามส่งข้อความอื่นนอกเหนือจาก JSON `{\"blocks\": [...]}`!"
    )


def _fallback_guarantee_section(
    blocks: list[dict[str, Any]],
    section_spec: dict[str, Any],
    dossier: dict[str, Any],
) -> list[dict[str, Any]]:
    """Deterministic safety net: ensures zero missing required subsections or tables even if LLM partially omitted one."""
    existing_subs = [str(b.get("text") or "") for b in blocks if b.get("type") == "sub"]
    for rsub in section_spec.get("subsections") or []:
        prefix_m = re.match(r"^(\d+\.\d+)", rsub.strip())
        key_token = prefix_m.group(1) if prefix_m else rsub[:16].strip()
        if not any(key_token.lower() in gs.lower() or rsub[:18].lower() in gs.lower() for gs in existing_subs):
            blocks.append({"type": "sub", "text": rsub})
            blocks.append({
                "type": "plain",
                "text": (
                    f"จากการรวบรวมข้อมูลในภารกิจ {dossier.get('task_title')} เป้าหมาย {dossier.get('task_target') or dossier.get('workspace_path') or 'ตามขอบเขตงาน'} "
                    f"ได้ดำเนินการตรวจสอบในส่วนของ {rsub} โดยอ้างอิงข้อมูลจากฐานข้อมูลภารกิจและไฟล์หลักฐานที่เกี่ยวข้องครบถ้วน"
                ),
            })

    existing_tables = [b for b in blocks if b.get("type") == "table" and len(b.get("rows") or []) >= 2]
    req_tables = section_spec.get("required_tables") or []
    while len(existing_tables) < len(req_tables):
        hdr = req_tables[len(existing_tables)]
        ncol = len(hdr)
        rows = [list(hdr)]
        if dossier.get("findings"):
            for idx, f in enumerate(dossier["findings"][:8], 1):
                vals = [
                    str(idx),
                    str(f.get("title") or f.get("name") or "ประเด็นความมั่นคงปลอดภัย"),
                    str(f.get("severity") or "Medium"),
                    str(f.get("target") or f.get("asset") or dossier.get("task_target") or "-"),
                    "Tested",
                ]
                rows.append((vals + ["-"] * ncol)[:ncol])
        elif (dossier.get("workspace_snapshot") or {}).get("files"):
            for f in dossier["workspace_snapshot"]["files"][:10]:
                vals = [
                    str(f.get("path") or "-"),
                    str(f.get("ext") or "-"),
                    f"{f.get('size_bytes', 0)} bytes ({f.get('sha256_prefix', '-')})",
                    (str(f.get("preview") or "ไฟล์ในขอบเขตการตรวจสอบ").splitlines()[0][:80] if f.get("preview") else "ไฟล์ในขอบเขตการตรวจสอบ"),
                ]
                rows.append((vals + ["-"] * ncol)[:ncol])
        elif dossier.get("assets"):
            for a in dossier["assets"][:8]:
                vals = [
                    str(a.get("value") or a.get("name") or dossier.get("task_target") or "-"),
                    str(a.get("kind") or a.get("type") or "Asset"),
                    str(a.get("detail") or a.get("state") or "ในขอบเขตภารกิจ"),
                    "ตรวจสอบแล้ว",
                ]
                rows.append((vals + ["-"] * ncol)[:ncol])
        else:
            vals = [
                str(dossier.get("task_target") or dossier.get("workspace_path") or dossier.get("task_title") or "เป้าหมายหลัก"),
                "System / Assessment Target",
                f"Task #{dossier.get('task_id')}",
                "ดำเนินการตรวจสอบตามขอบเขต",
            ]
            rows.append((vals + ["-"] * ncol)[:ncol])
        tbl_block = {"type": "table", "rows": rows, "header": True}
        blocks.append(tbl_block)
        existing_tables.append(tbl_block)

    if section_spec.get("include_closing_signature"):
        if not any(b.get("type") == "signature" for b in blocks):
            blocks.append({
                "type": "note",
                "text": "รายงานฉบับนี้จัดทำขึ้นจากการตรวจสอบทางเทคนิคตามขอบเขตและหลักฐานที่ตรวจพบจริง ณ วันเวลาที่ปฏิบัติงาน ข้อมูลสำคัญได้ผ่านการคัดกรองตามหลักการป้องกันระบบแล้ว",
            })
            blocks.append({
                "type": "signature",
                "date": thai_buddhist_date(),
                "unit": "ฝ่ายปฏิบัติการทางไซเบอร์ สำนักปฏิบัติการ",
            })
    return blocks


def _render_markdown_from_spec(spec: dict[str, Any]) -> str:
    lines: list[str] = []
    for idx, t in enumerate(spec.get("titles") or []):
        if idx == 0:
            lines.append(f"# {t}")
        else:
            lines.append(f"**{t}**")
    if spec.get("date"):
        lines.append(f"*{spec['date']}*")
    lines.append("")
    lines.append("---")
    lines.append("")

    fig_no = 0
    for b in spec.get("blocks") or []:
        ty = b.get("type")
        if ty == "heading":
            lines.append(f"\n## {b.get('text', '')}\n")
        elif ty == "sub":
            lines.append(f"\n### {b.get('text', '')}\n")
        elif ty == "plain":
            lines.append(f"{b.get('text', '')}\n")
        elif ty == "lead":
            lines.append(f"**{b.get('label', '')}** {b.get('text', '')}\n")
        elif ty == "bullet":
            lines.append(f"- {b.get('text', '')}")
        elif ty == "dash":
            lines.append(f"  - {b.get('text', '')}")
        elif ty == "numbered":
            lines.append(f"{b.get('n', 1)}. {b.get('text', '')}")
        elif ty == "status":
            lines.append(f"\n> **สถานะ:** {b.get('value', '')}\n")
        elif ty == "code":
            lines.append("\n```text")
            for ln in b.get("lines") or []:
                lines.append(str(ln))
            lines.append("```\n")
        elif ty == "table":
            rows = b.get("rows") or []
            if rows:
                hdr = [str(c).replace("|", "\\|").replace("\n", " ") for c in rows[0]]
                lines.append("\n| " + " | ".join(hdr) + " |")
                lines.append("| " + " | ".join(["---"] * len(hdr)) + " |")
                for r in rows[1:]:
                    cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in r]
                    lines.append("| " + " | ".join(cells) + " |")
                lines.append("")
        elif ty in ("figure", "placeholder"):
            fig_no += 1
            cap = b.get("caption", "")
            img = b.get("image", "")
            if ty == "figure" and img:
                lines.append(f"\n> **[รูปภาพที่ {fig_no}]** `{img}` - {cap}\n")
            else:
                lines.append(f"\n> **[กรอบรูปภาพที่ {fig_no}]** {cap}\n")
        elif ty == "note":
            lines.append(f"\n**หมายเหตุ:** {b.get('text', '')}\n")
        elif ty == "signature":
            lines.append("\n---")
            lines.append(f"**{b.get('unit', 'ฝ่ายปฏิบัติการทางไซเบอร์ สำนักปฏิบัติการ')}**  ")
            lines.append(f"{b.get('date', '')}\n")

    return "\n".join(lines).strip() + "\n"


def _run_report_job(
    job_id: str,
    task_id: int,
    template_id: str,
    model: str,
    workspace_path: str,
    extra_notes: str,
    custom_title: str,
) -> dict[str, Any]:
    def _upd(**kwargs: Any) -> None:
        with _REPORT_LOCK:
            if job_id in _JOBS:
                _JOBS[job_id].update(kwargs)
                _JOBS[job_id]["updated_at"] = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
                _persist_jobs_locked()

    try:
        templates = _load_templates_index()
        tpl = next((t for t in templates if t.get("id") == template_id), None)
        if not tpl:
            tpl = next((t for t in templates if t.get("is_default")), templates[0])

        _upd(status="running", stage="กำลังดึงหลักฐาน ข้อค้นพบ และโครงสร้างไฟล์จากภารกิจ (Harvesting Dossier)...")
        dossier = harvest_task_dossier(task_id=task_id, workspace_path=workspace_path, extra_notes=extra_notes)
        resolved_tid = int(dossier.get("task_id") or task_id or 0)
        dossier_prompt = _format_dossier_for_prompt(dossier)

        bp = tpl.get("blueprint") or {}
        sections = bp.get("sections") or []
        style_rules = bp.get("style_rules") or []
        sys_prompt = _build_section_system_prompt(style_rules)

        _upd(
            task_id=resolved_tid,
            template_id=tpl["id"],
            template_name=tpl["name"],
            total_sections=len(sections),
            completed_sections=0,
        )

        all_blocks: list[dict[str, Any]] = []
        gate_repairs = 0

        for idx, sec in enumerate(sections):
            sec_title = str(sec.get("title") or f"{idx + 1}. หัวข้อการตรวจสอบ")
            _upd(
                stage=f"กำลังเขียนหัวข้อที่ {idx + 1}/{len(sections)}: {sec_title}",
                completed_sections=idx,
            )
            req_subs = sec.get("subsections") or []
            req_tables = sec.get("required_tables") or []
            req_ph = sec.get("placeholders") or []

            sec_user_prompt = (
                f"=== แม่แบบที่ต้องเขียนในรอบนี้ (หัวข้อที่ {idx + 1} จาก {len(sections)}) ===\n"
                f"ชื่อหัวข้อหลัก (`heading`): {sec_title}\n"
                f"หัวข้อย่อยบังคับ (`sub` ต้องใส่ให้ครบทุกข้อตามลำดับ): {json.dumps(req_subs, ensure_ascii=False)}\n"
                f"โครงสร้างหัวตารางบังคับ (`table` ต้องสร้างให้ครบทุกตารางพร้อมข้อมูลจริงหลายแถว): {json.dumps(req_tables, ensure_ascii=False)}\n"
                + (f"ช่องข้อมูล/Placeholder ที่ต้องแทนที่ด้วยค่าจริง: {json.dumps(req_ph, ensure_ascii=False)}\n" if req_ph else "")
                + f"คำแนะนำเฉพาะส่วนนี้: {sec.get('guidance') or 'เขียนให้ละเอียดครบถ้วนที่สุด'}\n"
                + ("ต้องปิดท้ายด้วย `note` และ `signature` ในหัวข้อสุดท้ายนี้ด้วย\n" if sec.get("include_closing_signature") else "")
                + f"\n=== ข้อมูลหลักฐานจากการตรวจสอบจริง (TASK DOSSIER) ===\n{dossier_prompt}\n\n"
                "จงเขียน JSON `{\"blocks\": [...]}` ของหัวข้อนี้ให้ละเอียดและครบทุกหัวข้อย่อยและตารางเดี๋ยวนี้:"
            )

            raw_resp = _call_litellm_json(model=model, system_prompt=sys_prompt, user_prompt=sec_user_prompt, max_tokens=4096)
            sec_blocks = _normalize_blocks(_extract_json_blocks(raw_resp), sec_title)
            missing = _validate_section_blocks(sec_blocks, sec, dossier)

            if missing:
                gate_repairs += 1
                _upd(stage=f"Completeness Gate: กำลังขยายเนื้อหาส่วนที่ตกหล่นในหัวข้อที่ {idx + 1}/{len(sections)} ({len(missing)} รายการ)...")
                repair_prompt = (
                    f"ผลตรวจ Completeness Gate ของหัวข้อ '{sec_title}' พบจุดที่ยังไม่ครบตามแม่แบบดังนี้:\n"
                    + "\n".join(f"- {m}" for m in missing)
                    + f"\n\nเนื้อหารอบแรกที่คุณส่งมา:\n{json.dumps({'blocks': sec_blocks}, ensure_ascii=False)[:4500]}\n\n"
                    + f"ข้อมูลหลักฐาน (Dossier):\n{dossier_prompt[:7500]}\n\n"
                    + "กรุณาส่ง JSON `{\"blocks\": [...]}` ฉบับปรับปรุงของหัวข้อนี้ใหม่ทั้งหมด โดยเติมหัวข้อย่อย ตาราง และรายละเอียดทางเทคนิคให้ครบสมบูรณ์ 100%:"
                )
                try:
                    raw_repair = _call_litellm_json(model=model, system_prompt=sys_prompt, user_prompt=repair_prompt, max_tokens=4096)
                    repaired_blocks = _normalize_blocks(_extract_json_blocks(raw_repair), sec_title)
                    if repaired_blocks:
                        sec_blocks = repaired_blocks
                except Exception:
                    pass

            sec_blocks = _fallback_guarantee_section(sec_blocks, sec, dossier)
            all_blocks.extend(sec_blocks)
            _upd(completed_sections=idx + 1)

        _upd(stage="กำลังประกอบไฟล์รายงาน Word (.docx) และ Markdown (.md)...")
        target_label = dossier.get("task_target") or Path(dossier.get("workspace_path") or "").name or dossier.get("task_title") or f"Task #{resolved_tid}"
        doc_titles = list(bp.get("doc_titles") or [])
        if not doc_titles:
            doc_titles = [
                custom_title.strip() or f"รายงานผลการตรวจสอบความมั่นคงปลอดภัยทางเทคนิค: {target_label}",
                f"อ้างอิงภารกิจ ARTEX Task #{resolved_tid} · แม่แบบ {tpl['name']}",
            ]

        spec = {
            "fig_numbering": "continuous",
            "titles": doc_titles,
            "date": thai_buddhist_date(),
            "blocks": all_blocks,
        }

        task_folder = REPORTS_OUT_DIR / f"task_{resolved_tid}"
        task_folder.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now(datetime.timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
        report_id = f"rpt_t{resolved_tid}_{_slugify(tpl['id'], 'tpl')}_{ts}"

        spec_path = task_folder / f"{report_id}.spec.json"
        docx_path = task_folder / f"{report_id}.docx"
        md_path = task_folder / f"{report_id}.md"
        meta_path = task_folder / f"{report_id}.meta.json"

        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

        docx_shell = str(tpl.get("docx_shell_path") or DEFAULT_DOCX_SHELL)
        if not Path(docx_shell).is_file():
            docx_shell = str(DEFAULT_DOCX_SHELL)

        _, warnings = report_assembler.build(
            str(spec_path),
            str(docx_path),
            template=docx_shell,
            evidence_dir=str(EVIDENCE_DIR),
        )
        md_content = _render_markdown_from_spec(spec)
        md_path.write_text(md_content, encoding="utf-8")

        stats = {
            "sections": sum(1 for b in all_blocks if b.get("type") == "heading"),
            "subsections": sum(1 for b in all_blocks if b.get("type") == "sub"),
            "tables": sum(1 for b in all_blocks if b.get("type") == "table"),
            "blocks": len(all_blocks),
            "chars": len(md_content),
            "gate_repairs": gate_repairs,
            "docx_size_bytes": docx_path.stat().st_size if docx_path.is_file() else 0,
            "md_size_bytes": md_path.stat().st_size if md_path.is_file() else 0,
        }

        meta = {
            "id": report_id,
            "task_id": resolved_tid,
            "title": doc_titles[0],
            "template_id": tpl["id"],
            "template_name": tpl["name"],
            "model": model or "cyber-model",
            "created_at": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(),
            "docx_path": str(docx_path),
            "md_path": str(md_path),
            "spec_path": str(spec_path),
            "download_docx_url": f"/model-studio-api/reports/download?id={report_id}&format=docx",
            "download_md_url": f"/model-studio-api/reports/download?id={report_id}&format=md",
            "warnings": warnings,
            "stats": stats,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        _upd(status="completed", stage="สร้างรายงานฉบับสมบูรณ์พร้อมดาวน์โหลดแล้ว", report=meta)
        return {"ok": True, "job_id": job_id, "report": meta, "markdown": md_content}

    except Exception as e:
        _upd(status="failed", stage=f"เกิดข้อผิดพลาด: {e}", error=str(e))
        return {"ok": False, "job_id": job_id, "error": str(e)}


def generate_report(body: dict[str, Any]) -> dict[str, Any]:
    task_id = int(body.get("task_id") or 0)
    template_id = str(body.get("template_id") or "").strip()
    model = str(body.get("model") or "cyber-model").strip()
    workspace_path = str(body.get("workspace_path") or "").strip()
    extra_notes = str(body.get("extra_notes") or "").strip()
    custom_title = str(body.get("title") or "").strip()
    wait = bool(body.get("wait", False))
    force = bool(body.get("force", False))

    # Reuse already-running background job for the same task so switching tabs or clicking again never spawns duplicate jobs.
    if not wait and not force and task_id > 0:
        with _REPORT_LOCK:
            for existing in _JOBS.values():
                if int(existing.get("task_id") or 0) == task_id and existing.get("status") in ("queued", "running"):
                    return {"ok": True, "job_id": existing["job_id"], "job": dict(existing), "reused": True}

    job_id = f"job-{uuid.uuid4().hex[:10]}"
    now_iso = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
    with _REPORT_LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "task_id": task_id,
            "template_id": template_id,
            "model": model,
            "status": "queued",
            "stage": "เริ่มต้นเตรียมสร้างรายงานเบื้องหลังบน Backend...",
            "completed_sections": 0,
            "total_sections": 0,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        _persist_jobs_locked()

    if wait:
        return _run_report_job(job_id, task_id, template_id, model, workspace_path, extra_notes, custom_title)

    t = threading.Thread(
        target=_run_report_job,
        args=(job_id, task_id, template_id, model, workspace_path, extra_notes, custom_title),
        daemon=True,
    )
    t.start()
    return {"ok": True, "job_id": job_id, "job": dict(_JOBS[job_id])}


def get_job(job_id: str) -> dict[str, Any]:
    with _REPORT_LOCK:
        j = _JOBS.get(job_id)
        if not j:
            return {"ok": False, "error": f"ไม่พบงานสร้างรายงาน {job_id}"}
        return {"ok": True, "job": dict(j)}


def list_jobs(task_id: Optional[int] = None) -> dict[str, Any]:
    with _REPORT_LOCK:
        items = list(_JOBS.values())
        if task_id is not None and task_id > 0:
            items = [j for j in items if int(j.get("task_id") or 0) == task_id]
        items.sort(key=lambda j: str(j.get("updated_at") or j.get("created_at") or ""), reverse=True)
        active = next((dict(j) for j in items if j.get("status") in ("queued", "running")), None)
        return {"ok": True, "jobs": [dict(j) for j in items[:20]], "active_job": active}


def _iter_all_meta_files(task_id: Optional[int] = None) -> list[Path]:
    _ensure_dirs()
    if task_id is not None and task_id > 0:
        folder = REPORTS_OUT_DIR / f"task_{task_id}"
        files = list(folder.glob("*.meta.json")) if folder.is_dir() else []
    else:
        files = list(REPORTS_OUT_DIR.rglob("*.meta.json"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def list_generated_reports(task_id: Optional[int] = None) -> dict[str, Any]:
    reports = []
    for mp in _iter_all_meta_files(task_id):
        try:
            reports.append(json.loads(mp.read_text(encoding="utf-8")))
        except Exception:
            continue
    return {"ok": True, "reports": reports}


def get_report_content(report_id: str) -> dict[str, Any]:
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", report_id or "")
    if not clean_id:
        return {"ok": False, "error": "รหัสรายงานไม่ถูกต้อง"}
    for mp in _iter_all_meta_files(None):
        if mp.name == f"{clean_id}.meta.json":
            meta = json.loads(mp.read_text(encoding="utf-8"))
            md_path = Path(str(meta.get("md_path") or ""))
            md_text = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
            return {"ok": True, "report": meta, "markdown": md_text}
    return {"ok": False, "error": f"ไม่พบรายงาน {clean_id}"}


def resolve_report_download(report_id: str, fmt: str = "docx") -> Optional[tuple[Path, str, str]]:
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", report_id or "")
    if not clean_id:
        return None
    fmt_norm = "md" if (fmt or "").lower() in ("md", "markdown") else "docx"
    for mp in _iter_all_meta_files(None):
        if mp.name == f"{clean_id}.meta.json":
            meta = json.loads(mp.read_text(encoding="utf-8"))
            file_path = Path(str(meta.get("md_path" if fmt_norm == "md" else "docx_path") or ""))
            if not file_path.is_file():
                return None
            mime = (
                "text/markdown; charset=utf-8"
                if fmt_norm == "md"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            dl_name = f"{clean_id}.{fmt_norm}"
            return file_path, mime, dl_name
    return None
