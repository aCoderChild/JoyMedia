(function () {
	if (window.location.pathname !== "/desk") return;
	if (!window.frappe || !frappe.boot || !frappe.boot.user) return;

	window.location.replace("/joymedia/campaigns");
})();
