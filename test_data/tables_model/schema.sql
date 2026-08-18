CREATE SCHEMA dc;
CREATE SCHEMA tech;
CREATE TABLE dc.alias (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(1000) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now(),
    is_deleted boolean DEFAULT false NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.column_cat (
    id bigint NOT NULL,
    table_id bigint NOT NULL,
    name character varying(256) NOT NULL,
    alias_id bigint NOT NULL,
    column_type_id bigint NOT NULL,
    description character varying(1000) NOT NULL,
    calculation_type_id bigint NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    show_in_ui boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.column_type (
    id bigint NOT NULL,
    name character varying(128) NOT NULL,
    description character varying(1000) NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.calculation_type (
    id bigint NOT NULL,
    name character varying(52) NOT NULL,
    description character varying(1000) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL
);
CREATE TABLE dc.database_calculation (
    id bigint NOT NULL,
    database_cat_id bigint NOT NULL,
    calculation_type_id bigint NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.database_cat (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    host_id bigint NOT NULL,
    database_type_id bigint NOT NULL,
    description character varying(1000) NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.database_type (
    id bigint NOT NULL,
    name character varying(128) NOT NULL,
    db_version character varying(512) NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.domain_cat (
    id bigint NOT NULL,
    domain_name character varying(100) NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.following_calculation (
    id bigint NOT NULL,
    column_cat_id bigint NOT NULL,
    calculation_type_id bigint NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.group_levels (
    id bigint NOT NULL,
    column_id bigint NOT NULL,
    parent_column_id bigint NOT NULL,
    level smallint NOT NULL,
    description character varying(1000) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.has_to_group (
    id bigint NOT NULL,
    column_id_a bigint NOT NULL,
    column_id_b bigint NOT NULL,
    description character varying(1000) NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.host (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(1000) NOT NULL,
    host_env character varying(255) NOT NULL,
    port_env character varying(255) NOT NULL,
    username_env character varying(255) NOT NULL,
    password_env character varying(255) NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.schema_cat (
    id bigint NOT NULL,
    database_id bigint NOT NULL,
    name character varying(128) NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.table_cat (
    id bigint NOT NULL,
    name character varying(128) NOT NULL,
    description character varying(2000) NOT NULL,
    schema_id bigint NOT NULL,
    table_type_id bigint NOT NULL,
    domain_id bigint NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    is_get_dict bool DEFAULT false NOT NULL,
    user_id bigint NOT NULL
);
CREATE TABLE dc.table_type (
    id bigint NOT NULL,
    name character varying(128) NOT NULL,
    description character varying(1000) NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    user_id bigint NOT NULL
);
create table dc."user"
(
    id          bigserial
        constraint user_pk
            primary key,
    name        varchar(512)            not null
        constraint user_name_unique
            unique,
    created_at  timestamp default now() not null,
    updated_at  timestamp default now() not null,
    is_deleted  boolean   default false not null,
    external_id uuid                    not null
        constraint user_external_id_unique
            unique
);
