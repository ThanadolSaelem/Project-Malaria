# Research and report contract

Search by exact CVE/product/version and by related campaign, exploit, vendor mitigation and affected dependency. Prefer original vendor advisories, original research, CERT publications and authoritative vulnerability records. Treat news as leads and corroboration; follow through to the primary advisory. Verify current technical details against current sources rather than the historical templates.

Maintain evidence records with source ID, URL, title, publisher, publication/update dates, retrieval time, supported claims and limitations. Cite source IDs next to material claims and list the corresponding full URLs in the report. Separate confirmed facts, vendor/researcher reports, the analyst's inference and unknowns. Do not fabricate CVEs, CVSS scores/vectors, affected/fixed versions, active exploitation, IOCs, legal conclusions or test results. Conflicting sources must remain visible until resolved. An absence of evidence is not proof of absence.

Do not turn reading news into a claim that local infrastructure was inspected. A section named ผลการดำเนินการตรวจสอบ must state whether it describes document research, supplied evidence or an actual authorized technical check. Do not run exploit tests merely because an example contains them.

Full-report structure, adapted to evidence and the selected reference:
- Case-specific title and scope; draft status and report date.
- Preface and executive summary appropriate to the actual author and audience.
- Affected products/versions and prerequisites, with primary citations.
- Technical mechanism, observed threat behavior, impact and uncertainty.
- Detailed MITRE ATT&CK and D3FEND analysis following [mitre.md](mitre.md): research additional relevant mappings, explain prerequisites and case-specific rationale, distinguish observed evidence from conditional applicability, and provide investigation or implementation/verification guidance. Verify official IDs and descriptions; do not invent mappings to meet a row quota.
- Inspection/detection guidance and supplied findings, with provenance.
- Immediate mitigations and long-term remediation; distinguish vendor fixes from temporary workarounds.
- Further checks, evidence limitations and references.

For short alerts, keep the source form's investigation summary, objectives, recommendations and references; expand details only where needed. For legal sections, verify applicability and current primary legal text or explicitly mark unresolved. Do not transplant legal text from an unrelated template.

Use Thai technical prose with sufficient depth to explain cause, prerequisites, affected scope, evidence and action. Length must follow evidence, not a fixed page quota. Use real supplied/cited figures or clearly labelled explanatory diagrams. Never manufacture screenshots, logs or experimental results. Screenshots and figures need source/caption provenance.

Formatting review includes margins, sections, Thai fonts, Thai/Latin line breaking, first-line/hanging indents, tab stops, line/paragraph spacing, keep-with-next, widow/orphan control, manual breaks, character scaling/spacing, table split behavior, headers/footers and page numbering. After edits, check cover, TOC and all fields for stale values. Resolve every intentional placeholder before delivery or identify it explicitly as missing information.
