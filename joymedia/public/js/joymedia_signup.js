(function () {
	function bindJoyMediaSignup() {
		var form = $("#joymedia-signup-form");
		if (!form.length) return;

		var formElement = form[0];
		if (formElement.__joymediaSignupSubmitHandler) {
			formElement.removeEventListener("submit", formElement.__joymediaSignupSubmitHandler, true);
		}
		var submitHandler = function (event) {
			event.preventDefault();
			event.stopImmediatePropagation();
			var organization = ($("#signup_organization").val() || "").trim();
			if (!organization) {
				login.show_field_error("signup_organization", "Business / Organization is required.");
				return false;
			}
			var password = $("#signup_password").val() || "";
			var passwordConfirm = $("#signup_password_confirm").val() || "";
			if (password.length < 8) {
				login.show_field_error("signup_password", "Password must be at least 8 characters long.");
				return false;
			}
			if (password !== passwordConfirm) {
				login.show_field_error("signup_password_confirm", "Passwords do not match.");
				return false;
			}

			var args = {
				cmd: "joymedia.registration.register_with_organization",
				email: ($("#signup_email").val() || "").trim(),
				full_name: frappe.utils.xss_sanitise(($(`#signup_fullname`).val() || "").trim()),
				organization_name: organization,
				password: password,
				redirect_to: frappe.utils.sanitise_redirect(frappe.utils.get_url_arg("redirect-to")),
			};

			login.set_status("Creating account...", "blue");
			var button = form.find(".btn-signup");
			button.prop("disabled", true);
			var controller = new AbortController();
			var timeout = window.setTimeout(function () {
				controller.abort();
			}, 15000);
			var body = new URLSearchParams({
				email: args.email,
				full_name: args.full_name,
				organization_name: args.organization_name,
				password: args.password,
				redirect_to: args.redirect_to || "",
			});

			window.fetch("/api/method/joymedia.registration.register_with_organization", {
				method: "POST",
				credentials: "same-origin",
				headers: {
					Accept: "application/json",
					"X-Frappe-CSRF-Token": window.csrf_token || "None",
				},
				body: body,
				signal: controller.signal,
			})
			.then(function (response) {
				return response.json().then(function (payload) {
					if (!response.ok || payload.exc) {
						throw new Error(payload._server_messages || payload.exc || "Unable to create the account.");
					}
					return payload.message || {};
				});
			})
			.then(function (result) {
				login.set_status(result.message || "Unable to create the account.", result.status === 0 ? "red" : "blue");
				if (result.redirect_url) {
					window.location.assign(result.redirect_url);
					return;
				}
				button.prop("disabled", result.status === 0);
			}).catch(function (error) {
				var message = error && error.name === "AbortError"
					? "The verification request timed out. Please try again."
					: (error && error.message ? error.message : "Unable to create the account.");
				login.set_invalid(message);
				button.prop("disabled", false);
			}).finally(function () {
				window.clearTimeout(timeout);
			});
			return false;
		};
		formElement.__joymediaSignupSubmitHandler = submitHandler;
		formElement.addEventListener("submit", submitHandler, true);
	}

	frappe.ready(function () {
		$(document).on("login_rendered", bindJoyMediaSignup);
		setTimeout(bindJoyMediaSignup, 0);
	});
})();
