import frappe


def execute():
	if frappe.db.exists("DocType", "Generation Workflow"):
		return
	if not frappe.db.exists("DocType", "Workflow"):
		return

	q = chr(96)
	old_table = q + "tabWorkflow" + q
	new_table = q + "tabGeneration Workflow" + q
	old_tables = frappe.db.sql("SHOW TABLES LIKE 'tabWorkflow'")
	new_tables = frappe.db.sql("SHOW TABLES LIKE 'tabGeneration Workflow'")
	if old_tables and not new_tables:
		frappe.db.sql(f"RENAME TABLE {old_table} TO {new_table}")

	frappe.db.sql(
		f"""
		UPDATE {q}tabDocType{q}
		SET name = 'Generation Workflow'
		WHERE name = 'Workflow'
		"""
	)
	frappe.db.sql(
		f"""
		UPDATE {q}tabDocField{q}
		SET parent = 'Generation Workflow'
		WHERE parent = 'Workflow'
		"""
	)
	frappe.db.sql(
		f"""
		UPDATE {q}tabCustom Field{q}
		SET dt = 'Generation Workflow'
		WHERE dt = 'Workflow'
		"""
	)
	frappe.db.sql(
		f"""
		UPDATE {q}tabDocField{q}
		SET options = 'Generation Workflow'
		WHERE options = 'Workflow'
		"""
	)
	if frappe.db.table_exists("Workflow Binding"):
		frappe.db.sql(
			f"""
			UPDATE {q}tabWorkflow Binding{q}
			SET parenttype = 'Generation Workflow'
			WHERE parenttype = 'Workflow'
			""",
			auto_commit=True,
		)
	if not frappe.db.sql("SHOW TABLES LIKE 'tabWorkflow'"):
		frappe.db.sql(
			f"""
			CREATE TABLE {q}tabWorkflow{q} (
				name varchar(140) NOT NULL,
				document_type varchar(140),
				is_active tinyint(1) NOT NULL DEFAULT 1,
				creation datetime(6),
				modified datetime(6),
				modified_by varchar(140),
				owner varchar(140),
				docstatus int NOT NULL DEFAULT 0,
				idx int NOT NULL DEFAULT 0,
				PRIMARY KEY (name)
				) ENGINE=InnoDB
				""",
				auto_commit=True,
			)
	frappe.clear_cache()
