import frappe, json
def run():
    v = json.loads(frappe.db.get_value("Creative Batch", "CRB-00093", "variants_json"))[0]
    pv = ";".join(f"{r.get('scene')}:{r.get('status')}:{r.get('view','-')}" for r in v.get("pose_views") or [])
    print(f"STATE {v.get('status')} | resume={v.get('resume_stage')} | poses={pv} | err={(v.get('error') or '')[:200]}")
