
CREATE TABLE users (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	email TEXT NOT NULL,
	password_hash TEXT NOT NULL,
	display_name TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	account_status TEXT DEFAULT 'active' NOT NULL,
	email_verified_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_users PRIMARY KEY (id),
	CONSTRAINT ck_users_ck_ck_users_email CHECK (length(btrim(email)) > 3),
	CONSTRAINT ck_users_ck_users_7 CHECK (account_status IN ('active','disabled','deleting'))
)

;

CREATE TABLE workspaces (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	owner_user_id UUID NOT NULL,
	name TEXT DEFAULT '我的科研空间' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	status TEXT DEFAULT 'active' NOT NULL,
	CONSTRAINT pk_workspaces PRIMARY KEY (id),
	CONSTRAINT fk_fk_workspace_owner FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE RESTRICT,
	CONSTRAINT ck_workspaces_ck_workspaces_5 CHECK (status IN ('active','deleting')),
	CONSTRAINT uq_workspaces_owner_user_id UNIQUE (owner_user_id)
)

;

CREATE TABLE research_profiles (
	workspace_id UUID NOT NULL,
	degree_stage TEXT,
	field_of_study TEXT,
	reading_preferences JSONB DEFAULT '{}'::jsonb NOT NULL,
	dashboard_preferences JSONB DEFAULT '{}'::jsonb NOT NULL,
	personalization_enabled BOOLEAN DEFAULT true NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	onboarding_state JSONB DEFAULT '{}'::jsonb NOT NULL,
	CONSTRAINT pk_research_profiles PRIMARY KEY (workspace_id),
	CONSTRAINT fk_research_profiles_7 FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
	CONSTRAINT ck_research_profiles_ck_research_profiles_8 CHECK (
        degree_stage IS NULL OR degree_stage IN
        ('master', 'phd', 'other')
    ),
	CONSTRAINT ck_research_profiles_ck_research_profiles_9 CHECK (jsonb_typeof(reading_preferences) = 'object'),
	CONSTRAINT ck_research_profiles_ck_research_profiles_10 CHECK (jsonb_typeof(dashboard_preferences) = 'object'),
	CONSTRAINT ck_research_profiles_ck_research_profiles_11 CHECK (version > 0)
)

;

CREATE TABLE projects (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	title TEXT NOT NULL,
	description TEXT DEFAULT '' NOT NULL,
	research_stage TEXT DEFAULT 'literature_review' NOT NULL,
	status TEXT DEFAULT 'active' NOT NULL,
	is_default BOOLEAN DEFAULT false NOT NULL,
	archived_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_projects PRIMARY KEY (id),
	CONSTRAINT uq_projects_10 UNIQUE (workspace_id, id),
	CONSTRAINT fk_projects_11 FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT,
	CONSTRAINT ck_projects_ck_projects_12 CHECK (length(btrim(title)) > 0),
	CONSTRAINT ck_projects_ck_projects_13 CHECK (research_stage IN (
        'literature_review', 'planning',
        'experimentation', 'writing', 'custom'
    )),
	CONSTRAINT ck_projects_ck_projects_14 CHECK (status IN ('active', 'paused', 'archived')),
	CONSTRAINT ck_projects_ck_projects_15 CHECK (version > 0),
	CONSTRAINT ck_projects_ck_ck_project_archive_time CHECK ((status='archived')=(archived_at IS NOT NULL))
)

;

CREATE TABLE research_threads (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	title TEXT NOT NULL,
	question TEXT NOT NULL,
	description TEXT DEFAULT '' NOT NULL,
	status TEXT DEFAULT 'draft' NOT NULL,
	archived_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	current_revision INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_research_threads PRIMARY KEY (id),
	CONSTRAINT uq_research_threads_10 UNIQUE (workspace_id, project_id, id),
	CONSTRAINT fk_research_threads_11 FOREIGN KEY(workspace_id, project_id) REFERENCES projects (workspace_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_research_threads_ck_research_threads_12 CHECK (length(btrim(title)) > 0),
	CONSTRAINT ck_research_threads_ck_research_threads_13 CHECK (length(btrim(question)) > 0),
	CONSTRAINT ck_research_threads_ck_research_threads_14 CHECK (status IN (
        'draft', 'active', 'paused', 'archived'
    )),
	CONSTRAINT ck_research_threads_ck_research_threads_15 CHECK (version > 0),
	CONSTRAINT ck_research_threads_ck_research_threads_16 CHECK (current_revision > 0),
	CONSTRAINT ck_research_threads_ck_ck_thread_archive_time CHECK ((status='archived')=(archived_at IS NOT NULL))
)

;

CREATE TABLE papers (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	title TEXT DEFAULT '未命名文献' NOT NULL,
	authors JSONB DEFAULT '[]'::jsonb NOT NULL,
	publication_year INTEGER,
	doi TEXT,
	abstract TEXT,
	reading_status TEXT DEFAULT 'unread' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_papers PRIMARY KEY (id),
	CONSTRAINT uq_papers_10 UNIQUE (workspace_id, id),
	CONSTRAINT fk_papers_11 FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT,
	CONSTRAINT ck_papers_ck_papers_12 CHECK (publication_year IS NULL OR
           publication_year BETWEEN 1500 AND 2200),
	CONSTRAINT ck_papers_ck_papers_13 CHECK (jsonb_typeof(authors) = 'array'),
	CONSTRAINT ck_papers_ck_papers_14 CHECK (reading_status IN ('unread', 'reading', 'read')),
	CONSTRAINT ck_papers_ck_papers_15 CHECK (version > 0)
)

;

CREATE TABLE paper_files (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	paper_id UUID NOT NULL,
	version_no INTEGER NOT NULL,
	storage_key TEXT NOT NULL,
	original_filename TEXT NOT NULL,
	mime_type TEXT DEFAULT 'application/pdf' NOT NULL,
	size_bytes BIGINT NOT NULL,
	sha256 TEXT,
	upload_status TEXT DEFAULT 'pending' NOT NULL,
	parse_status TEXT DEFAULT 'pending' NOT NULL,
	is_current BOOLEAN DEFAULT false NOT NULL,
	page_count INTEGER,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	storage_version_id TEXT,
	availability_status TEXT DEFAULT 'available' NOT NULL,
	parser_version TEXT,
	has_text_layer BOOLEAN,
	CONSTRAINT pk_paper_files PRIMARY KEY (id),
	CONSTRAINT uq_paper_files_15 UNIQUE (paper_id, version_no),
	CONSTRAINT uq_paper_files_16 UNIQUE (workspace_id, id),
	CONSTRAINT uq_paper_files_17 UNIQUE (workspace_id, paper_id, id),
	CONSTRAINT fk_paper_files_18 FOREIGN KEY(workspace_id, paper_id) REFERENCES papers (workspace_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_paper_files_ck_paper_files_19 CHECK (version_no >= 1),
	CONSTRAINT ck_paper_files_ck_paper_files_20 CHECK (size_bytes > 0),
	CONSTRAINT ck_paper_files_ck_paper_files_21 CHECK (mime_type = 'application/pdf'),
	CONSTRAINT ck_paper_files_ck_paper_files_22 CHECK (sha256 IS NULL OR
           sha256 ~ '^[0-9a-fA-F]{64}$'),
	CONSTRAINT ck_paper_files_ck_paper_files_23 CHECK (upload_status IN (
        'pending', 'uploaded', 'failed'
    )),
	CONSTRAINT ck_paper_files_ck_paper_files_24 CHECK (parse_status IN (
        'pending', 'queued', 'processing',
        'ready', 'failed'
    )),
	CONSTRAINT ck_paper_files_ck_paper_files_25 CHECK (page_count IS NULL OR page_count > 0),
	CONSTRAINT ck_paper_files_ck_paper_files_26 CHECK (
        NOT is_current OR upload_status = 'uploaded'
    ),
	CONSTRAINT ck_paper_files_ck_paper_files_28 CHECK (availability_status IN ('available','missing','deleting')),
	CONSTRAINT uq_paper_files_storage_key UNIQUE (storage_key)
)

;

CREATE TABLE paper_pages (
	workspace_id UUID NOT NULL,
	paper_id UUID NOT NULL,
	paper_file_id UUID NOT NULL,
	page_number INTEGER NOT NULL,
	text_content TEXT DEFAULT '' NOT NULL,
	layout_data JSONB DEFAULT '{}'::jsonb NOT NULL,
	CONSTRAINT pk_paper_pages_6 PRIMARY KEY (paper_file_id, page_number),
	CONSTRAINT fk_paper_pages_7 FOREIGN KEY(workspace_id, paper_id, paper_file_id) REFERENCES paper_files (workspace_id, paper_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_paper_pages_ck_paper_pages_8 CHECK (page_number >= 1),
	CONSTRAINT ck_paper_pages_ck_paper_pages_9 CHECK (jsonb_typeof(layout_data) = 'object')
)

;

CREATE TABLE project_papers (
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	paper_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_project_papers_4 PRIMARY KEY (workspace_id, project_id, paper_id),
	CONSTRAINT fk_project_papers_5 FOREIGN KEY(workspace_id, project_id) REFERENCES projects (workspace_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_project_papers_6 FOREIGN KEY(workspace_id, paper_id) REFERENCES papers (workspace_id, id) ON DELETE RESTRICT
)

;

CREATE TABLE thread_papers (
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	paper_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_thread_papers_5 PRIMARY KEY (workspace_id, project_id, thread_id, paper_id),
	CONSTRAINT fk_thread_papers_6 FOREIGN KEY(workspace_id, project_id, thread_id) REFERENCES research_threads (workspace_id, project_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_thread_papers_7 FOREIGN KEY(workspace_id, project_id, paper_id) REFERENCES project_papers (workspace_id, project_id, paper_id) ON DELETE RESTRICT
)

;

CREATE TABLE evidence (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	paper_id UUID NOT NULL,
	paper_file_id UUID NOT NULL,
	quote_text TEXT NOT NULL,
	interpretation TEXT DEFAULT '' NOT NULL,
	page_start INTEGER NOT NULL,
	page_end INTEGER NOT NULL,
	source_anchor JSONB DEFAULT '{}'::jsonb NOT NULL,
	anchor_status TEXT DEFAULT 'page_only' NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by UUID NOT NULL,
	tags JSONB DEFAULT '[]'::jsonb NOT NULL,
	CONSTRAINT pk_evidence PRIMARY KEY (id),
	CONSTRAINT uq_evidence_15 UNIQUE (workspace_id, id),
	CONSTRAINT uq_evidence_16 UNIQUE (workspace_id, project_id, thread_id, id),
	CONSTRAINT fk_evidence_17 FOREIGN KEY(workspace_id, project_id, thread_id, paper_id) REFERENCES thread_papers (workspace_id, project_id, thread_id, paper_id) ON DELETE RESTRICT,
	CONSTRAINT fk_evidence_18 FOREIGN KEY(workspace_id, paper_id, paper_file_id) REFERENCES paper_files (workspace_id, paper_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_evidence_ck_evidence_19 CHECK (length(btrim(quote_text)) > 0),
	CONSTRAINT ck_evidence_ck_evidence_20 CHECK (page_start >= 1),
	CONSTRAINT ck_evidence_ck_evidence_21 CHECK (page_end >= page_start),
	CONSTRAINT ck_evidence_ck_evidence_22 CHECK (version >= 1),
	CONSTRAINT ck_evidence_ck_evidence_23 CHECK (jsonb_typeof(source_anchor) = 'object'),
	CONSTRAINT ck_evidence_ck_evidence_24 CHECK (anchor_status IN (
        'located', 'page_only', 'unresolved'
    )),
	CONSTRAINT ck_evidence_ck_evidence_26 CHECK (jsonb_typeof(tags)='array'),
	CONSTRAINT fk_evidence_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT
)

;

CREATE TABLE hypotheses (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	statement TEXT NOT NULL,
	status TEXT DEFAULT 'proposed' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	current_revision INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_hypotheses PRIMARY KEY (id),
	CONSTRAINT uq_hypotheses_8 UNIQUE (workspace_id, project_id, thread_id, id),
	CONSTRAINT fk_hypotheses_9 FOREIGN KEY(workspace_id, project_id, thread_id) REFERENCES research_threads (workspace_id, project_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_hypotheses_ck_hypotheses_10 CHECK (length(btrim(statement)) > 0),
	CONSTRAINT ck_hypotheses_ck_hypotheses_11 CHECK (status IN (
        'proposed', 'testing', 'supported',
        'contradicted', 'inconclusive'
    )),
	CONSTRAINT ck_hypotheses_ck_hypotheses_12 CHECK (version > 0),
	CONSTRAINT ck_hypotheses_ck_hypotheses_13 CHECK (current_revision > 0)
)

;

CREATE TABLE hypothesis_evidence_links (
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	hypothesis_id UUID NOT NULL,
	evidence_id UUID NOT NULL,
	relation TEXT NOT NULL,
	explanation TEXT DEFAULT '' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_hypothesis_evidence_links_8 PRIMARY KEY (workspace_id, hypothesis_id, evidence_id),
	CONSTRAINT fk_hypothesis_evidence_links_9 FOREIGN KEY(workspace_id, project_id, thread_id, hypothesis_id) REFERENCES hypotheses (workspace_id, project_id, thread_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_hypothesis_evidence_links_10 FOREIGN KEY(workspace_id, project_id, thread_id, evidence_id) REFERENCES evidence (workspace_id, project_id, thread_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_hypothesis_evidence_links_ck_hypothesis_evidence_links_11 CHECK (relation IN (
        'support', 'challenge', 'background', 'uncertain'
    )),
	CONSTRAINT ck_hypothesis_evidence_links_ck_hypothesis_evidence_links_12 CHECK (version > 0)
)

;

CREATE TABLE research_decisions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	title TEXT NOT NULL,
	decision_type TEXT NOT NULL,
	current_revision INTEGER DEFAULT 1 NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_research_decisions PRIMARY KEY (id),
	CONSTRAINT uq_research_decisions_9 UNIQUE (workspace_id, project_id, thread_id, id),
	CONSTRAINT fk_research_decisions_10 FOREIGN KEY(workspace_id, project_id, thread_id) REFERENCES research_threads (workspace_id, project_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_research_decisions_ck_research_decisions_11 CHECK (length(btrim(title)) > 0),
	CONSTRAINT ck_research_decisions_ck_research_decisions_12 CHECK (decision_type IN (
        'adopt', 'abandon', 'adjust', 'defer'
    )),
	CONSTRAINT ck_research_decisions_ck_research_decisions_13 CHECK (current_revision >= 1)
)

;

CREATE TABLE decision_revisions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	decision_id UUID NOT NULL,
	revision_no INTEGER NOT NULL,
	reason TEXT NOT NULL,
	content TEXT DEFAULT '' NOT NULL,
	created_by UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	title_snapshot TEXT NOT NULL,
	decision_type_snapshot TEXT NOT NULL,
	CONSTRAINT pk_decision_revisions PRIMARY KEY (id),
	CONSTRAINT uq_decision_revisions_10 UNIQUE (decision_id, revision_no),
	CONSTRAINT uq_decision_revisions_11 UNIQUE (workspace_id, project_id, thread_id, id),
	CONSTRAINT fk_decision_revisions_12 FOREIGN KEY(workspace_id, project_id, thread_id, decision_id) REFERENCES research_decisions (workspace_id, project_id, thread_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_decision_revisions_13 FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT,
	CONSTRAINT ck_decision_revisions_ck_decision_revisions_14 CHECK (revision_no >= 1),
	CONSTRAINT ck_decision_revisions_ck_decision_revisions_15 CHECK (length(btrim(reason)) > 0),
	CONSTRAINT ck_decision_revisions_ck_decision_revisions_16 CHECK (length(btrim(title_snapshot)) > 0),
	CONSTRAINT ck_decision_revisions_ck_decision_revisions_17 CHECK (decision_type_snapshot IN ('adopt','abandon','adjust','defer')),
	CONSTRAINT uq_uq_decision_revision_pointer UNIQUE (workspace_id, project_id, thread_id, decision_id, revision_no)
)

;

CREATE TABLE decision_revision_evidence_links (
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	decision_revision_id UUID NOT NULL,
	evidence_id UUID NOT NULL,
	quote_snapshot TEXT NOT NULL,
	interpretation_snapshot TEXT DEFAULT '' NOT NULL,
	evidence_version INTEGER NOT NULL,
	paper_file_id UUID NOT NULL,
	page_start INTEGER NOT NULL,
	page_end INTEGER NOT NULL,
	source_anchor_snapshot JSONB NOT NULL,
	CONSTRAINT pk_decision_revision_evidence_links_7 PRIMARY KEY (workspace_id, decision_revision_id, evidence_id),
	CONSTRAINT fk_decision_revision_evidence_links_8 FOREIGN KEY(workspace_id, project_id, thread_id, decision_revision_id) REFERENCES decision_revisions (workspace_id, project_id, thread_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_decision_revision_evidence_links_9 FOREIGN KEY(workspace_id, project_id, thread_id, evidence_id) REFERENCES evidence (workspace_id, project_id, thread_id, id) ON DELETE RESTRICT
)

;

CREATE TABLE tasks (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID,
	decision_id UUID,
	title TEXT NOT NULL,
	description TEXT DEFAULT '' NOT NULL,
	status TEXT DEFAULT 'todo' NOT NULL,
	priority TEXT DEFAULT 'medium' NOT NULL,
	due_date DATE,
	completed_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	source_revision_no INTEGER,
	CONSTRAINT pk_tasks PRIMARY KEY (id),
	CONSTRAINT uq_tasks_13 UNIQUE (workspace_id, id),
	CONSTRAINT fk_tasks_14 FOREIGN KEY(workspace_id, project_id) REFERENCES projects (workspace_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_tasks_15 FOREIGN KEY(workspace_id, project_id, thread_id) REFERENCES research_threads (workspace_id, project_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_tasks_16 FOREIGN KEY(workspace_id, project_id, thread_id, decision_id) REFERENCES research_decisions (workspace_id, project_id, thread_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_tasks_ck_tasks_17 CHECK (length(btrim(title)) > 0),
	CONSTRAINT ck_tasks_ck_tasks_18 CHECK (status IN (
        'todo', 'doing', 'done', 'blocked'
    )),
	CONSTRAINT ck_tasks_ck_tasks_19 CHECK (priority IN ('low', 'medium', 'high')),
	CONSTRAINT ck_tasks_ck_tasks_20 CHECK (
        decision_id IS NULL OR thread_id IS NOT NULL
    ),
	CONSTRAINT ck_tasks_ck_tasks_21 CHECK (
        (status = 'done') = (completed_at IS NOT NULL)
    ),
	CONSTRAINT ck_tasks_ck_tasks_22 CHECK (version > 0),
	CONSTRAINT ck_tasks_ck_ck_task_source_revision CHECK ((decision_id IS NULL) = (source_revision_no IS NULL)),
	CONSTRAINT fk_fk_task_source_revision FOREIGN KEY(workspace_id, project_id, thread_id, decision_id, source_revision_no) REFERENCES decision_revisions (workspace_id, project_id, thread_id, decision_id, revision_no) ON DELETE RESTRICT
)

;

CREATE TABLE notes (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	title TEXT NOT NULL,
	content JSONB DEFAULT '{"type":"doc","content":[]}'::jsonb NOT NULL,
	search_text TEXT DEFAULT '' NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	last_saved_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_notes PRIMARY KEY (id),
	CONSTRAINT uq_notes_9 UNIQUE (workspace_id, id),
	CONSTRAINT fk_notes_10 FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT,
	CONSTRAINT ck_notes_ck_notes_11 CHECK (length(btrim(title)) > 0),
	CONSTRAINT ck_notes_ck_notes_12 CHECK (version >= 1),
	CONSTRAINT ck_notes_ck_notes_13 CHECK (jsonb_typeof(content) = 'object')
)

;

CREATE TABLE project_notes (
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	note_id UUID NOT NULL,
	CONSTRAINT pk_project_notes_3 PRIMARY KEY (workspace_id, project_id, note_id),
	CONSTRAINT fk_project_notes_4 FOREIGN KEY(workspace_id, project_id) REFERENCES projects (workspace_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_project_notes_5 FOREIGN KEY(workspace_id, note_id) REFERENCES notes (workspace_id, id) ON DELETE RESTRICT
)

;

CREATE TABLE thread_notes (
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	note_id UUID NOT NULL,
	CONSTRAINT pk_thread_notes_4 PRIMARY KEY (workspace_id, project_id, thread_id, note_id),
	CONSTRAINT fk_thread_notes_5 FOREIGN KEY(workspace_id, project_id, thread_id) REFERENCES research_threads (workspace_id, project_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_thread_notes_6 FOREIGN KEY(workspace_id, project_id, note_id) REFERENCES project_notes (workspace_id, project_id, note_id) ON DELETE RESTRICT
)

;

CREATE TABLE note_papers (
	workspace_id UUID NOT NULL,
	note_id UUID NOT NULL,
	paper_id UUID NOT NULL,
	CONSTRAINT pk_note_papers_3 PRIMARY KEY (workspace_id, note_id, paper_id),
	CONSTRAINT fk_note_papers_4 FOREIGN KEY(workspace_id, note_id) REFERENCES notes (workspace_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_note_papers_5 FOREIGN KEY(workspace_id, paper_id) REFERENCES papers (workspace_id, id) ON DELETE RESTRICT
)

;

CREATE TABLE note_evidence_links (
	workspace_id UUID NOT NULL,
	note_id UUID NOT NULL,
	evidence_id UUID NOT NULL,
	CONSTRAINT pk_note_evidence_links_3 PRIMARY KEY (workspace_id, note_id, evidence_id),
	CONSTRAINT fk_note_evidence_links_4 FOREIGN KEY(workspace_id, note_id) REFERENCES notes (workspace_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_note_evidence_links_5 FOREIGN KEY(workspace_id, evidence_id) REFERENCES evidence (workspace_id, id) ON DELETE RESTRICT
)

;

CREATE TABLE activity_events (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	project_id UUID,
	thread_id UUID,
	actor_user_id UUID NOT NULL,
	event_type TEXT NOT NULL,
	target_type TEXT NOT NULL,
	target_id UUID NOT NULL,
	event_payload JSONB DEFAULT '{}'::jsonb NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	event_schema_version INTEGER DEFAULT 1 NOT NULL,
	CONSTRAINT pk_activity_events PRIMARY KEY (id),
	CONSTRAINT fk_activity_events_10 FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT,
	CONSTRAINT fk_activity_events_11 FOREIGN KEY(workspace_id, project_id) REFERENCES projects (workspace_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_activity_events_12 FOREIGN KEY(workspace_id, project_id, thread_id) REFERENCES research_threads (workspace_id, project_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_activity_events_13 FOREIGN KEY(actor_user_id) REFERENCES users (id) ON DELETE RESTRICT,
	CONSTRAINT ck_activity_events_ck_activity_events_14 CHECK (length(btrim(event_type)) > 0),
	CONSTRAINT ck_activity_events_ck_activity_events_15 CHECK (length(btrim(target_type)) > 0),
	CONSTRAINT ck_activity_events_ck_activity_events_16 CHECK (
        thread_id IS NULL OR project_id IS NOT NULL
    ),
	CONSTRAINT ck_activity_events_ck_activity_events_17 CHECK (jsonb_typeof(event_payload) = 'object')
)

;

CREATE TABLE processing_jobs (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	paper_file_id UUID NOT NULL,
	job_type TEXT DEFAULT 'parse_pdf' NOT NULL,
	status TEXT DEFAULT 'queued' NOT NULL,
	attempts INTEGER DEFAULT 0 NOT NULL,
	max_attempts INTEGER DEFAULT 3 NOT NULL,
	error_code TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	lease_owner TEXT,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	attempt_token UUID,
	heartbeat_at TIMESTAMP WITH TIME ZONE,
	parser_version TEXT,
	next_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_processing_jobs PRIMARY KEY (id),
	CONSTRAINT fk_processing_jobs_11 FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT,
	CONSTRAINT fk_processing_jobs_12 FOREIGN KEY(workspace_id, paper_file_id) REFERENCES paper_files (workspace_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_processing_jobs_ck_processing_jobs_13 CHECK (job_type = 'parse_pdf'),
	CONSTRAINT ck_processing_jobs_ck_processing_jobs_14 CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed'
    )),
	CONSTRAINT ck_processing_jobs_ck_processing_jobs_15 CHECK (attempts >= 0),
	CONSTRAINT ck_processing_jobs_ck_processing_jobs_16 CHECK (max_attempts >= 1)
)

;

CREATE TABLE export_jobs (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	requested_by UUID NOT NULL,
	status TEXT DEFAULT 'queued' NOT NULL,
	include_files BOOLEAN DEFAULT true NOT NULL,
	storage_key TEXT,
	error_code TEXT,
	expires_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	finished_at TIMESTAMP WITH TIME ZONE,
	snapshot_at TIMESTAMP WITH TIME ZONE,
	schema_version INTEGER DEFAULT 1 NOT NULL,
	lease_owner TEXT,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	attempt_token UUID,
	heartbeat_at TIMESTAMP WITH TIME ZONE,
	attempts INTEGER DEFAULT 0 NOT NULL,
	max_attempts INTEGER DEFAULT 3 NOT NULL,
	next_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	manifest_hash TEXT,
	progress INTEGER DEFAULT 0 NOT NULL,
	CONSTRAINT pk_export_jobs PRIMARY KEY (id),
	CONSTRAINT fk_export_jobs_10 FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT,
	CONSTRAINT fk_export_jobs_11 FOREIGN KEY(requested_by) REFERENCES users (id) ON DELETE RESTRICT,
	CONSTRAINT ck_export_jobs_ck_export_jobs_12 CHECK (status IN (
        'queued', 'running', 'succeeded',
        'failed', 'expired'
    )),
	CONSTRAINT uq_export_jobs_storage_key UNIQUE (storage_key)
)

;


CREATE TABLE auth_sessions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	user_id UUID NOT NULL,
	token_hash TEXT NOT NULL,
	csrf_hash TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_auth_sessions PRIMARY KEY (id),
	CONSTRAINT fk_auth_sessions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT,
	CONSTRAINT uq_auth_sessions_token_hash UNIQUE (token_hash)
)

;

CREATE TABLE auth_tokens (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	purpose TEXT NOT NULL,
	user_id UUID,
	email TEXT,
	token_hash TEXT NOT NULL,
	delivery_ciphertext TEXT,
	delivered_at TIMESTAMP WITH TIME ZONE,
	delivery_error_code TEXT,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	used_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_auth_tokens PRIMARY KEY (id),
	CONSTRAINT ck_auth_tokens_ck_auth_tokens_1 CHECK (purpose IN ('invite','email_verify','password_reset')),
	CONSTRAINT fk_auth_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT,
	CONSTRAINT uq_auth_tokens_token_hash UNIQUE (token_hash)
)

;

CREATE TABLE upload_sessions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	paper_id UUID NOT NULL,
	paper_file_id UUID NOT NULL,
	staging_key TEXT NOT NULL,
	status TEXT DEFAULT 'pending' NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expected_size BIGINT NOT NULL,
	expected_sha256 TEXT,
	lease_token UUID,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_upload_sessions PRIMARY KEY (id),
	CONSTRAINT ck_upload_sessions_ck_upload_sessions_5 CHECK (status IN ('pending','validating','completed','failed','expired')),
	CONSTRAINT ck_upload_sessions_ck_upload_sessions_7 CHECK (expected_size > 0),
	CONSTRAINT fk_upload_sessions_12 FOREIGN KEY(workspace_id, paper_id, paper_file_id) REFERENCES paper_files (workspace_id, paper_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_upload_sessions_staging_key UNIQUE (staging_key)
)

;

CREATE TABLE api_idempotency_keys (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	actor_user_id UUID NOT NULL,
	operation TEXT NOT NULL,
	key TEXT NOT NULL,
	request_hash TEXT NOT NULL,
	status TEXT DEFAULT 'completed' NOT NULL,
	response_status INTEGER NOT NULL,
	response_body JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_api_idempotency_keys PRIMARY KEY (id),
	CONSTRAINT ck_api_idempotency_keys_ck_api_idempotency_keys_4 CHECK (length(key) BETWEEN 1 AND 128),
	CONSTRAINT uq_api_idempotency_keys_11 UNIQUE (workspace_id, actor_user_id, operation, key),
	CONSTRAINT fk_api_idempotency_keys_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT,
	CONSTRAINT fk_api_idempotency_keys_actor_user_id_users FOREIGN KEY(actor_user_id) REFERENCES users (id) ON DELETE RESTRICT
)

;

CREATE TABLE outbox_events (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	event_type TEXT NOT NULL,
	aggregate_id UUID NOT NULL,
	payload JSONB DEFAULT '{}'::jsonb NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	dispatched_at TIMESTAMP WITH TIME ZONE,
	attempts INTEGER DEFAULT 0 NOT NULL,
	next_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_outbox_events PRIMARY KEY (id),
	CONSTRAINT ck_outbox_events_ck_outbox_events_7 CHECK (attempts >= 0),
	CONSTRAINT fk_outbox_events_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT
)

;

CREATE TABLE thread_revisions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	revision_no INTEGER NOT NULL,
	title TEXT NOT NULL,
	question TEXT NOT NULL,
	description TEXT NOT NULL,
	status TEXT NOT NULL,
	created_by UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_thread_revisions PRIMARY KEY (id),
	CONSTRAINT ck_thread_revisions_ck_thread_revisions_4 CHECK (revision_no > 0),
	CONSTRAINT uq_thread_revisions_11 UNIQUE (thread_id, revision_no),
	CONSTRAINT uq_thread_revisions_12 UNIQUE (workspace_id, project_id, thread_id, revision_no),
	CONSTRAINT fk_thread_revisions_13 FOREIGN KEY(workspace_id, project_id, thread_id) REFERENCES research_threads (workspace_id, project_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_thread_revisions_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT
)

;

CREATE TABLE hypothesis_revisions (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	hypothesis_id UUID NOT NULL,
	revision_no INTEGER NOT NULL,
	statement TEXT NOT NULL,
	status TEXT NOT NULL,
	evidence_links_snapshot JSONB DEFAULT '[]'::jsonb NOT NULL,
	created_by UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_hypothesis_revisions PRIMARY KEY (id),
	CONSTRAINT ck_hypothesis_revisions_ck_hypothesis_revisions_5 CHECK (revision_no > 0),
	CONSTRAINT uq_hypothesis_revisions_11 UNIQUE (hypothesis_id, revision_no),
	CONSTRAINT uq_hypothesis_revisions_12 UNIQUE (workspace_id, project_id, thread_id, hypothesis_id, revision_no),
	CONSTRAINT fk_hypothesis_revisions_13 FOREIGN KEY(workspace_id, project_id, thread_id, hypothesis_id) REFERENCES hypotheses (workspace_id, project_id, thread_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_hypothesis_revisions_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT
)

;

CREATE TABLE decision_revision_hypothesis_links (
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	decision_revision_id UUID NOT NULL,
	hypothesis_id UUID NOT NULL,
	statement_snapshot TEXT NOT NULL,
	status_snapshot TEXT NOT NULL,
	hypothesis_revision_no INTEGER NOT NULL,
	CONSTRAINT pk_decision_revision_hypothesis_links_8 PRIMARY KEY (workspace_id, decision_revision_id, hypothesis_id),
	CONSTRAINT fk_decision_revision_hypothesis_links_9 FOREIGN KEY(workspace_id, project_id, thread_id, decision_revision_id) REFERENCES decision_revisions (workspace_id, project_id, thread_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_decision_revision_hypothesis_links_10 FOREIGN KEY(workspace_id, project_id, thread_id, hypothesis_id, hypothesis_revision_no) REFERENCES hypothesis_revisions (workspace_id, project_id, thread_id, hypothesis_id, revision_no) ON DELETE RESTRICT
)

;

CREATE TABLE decision_revision_note_links (
	workspace_id UUID NOT NULL,
	project_id UUID NOT NULL,
	thread_id UUID NOT NULL,
	decision_revision_id UUID NOT NULL,
	note_id UUID NOT NULL,
	note_version INTEGER NOT NULL,
	content_snapshot JSONB NOT NULL,
	CONSTRAINT pk_decision_revision_note_links_7 PRIMARY KEY (workspace_id, decision_revision_id, note_id),
	CONSTRAINT ck_decision_revision_note_links_ck_decision_revision_no_9eec CHECK (note_version > 0),
	CONSTRAINT fk_decision_revision_note_links_8 FOREIGN KEY(workspace_id, project_id, thread_id, decision_revision_id) REFERENCES decision_revisions (workspace_id, project_id, thread_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_decision_revision_note_links_9 FOREIGN KEY(workspace_id, note_id) REFERENCES notes (workspace_id, id) ON DELETE RESTRICT
)

;

CREATE TABLE deletion_jobs (
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	workspace_id UUID,
	requested_by UUID,
	status TEXT DEFAULT 'queued' NOT NULL,
	scope TEXT NOT NULL,
	target_id UUID,
	receipt_hash TEXT,
	requested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	lease_owner TEXT,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	attempt_token UUID,
	attempts INTEGER DEFAULT 0 NOT NULL,
	max_attempts INTEGER DEFAULT 3 NOT NULL,
	online_finished_at TIMESTAMP WITH TIME ZONE,
	backup_expiry_at TIMESTAMP WITH TIME ZONE,
	error_code TEXT,
	CONSTRAINT pk_deletion_jobs PRIMARY KEY (id),
	CONSTRAINT ck_deletion_jobs_ck_deletion_jobs_3 CHECK (status IN ('queued','running','succeeded','failed')),
	CONSTRAINT fk_deletion_jobs_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE SET NULL,
	CONSTRAINT fk_deletion_jobs_requested_by_users FOREIGN KEY(requested_by) REFERENCES users (id) ON DELETE SET NULL
)

;

ALTER TABLE research_threads ADD CONSTRAINT fk_fk_thread_current_revision FOREIGN KEY(workspace_id, project_id, id, current_revision) REFERENCES thread_revisions (workspace_id, project_id, thread_id, revision_no) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE hypotheses ADD CONSTRAINT fk_fk_hypothesis_current_revision FOREIGN KEY(workspace_id, project_id, thread_id, id, current_revision) REFERENCES hypothesis_revisions (workspace_id, project_id, thread_id, hypothesis_id, revision_no) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE research_decisions ADD CONSTRAINT fk_fk_decision_current_revision FOREIGN KEY(workspace_id, project_id, thread_id, id, current_revision) REFERENCES decision_revisions (workspace_id, project_id, thread_id, decision_id, revision_no) DEFERRABLE INITIALLY DEFERRED;
CREATE OR REPLACE FUNCTION protect_immutable_history() RETURNS trigger AS $$
BEGIN
    IF current_user <> 'researchos_admin' AND current_user <> 'researchos_cleanup' THEN
        RAISE EXCEPTION 'Immutable research history' USING ERRCODE='42501';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER guard_decision_revision BEFORE UPDATE OR DELETE ON decision_revisions FOR EACH ROW EXECUTE FUNCTION protect_immutable_history();
CREATE TRIGGER guard_decision_evidence BEFORE UPDATE OR DELETE ON decision_revision_evidence_links FOR EACH ROW EXECUTE FUNCTION protect_immutable_history();
CREATE TRIGGER guard_decision_hypothesis BEFORE UPDATE OR DELETE ON decision_revision_hypothesis_links FOR EACH ROW EXECUTE FUNCTION protect_immutable_history();
CREATE TRIGGER guard_decision_note BEFORE UPDATE OR DELETE ON decision_revision_note_links FOR EACH ROW EXECUTE FUNCTION protect_immutable_history();
CREATE TRIGGER guard_thread_revision BEFORE UPDATE OR DELETE ON thread_revisions FOR EACH ROW EXECUTE FUNCTION protect_immutable_history();
CREATE TRIGGER guard_hypothesis_revision BEFORE UPDATE OR DELETE ON hypothesis_revisions FOR EACH ROW EXECUTE FUNCTION protect_immutable_history();
CREATE TRIGGER guard_activity BEFORE UPDATE OR DELETE ON activity_events FOR EACH ROW EXECUTE FUNCTION protect_immutable_history();
CREATE OR REPLACE FUNCTION protect_evidence_source() RETURNS trigger AS $$
BEGIN
    IF ROW(NEW.workspace_id,NEW.project_id,NEW.thread_id,NEW.paper_id,NEW.paper_file_id,NEW.quote_text,NEW.page_start,NEW.page_end,NEW.source_anchor)
        IS DISTINCT FROM ROW(OLD.workspace_id,OLD.project_id,OLD.thread_id,OLD.paper_id,OLD.paper_file_id,OLD.quote_text,OLD.page_start,OLD.page_end,OLD.source_anchor) THEN
        RAISE EXCEPTION 'Evidence source is immutable' USING ERRCODE='42501';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER guard_evidence_source BEFORE UPDATE ON evidence FOR EACH ROW EXECUTE FUNCTION protect_evidence_source();


CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email));
CREATE UNIQUE INDEX uq_projects_one_default ON projects (workspace_id) WHERE is_default = true;
CREATE INDEX ix_projects_title_trgm ON projects USING gin (title gin_trgm_ops);
CREATE INDEX ix_projects_workspace_updated ON projects (workspace_id, updated_at DESC);
CREATE INDEX ix_threads_title_trgm ON research_threads USING gin (title gin_trgm_ops);
CREATE INDEX ix_threads_question_trgm ON research_threads USING gin (question gin_trgm_ops);
CREATE INDEX ix_threads_project_status ON research_threads (workspace_id, project_id, status, updated_at DESC);
CREATE INDEX ix_papers_workspace_created ON papers (workspace_id, created_at DESC);
CREATE INDEX ix_papers_title_trgm ON papers USING gin (title gin_trgm_ops);
CREATE INDEX ix_papers_workspace_reading ON papers (workspace_id, reading_status);
CREATE INDEX ix_papers_workspace_doi ON papers (workspace_id, lower(doi)) WHERE doi IS NOT NULL;
CREATE UNIQUE INDEX uq_paper_files_current ON paper_files (paper_id) WHERE is_current = true;
CREATE INDEX ix_paper_files_hash ON paper_files (workspace_id, sha256) WHERE sha256 IS NOT NULL;
CREATE INDEX ix_paper_files_versions ON paper_files (workspace_id, paper_id, version_no DESC);
CREATE INDEX ix_project_papers_by_paper ON project_papers (workspace_id, paper_id);
CREATE INDEX ix_thread_papers_by_paper ON thread_papers (workspace_id, paper_id);
CREATE INDEX ix_evidence_thread_created ON evidence (workspace_id, thread_id, created_at DESC);
CREATE INDEX ix_evidence_file_page ON evidence (workspace_id, paper_file_id, page_start);
CREATE INDEX ix_hypotheses_thread_status ON hypotheses (workspace_id, thread_id, status);
CREATE INDEX ix_hyp_evidence_reverse ON hypothesis_evidence_links (workspace_id, evidence_id);
CREATE INDEX ix_decisions_thread_updated ON research_decisions (workspace_id, thread_id, updated_at DESC);
CREATE INDEX ix_revision_evidence_reverse ON decision_revision_evidence_links (workspace_id, evidence_id);
CREATE INDEX ix_tasks_workspace_due ON tasks (workspace_id, due_date) WHERE status <> 'done';
CREATE INDEX ix_tasks_title_trgm ON tasks USING gin (title gin_trgm_ops);
CREATE INDEX ix_tasks_decision ON tasks (workspace_id, decision_id) WHERE decision_id IS NOT NULL;
CREATE INDEX ix_tasks_thread ON tasks (workspace_id, thread_id) WHERE thread_id IS NOT NULL;
CREATE INDEX ix_tasks_project_status_due ON tasks (workspace_id, project_id, status, due_date);
CREATE INDEX ix_notes_workspace_updated ON notes (workspace_id, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ix_notes_title_trgm ON notes USING gin (title gin_trgm_ops);
CREATE INDEX ix_notes_search_text_trgm ON notes USING gin (search_text gin_trgm_ops);
CREATE INDEX ix_project_notes_by_note ON project_notes (workspace_id, note_id);
CREATE INDEX ix_thread_notes_by_note ON thread_notes (workspace_id, note_id);
CREATE INDEX ix_note_papers_by_paper ON note_papers (workspace_id, paper_id);
CREATE INDEX ix_note_evidence_reverse ON note_evidence_links (workspace_id, evidence_id);
CREATE INDEX ix_activity_thread_time ON activity_events (workspace_id, thread_id, created_at DESC);
CREATE INDEX ix_activity_workspace_time ON activity_events (workspace_id, created_at DESC, id DESC);
CREATE INDEX ix_activity_project_time ON activity_events (workspace_id, project_id, created_at DESC);
CREATE INDEX ix_processing_jobs_queue ON processing_jobs (status, created_at) WHERE status IN ('queued', 'running');
CREATE UNIQUE INDEX uq_processing_one_active ON processing_jobs (paper_file_id, job_type) WHERE status IN ('queued', 'running');
CREATE INDEX ix_exports_workspace_created ON export_jobs (workspace_id, created_at DESC);
CREATE INDEX ix_session_token_active ON auth_sessions (token_hash) WHERE revoked_at IS NULL;
CREATE INDEX ix_upload_pending ON upload_sessions (expires_at) WHERE status IN ('pending','validating');
CREATE INDEX ix_outbox_pending ON outbox_events (next_attempt_at, created_at) WHERE dispatched_at IS NULL;
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_projects_updated
BEFORE UPDATE ON projects
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_threads_updated
BEFORE UPDATE ON research_threads
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_papers_updated
BEFORE UPDATE ON papers
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_evidence_updated
BEFORE UPDATE ON evidence
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_hypotheses_updated
BEFORE UPDATE ON hypotheses
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_decisions_updated
BEFORE UPDATE ON research_decisions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_tasks_updated
BEFORE UPDATE ON tasks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_notes_updated
BEFORE UPDATE ON notes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_profiles_updated
BEFORE UPDATE ON research_profiles
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
