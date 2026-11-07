"""Production's QC checklist: five steps, three checks each.

The same list the screens carry (`production-ui/src/lib/qc-checklist.ts`);
the server checks a recorded line against it. A test keeps the two equal.
"""

QC_STEPS: tuple[dict, ...] = (
    {"id": "materials", "name": "Materials & approved sample", "checks": (
        "Fabric, colour and GSM match the approved specification",
        "Approved sample and size chart available",
        "Fabric defects and shrinkage checked",
    )},
    {"id": "cutting", "name": "Cutting & measurements", "checks": (
        "Measurements checked against the size chart",
        "Size quantities and cut panels counted",
        "Cutting alignment and seam allowances checked",
    )},
    {"id": "sewing", "name": "Sewing & assembly", "checks": (
        "Stitching, seams and thread tension checked",
        "Fit and symmetry checked across sizes",
        "Print, embroidery and transfer placement checked",
    )},
    {"id": "finishing", "name": "Finishing & labels", "checks": (
        "Loose threads, stains and finishing checked",
        "Brand, size and care labels verified",
        "Wash, colour consistency and final measurements checked",
    )},
    {"id": "delivery", "name": "Final inspection & packing", "checks": (
        "Finished quantities verified by size and colour",
        "Defects and rework recorded and resolved",
        "Packaging, tags and delivery quantities verified",
    )},
)
