frappe.pages["joymedia-campaigns"].on_page_load = (wrapper) => {
	frappe.require("/assets/joymedia/css/joymedia_campaigns.css");

	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Campaigns"),
		single_column: true,
	});

	page.set_primary_action(__("Create Campaign"), () => {
		frappe.set_route("Form", "Media Project", "new-media-project-1");
	});

	wrapper.joymedia_campaigns = new JoyMediaCampaignsPage(page);
};

frappe.pages["joymedia-campaigns"].refresh = (wrapper) => {
	if (wrapper.joymedia_campaigns) wrapper.joymedia_campaigns.refresh();
};

class JoyMediaCampaignsPage {
	constructor(page) {
		this.page = page;
		this.campaigns = [];
		this.status = "All";
		this.render();
		this.refresh();
	}

	render() {
		this.page.main.html(`
			<div class="joymedia-campaigns-page">
				<section class="joymedia-campaigns-content">
					<div class="joymedia-campaigns-heading">
						<div>
							<h1>${__("Your Campaigns")}</h1>
							<p>${__("Create, generate, and review your product videos.")}</p>
						</div>
						<div class="joymedia-campaigns-toolbar">
							<div class="joymedia-status-tabs">
								${["All", "Draft", "Generating", "Review", "Completed"]
									.map((status) => `<button class="joymedia-status-tab ${status === "All" ? "active" : ""}" data-status="${status}">${__(status)}</button>`)
									.join("")}
							</div>
							<input class="joymedia-campaign-search" type="search" placeholder="${__("Search campaigns")}" aria-label="${__("Search campaigns")}">
						</div>
					</div>
					<div class="joymedia-campaign-grid"></div>
				</section>
			</div>
		`);

		this.page.main.on("click", ".joymedia-status-tab", (event) => {
			this.status = event.currentTarget.dataset.status;
			this.page.main.find(".joymedia-status-tab").removeClass("active");
			$(event.currentTarget).addClass("active");
			this.render_cards();
		});
		this.page.main.on("input", ".joymedia-campaign-search", () => this.render_cards());
		this.page.main.on("click", ".joymedia-campaign-card", (event) => {
			frappe.set_route("Form", "Media Project", event.currentTarget.dataset.name);
		});
	}

	refresh() {
		frappe.call({
			method: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_cards",
		}).then((response) => {
			this.campaigns = response.message || [];
			this.render_cards();
		});
	}

	render_cards() {
		const search = (this.page.main.find(".joymedia-campaign-search").val() || "").toLowerCase();
		const campaigns = this.campaigns.filter((campaign) => {
			const matches_status = this.status === "All" || campaign.status === this.status;
			const text = [campaign.project_name, campaign.product_name, campaign.target_audience]
				.filter(Boolean)
				.join(" ")
				.toLowerCase();
			return matches_status && (!search || text.includes(search));
		});

		const grid = this.page.main.find(".joymedia-campaign-grid");
		if (!campaigns.length) {
			grid.html(`<div class="joymedia-empty-state"><h2>${__("No campaigns yet")}</h2><p>${__("Create a campaign to start your next product video.")}</p><button class="btn btn-primary">${__("Create Campaign")}</button></div>`);
			grid.find("button").on("click", () => frappe.set_route("Form", "Media Project", "new-media-project-1"));
			return;
		}

		grid.html(campaigns.map((campaign, index) => this.render_card(campaign, index)).join(""));
	}

	render_card(campaign, index) {
		const gradients = ["blue", "green", "purple", "gold"];
		const duration = campaign.total_duration_seconds ? `${campaign.total_duration_seconds}s` : __("Settings needed");
		const format = campaign.delivery_preset || "";
		return `
			<article class="joymedia-campaign-card" data-name="${frappe.utils.escape_html(campaign.name)}">
				<div class="joymedia-campaign-cover ${gradients[index % gradients.length]}">
					<span class="joymedia-campaign-status">${frappe.utils.escape_html(campaign.status || "Draft")}</span>
					<h2>${frappe.utils.escape_html(campaign.project_name || campaign.name)}</h2>
				</div>
				<div class="joymedia-campaign-card-body">
					<div class="joymedia-campaign-meta"><span>${frappe.utils.escape_html(campaign.product_name || __("No product"))}</span><span>${duration} ${format ? `· ${frappe.utils.escape_html(format)}` : ""}</span></div>
					<p>${frappe.utils.escape_html(campaign.video_idea || __("Add a video idea to define this campaign."))}</p>
					<div class="joymedia-campaign-stats"><span>${campaign.assets_count || 0} ${__("assets")}</span><span>${campaign.shots_count || 0} ${__("scenes")}</span></div>
				</div>
			</article>
		`;
	}
}
