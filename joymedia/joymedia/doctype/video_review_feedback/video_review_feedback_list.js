frappe.listview_settings['Video Review Feedback'] = {
  get_indicator(doc) {
    const colors = {Open:'orange', Investigating:'blue', Resolved:'green', Dismissed:'gray'};
    return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
  },
};
