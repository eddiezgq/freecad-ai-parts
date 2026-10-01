-- 组件知识库初始结构（ADR-0018）
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE components (
    id              text PRIMARY KEY,
    category        text NOT NULL,
    vendor          text NOT NULL,
    model           text NOT NULL,
    series          text,
    status          text NOT NULL CHECK (status IN ('active', 'discontinued')),
    superseded_by   text,
    license         text NOT NULL,
    envelope        jsonb NOT NULL,
    vendor_cad_url  text,
    note            text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX components_category_idx ON components (category);

CREATE TABLE params (
    component_id    text NOT NULL REFERENCES components (id) ON DELETE CASCADE,
    name            text NOT NULL,
    value           jsonb NOT NULL,
    value_num       double precision,
    min_num         double precision,
    max_num         double precision,
    nominal_num     double precision,
    method          text NOT NULL,
    confidence      double precision NOT NULL,
    reviewed        boolean NOT NULL,
    source_doc      text,
    PRIMARY KEY (component_id, name)
);
CREATE INDEX params_name_idx ON params (name);

CREATE TABLE ports (
    component_id    text NOT NULL REFERENCES components (id) ON DELETE CASCADE,
    port_id         text NOT NULL,
    pos             integer NOT NULL,
    type            text NOT NULL,
    dir             text NOT NULL,
    motion          text,
    frame           jsonb,
    spec            jsonb NOT NULL,
    note            text,
    PRIMARY KEY (component_id, port_id)
);
CREATE INDEX ports_type_idx ON ports (type);

CREATE TABLE change_log (
    id              bigserial PRIMARY KEY,
    component_id    text NOT NULL,
    scope           text NOT NULL CHECK (scope IN ('component', 'param', 'port')),
    name            text NOT NULL,
    old_value       jsonb,
    new_value       jsonb,
    reason          text NOT NULL,
    changed_by      text NOT NULL,
    changed_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX change_log_component_idx ON change_log (component_id);
