import frappe, json
def run():
    v = json.loads(frappe.db.get_value("Creative Batch", "CRB-00093", "variants_json"))[0]
    req = (v.get("keyframe_request") or {}).get("run")
    run = frappe.db.get_value("Generation Run", req, ["status","total_tasks","completed_tasks","failed_tasks","error_summary"], as_dict=True) if req else None
    shots = frappe.get_all("Shot", filters={"media_project": "PRJ-02709", "is_removed": 0}, fields=["shot_number","keyframe_status"], order_by="shot_number")
    fails = []
    if req:
        for t in frappe.get_all("Generation Task", filters={"generation_run": req}, fields=["name","shot"]):
            a = frappe.get_all("Generation Attempt", filters={"generation_task": t.name, "status": "Failed"}, fields=["error_details"], order_by="creation desc", limit=1)
            if a: fails.append((t.shot, (a[0].error_details or "")[:160]))
    print(f"FRAMES variant={v['status']} run={req}:{run and run.status} {run and run.completed_tasks}/{run and run.total_tasks} failed={run and run.failed_tasks} | shots=" + ",".join(f"{s.shot_number}:{s.keyframe_status or '-'}" for s in shots) + f" | fails={fails} | err={(v.get('error') or '')[:150]}")
