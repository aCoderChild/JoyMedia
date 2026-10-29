import frappe, json
def hold():
    with frappe.cache.lock("joymedia-creative:CRB-00093", timeout=180, blocking_timeout=30):
        frappe.db.commit()
        vs = json.loads(frappe.db.get_value("Creative Batch", "CRB-00093", "variants_json"))
        vs[0].update(status="Rewriting", error="", scene_revision={"pose_scenes": [1], "by": "Retry"})
        frappe.db.set_value("Creative Batch", "CRB-00093", {"variants_json": frappe.as_json(vs), "status": "Planning"})
        frappe.db.commit()
    print("held for scene 1 re-plan")
def run_state():
    print("RUNSTATE", frappe.db.get_value("Generation Run", "RUN-01343", "status"))
def release():
    from joymedia.services.generation.creative_batch import _planning_queue
    frappe.enqueue("joymedia.services.generation.creative_batch.rewrite_scenes_in_place", queue=_planning_queue(), timeout=3600,
                   batch_name="CRB-00093", position=0, job_id="joymedia-creative-rewrite:CRB-00093:0", deduplicate=True, enqueue_after_commit=True)
    frappe.db.commit()
    print("scene 1 re-plan queued")
