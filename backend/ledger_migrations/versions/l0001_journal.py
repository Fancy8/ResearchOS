"""An append-only journal and separately protected current head outside business backups."""

from alembic import op

revision = "l0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("""
        CREATE TABLE public.ledger_heads (
            source_id text PRIMARY KEY CHECK (source_id ~ '^[0-9a-f]{64}$'),
            sequence bigint NOT NULL CHECK (sequence >= 0),
            entry_hash text NOT NULL CHECK (entry_hash ~ '^[0-9a-f]{64}$'),
            signature text NOT NULL CHECK (signature ~ '^[0-9a-f]{64}$')
        )
    """)
    op.execute("""
        CREATE TABLE public.ledger_entries (
            source_id text NOT NULL REFERENCES public.ledger_heads(source_id),
            sequence bigint NOT NULL CHECK (sequence > 0),
            job_id uuid NOT NULL,
            payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
            previous_hash text NOT NULL CHECK (previous_hash ~ '^[0-9a-f]{64}$'),
            entry_hash text NOT NULL CHECK (entry_hash ~ '^[0-9a-f]{64}$'),
            signature text NOT NULL CHECK (signature ~ '^[0-9a-f]{64}$'),
            head_signature text NOT NULL CHECK (head_signature ~ '^[0-9a-f]{64}$'),
            recorded_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(source_id, sequence),
            UNIQUE(source_id, job_id)
        )
    """)
    op.execute("""
        CREATE FUNCTION public.register_ledger_source(source text, signed_zero text)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,pg_temp AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended('ledger:'||source,0));
            INSERT INTO public.ledger_heads VALUES(source,0,repeat('0',64),signed_zero)
                ON CONFLICT DO NOTHING;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION public.advance_ledger_head() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        DECLARE head public.ledger_heads;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended('ledger:'||NEW.source_id,0));
            SELECT * INTO STRICT head FROM public.ledger_heads WHERE source_id=NEW.source_id FOR UPDATE;
            IF NEW.sequence <> head.sequence+1 OR NEW.previous_hash <> head.entry_hash
               OR NEW.payload->>'job_id' IS DISTINCT FROM NEW.job_id::text
            THEN RAISE EXCEPTION 'LEDGER_SEQUENCE_CONFLICT'; END IF;
            UPDATE public.ledger_heads SET sequence=NEW.sequence,entry_hash=NEW.entry_hash,
                signature=NEW.head_signature WHERE source_id=NEW.source_id;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER ledger_append BEFORE INSERT ON public.ledger_entries FOR EACH ROW EXECUTE FUNCTION public.advance_ledger_head()"
    )
    op.execute(
        "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC,researchos_ledger_writer,researchos_ledger_reader"
    )
    op.execute("GRANT USAGE ON SCHEMA public TO researchos_ledger_writer,researchos_ledger_reader")
    op.execute(
        "GRANT SELECT ON public.ledger_entries,public.ledger_heads TO researchos_ledger_writer,researchos_ledger_reader"
    )
    op.execute("GRANT INSERT ON public.ledger_entries TO researchos_ledger_writer")
    op.execute(
        "REVOKE ALL ON FUNCTION public.register_ledger_source(text,text),public.advance_ledger_head() FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.register_ledger_source(text,text) TO researchos_ledger_writer"
    )


def downgrade():
    raise RuntimeError("Deletion journal migrations are forward only")
