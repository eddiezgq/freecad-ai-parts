-- 人工复核队列（ADR-0023）
CREATE TABLE extractions (
    id              bigserial PRIMARY KEY,
    doc             text NOT NULL,
    sha256          text NOT NULL,
    pages           integer NOT NULL CHECK (pages >= 1),
    category        text NOT NULL,
    vendor          text,
    model           text,
    llm_model       text NOT NULL,
    prompt_version  text NOT NULL,
    simulated       boolean NOT NULL DEFAULT false,
    result          jsonb NOT NULL,
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'committed')),
    component_id    text,
    created_by      text NOT NULL CHECK (btrim(created_by) <> ''),
    created_at      timestamptz NOT NULL DEFAULT now(),
    committed_by    text,
    committed_at    timestamptz,
    UNIQUE (doc, sha256, llm_model, prompt_version),
    CHECK ((status = 'committed') = (component_id IS NOT NULL AND committed_at IS NOT NULL))
);

CREATE TABLE review_items (
    id              bigserial PRIMARY KEY,
    extraction_id   bigint NOT NULL REFERENCES extractions (id) ON DELETE RESTRICT,
    kind            text NOT NULL CHECK (kind IN ('item', 'rejected', 'missing', 'added')),
    target          text,
    proposed        jsonb,
    printed         jsonb,
    issues          jsonb NOT NULL DEFAULT '[]',
    reasons         text[] NOT NULL DEFAULT '{}',
    needs_review    boolean NOT NULL
);
CREATE INDEX review_items_extraction_idx ON review_items (extraction_id);

CREATE TABLE review_decisions (
    id              bigserial PRIMARY KEY,
    item_id         bigint NOT NULL REFERENCES review_items (id) ON DELETE RESTRICT,
    action          text NOT NULL CHECK (action IN ('accept', 'correct', 'reject', 'dismiss', 'absent')),
    value           jsonb,
    error_category  text NOT NULL CHECK (error_category IN (
                        'none', 'wrong_value', 'wrong_unit', 'wrong_target', 'wrong_page', 'wrong_condition',
                        'enum_mapping', 'hallucinated', 'missed', 'false_reject', 'withdrawn', 'other')),
    reviewer        text NOT NULL CHECK (btrim(reviewer) <> ''),
    note            text,
    decided_at      timestamptz NOT NULL DEFAULT now(),
    CHECK ((action = 'correct') = (value IS NOT NULL))
);
CREATE INDEX review_decisions_item_idx ON review_decisions (item_id, id);

-- 复核依据与决定只增不改（ADR-0023）
CREATE FUNCTION review_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% 只允许追加，不允许修改、删除或清空', TG_TABLE_NAME;
END;
$$;
CREATE TRIGGER review_decisions_no_update_delete
    BEFORE UPDATE OR DELETE ON review_decisions FOR EACH ROW EXECUTE FUNCTION review_append_only();
CREATE TRIGGER review_decisions_no_truncate
    BEFORE TRUNCATE ON review_decisions FOR EACH STATEMENT EXECUTE FUNCTION review_append_only();
CREATE TRIGGER review_items_no_update_delete
    BEFORE UPDATE OR DELETE ON review_items FOR EACH ROW EXECUTE FUNCTION review_append_only();
CREATE TRIGGER review_items_no_truncate
    BEFORE TRUNCATE ON review_items FOR EACH STATEMENT EXECUTE FUNCTION review_append_only();
CREATE TRIGGER extractions_no_truncate
    BEFORE TRUNCATE ON extractions FOR EACH STATEMENT EXECUTE FUNCTION review_append_only();

-- 抽取只允许从 open 变为 committed（记下组件 id、提交人与时间），其余字段不可改，不可删除
CREATE FUNCTION extractions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'extractions 不允许删除';
    END IF;
    IF OLD.status <> 'open' OR NEW.status <> 'committed'
       OR (to_jsonb(NEW) - ARRAY['status', 'component_id', 'committed_by', 'committed_at'])
          IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'component_id', 'committed_by', 'committed_at']) THEN
        RAISE EXCEPTION 'extractions 只允许从 open 提交为 committed';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER extractions_guard_update_delete
    BEFORE UPDATE OR DELETE ON extractions FOR EACH ROW EXECUTE FUNCTION extractions_guard();
