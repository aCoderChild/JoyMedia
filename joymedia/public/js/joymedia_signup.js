(function () {
	function bindJoyMediaSignup() {
		var form = $("#joymedia-signup-form");
		if (!form.length) return;

		form.off("submit").on("submit", function (event) {
			event.preventDefault();
			var organization = ($("#signup_organization").val() || "").trim();
			if (!organization) {
				login.show_field_error("signup_organization", "Business / Organization is required.");
				return false;
			}

			var args = {
				cmd: "joymedia.registration.register_with_organization",
				email: ($("#signup_email").val() || "").trim(),
				full_name: frappe.utils.xss_sanitise(($(`#signup_fullname`).val() || "").trim()),
				organization_name: organization,
				industry: ($("#signup_industry").val() || "").trim(),
				redirect_to: frappe.utils.sanitise_redirect(frappe.utils.get_url_arg("redirect-to")),
			};

			login.call(args, function (response) {
				var result = response.message || {};
				login.set_status(result.message || "Please check your email for verification.", "blue");
				form.find(".btn-signup").prop("disabled", true);
			});
			return false;
		});
	}

	frappe.ready(function () {
		$(document).on("login_rendered", bindJoyMediaSignup);
		setTimeout(bindJoyMediaSignup, 0);
	});
})();
