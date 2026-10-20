frappe.ui.form.on('Video Review Feedback', {
  refresh(frm) {
    if (!frm.is_new()) frm.add_custom_button(__('Open video evidence'), () => {
      window.open(`/joymedia/projects/${encodeURIComponent(frm.doc.source_edit)}?review=${encodeURIComponent(frm.doc.asset_version)}&feedback=${encodeURIComponent(frm.doc.name)}`, '_blank', 'noopener');
    });
  },
});
