CREATE TABLE auth_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE auth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purpose TEXT NOT NULL CHECK (purpose IN ('invite','email_verify','password_reset')),
    user_id UUID REFERENCES users(id) ON DELETE RESTRICT,
    email TEXT,
    token_hash TEXT NOT NULL UNIQUE,
    delivery_ciphertext TEXT,
    delivered_at TIMESTAMPTZ,
    delivery_error_code TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE upload_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    paper_id UUID NOT NULL,
    paper_file_id UUID NOT NULL,
    staging_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','validating','completed','failed','expired')),
    expires_at TIMESTAMPTZ NOT NULL,
    expected_size BIGINT NOT NULL CHECK (expected_size > 0),
    expected_sha256 TEXT,
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (workspace_id,paper_id,paper_file_id) REFERENCES paper_files(workspace_id,paper_id,id) ON DELETE RESTRICT
);
CREATE TABLE api_idempotency_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    actor_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    operation TEXT NOT NULL,
    key TEXT NOT NULL CHECK (length(key) BETWEEN 1 AND 128),
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    response_status INTEGER NOT NULL,
    response_body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE (workspace_id,actor_user_id,operation,key)
);
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    aggregate_id UUID NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE thread_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    project_id UUID NOT NULL,
    thread_id UUID NOT NULL,
    revision_no INTEGER NOT NULL CHECK (revision_no > 0),
    title TEXT NOT NULL,
    question TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (thread_id,revision_no),
    UNIQUE (workspace_id,project_id,thread_id,revision_no),
    FOREIGN KEY (workspace_id,project_id,thread_id) REFERENCES research_threads(workspace_id,project_id,id) ON DELETE RESTRICT
);
CREATE TABLE hypothesis_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    project_id UUID NOT NULL,
    thread_id UUID NOT NULL,
    hypothesis_id UUID NOT NULL,
    revision_no INTEGER NOT NULL CHECK (revision_no > 0),
    statement TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_links_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (hypothesis_id,revision_no),
    UNIQUE (workspace_id,project_id,thread_id,hypothesis_id,revision_no),
    FOREIGN KEY (workspace_id,project_id,thread_id,hypothesis_id) REFERENCES hypotheses(workspace_id,project_id,thread_id,id) ON DELETE RESTRICT
);
CREATE TABLE decision_revision_hypothesis_links (
    workspace_id UUID NOT NULL,
    project_id UUID NOT NULL,
    thread_id UUID NOT NULL,
    decision_revision_id UUID NOT NULL,
    hypothesis_id UUID NOT NULL,
    statement_snapshot TEXT NOT NULL,
    status_snapshot TEXT NOT NULL,
    hypothesis_revision_no INTEGER NOT NULL,
    PRIMARY KEY (workspace_id,decision_revision_id,hypothesis_id),
    FOREIGN KEY (workspace_id,project_id,thread_id,decision_revision_id) REFERENCES decision_revisions(workspace_id,project_id,thread_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id,project_id,thread_id,hypothesis_id,hypothesis_revision_no) REFERENCES hypothesis_revisions(workspace_id,project_id,thread_id,hypothesis_id,revision_no) ON DELETE RESTRICT
);
CREATE TABLE decision_revision_note_links (
    workspace_id UUID NOT NULL,
    project_id UUID NOT NULL,
    thread_id UUID NOT NULL,
    decision_revision_id UUID NOT NULL,
    note_id UUID NOT NULL,
    note_version INTEGER NOT NULL CHECK (note_version > 0),
    content_snapshot JSONB NOT NULL,
    PRIMARY KEY (workspace_id,decision_revision_id,note_id),
    FOREIGN KEY (workspace_id,project_id,thread_id,decision_revision_id) REFERENCES decision_revisions(workspace_id,project_id,thread_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id,note_id) REFERENCES notes(workspace_id,id) ON DELETE RESTRICT
);
CREATE TABLE deletion_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
    requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed')),
    scope TEXT NOT NULL,
    target_id UUID,
    receipt_hash TEXT,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    attempt_token UUID,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    online_finished_at TIMESTAMPTZ,
    backup_expiry_at TIMESTAMPTZ,
    error_code TEXT
);
-- POST_TABLE_CONSTRAINTS
ALTER TABLE decision_revisions ADD CONSTRAINT uq_decision_revision_pointer UNIQUE (workspace_id,project_id,thread_id,decision_id,revision_no);
ALTER TABLE research_decisions ADD CONSTRAINT fk_decision_current_revision FOREIGN KEY (workspace_id,project_id,thread_id,id,current_revision) REFERENCES decision_revisions(workspace_id,project_id,thread_id,decision_id,revision_no) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE research_threads ADD CONSTRAINT fk_thread_current_revision FOREIGN KEY (workspace_id,project_id,id,current_revision) REFERENCES thread_revisions(workspace_id,project_id,thread_id,revision_no) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE hypotheses ADD CONSTRAINT fk_hypothesis_current_revision FOREIGN KEY (workspace_id,project_id,thread_id,id,current_revision) REFERENCES hypothesis_revisions(workspace_id,project_id,thread_id,hypothesis_id,revision_no) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE tasks ADD CONSTRAINT ck_task_source_revision CHECK ((decision_id IS NULL) = (source_revision_no IS NULL));
ALTER TABLE tasks ADD CONSTRAINT fk_task_source_revision FOREIGN KEY (workspace_id,project_id,thread_id,decision_id,source_revision_no) REFERENCES decision_revisions(workspace_id,project_id,thread_id,decision_id,revision_no) ON DELETE RESTRICT;
ALTER TABLE projects ADD CONSTRAINT ck_project_archive_time CHECK ((status='archived')=(archived_at IS NOT NULL));
ALTER TABLE research_threads ADD CONSTRAINT ck_thread_archive_time CHECK ((status='archived')=(archived_at IS NOT NULL));
CREATE INDEX ix_outbox_pending ON outbox_events(next_attempt_at,created_at) WHERE dispatched_at IS NULL;
CREATE INDEX ix_session_token_active ON auth_sessions(token_hash) WHERE revoked_at IS NULL;
CREATE INDEX ix_upload_pending ON upload_sessions(expires_at) WHERE status IN ('pending','validating');
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
