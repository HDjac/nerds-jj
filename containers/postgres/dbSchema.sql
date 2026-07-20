CREATE USER created_instances_user WITH PASSWORD 'oSYcoJcasKmtDZa2EAhM3igiSqrGrUtD';
CREATE USER insert_user WITH PASSWORD 'paIvTiE0vevzF56eDYkBfGmc12QDsyae';
CREATE USER read_only_user WITH PASSWORD 'MKTL7RYymrfwLAZQnQI3gXBUZwyd2Qpn';

CREATE TABLE IF NOT EXISTS "createdInstances" (
    id serial primary key,
    userid text,
    ip text NOT NULL,
    origin integer,
    time timestamp without time zone,
    session_start TIMESTAMPTZ,
    ec2instance text,
    category integer,
    condition integer,
    instanceid text,
    finished boolean DEFAULT false,
    heartbeat timestamp without time zone default now(),
    "instanceTerminated" boolean DEFAULT false
);

DROP TABLE IF EXISTS "conditions";
CREATE TABLE "conditions" (category integer, condition integer, filename text, hash text, PRIMARY KEY(category, condition));

CREATE TABLE IF NOT EXISTS "copy_pasted_code" (
    id serial primary key,
    userid character varying,
    token character varying,
    tasknum character varying,
    cellid character varying,
    code character varying,
    "time" timestamp without time zone
);
    
CREATE TABLE IF NOT EXISTS "jupyter" (
    id serial primary key,
    userid character varying,
    token character varying,
    code json,
    "time" json,
    status character varying(1),
    date timestamp without time zone
);

CREATE TABLE IF NOT EXISTS "firefox_history" (
    id serial primary key,
    userid character varying,
    token character varying,
    visit_time timestamp without time zone,
    url TEXT NOT NULL,
    from_url TEXT,
    visit_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS "llm_prompts" (
    id serial primary key,
    userid character varying,
    token character varying,
    service character varying,
    model character varying,
    prompt text,
    url text,
    client_timestamp character varying,
    "time" timestamp without time zone default now()
);

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
ALTER TABLE "createdInstances" OWNER TO created_instances_user;
ALTER TABLE "jupyter" OWNER TO insert_user;
ALTER TABLE "copy_pasted_code" OWNER TO insert_user;
ALTER TABLE "firefox_history" OWNER TO insert_user;
ALTER TABLE "llm_prompts" OWNER TO insert_user;
GRANT SELECT ON "conditions" TO created_instances_user;
GRANT SELECT ON "conditions" TO insert_user;
GRANT SELECT ON "conditions" TO read_only_user;
GRANT SELECT,UPDATE,INSERT ON "createdInstances" TO created_instances_user;
GRANT SELECT,UPDATE ON "createdInstances" TO insert_user;
GRANT SELECT ON "createdInstances" TO read_only_user;
GRANT INSERT ON "jupyter" TO insert_user;
GRANT SELECT ON "jupyter" TO read_only_user;
GRANT INSERT ON "copy_pasted_code" TO insert_user;
GRANT INSERT,UPDATE,SELECT ON "firefox_history" TO insert_user;
GRANT SELECT ON "firefox_history" to read_only_user;
GRANT INSERT,SELECT ON "llm_prompts" TO insert_user;
GRANT SELECT ON "llm_prompts" to read_only_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public to insert_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public to read_only_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public to created_instances_user;
