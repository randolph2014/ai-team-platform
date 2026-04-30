-- Settings: 存储 runtimes / agents / pipeline / runner 等配置
-- DB 优先、文件兜底：API 层读写 DB，YAML 文件仅作备份。
CREATE TABLE IF NOT EXISTS settings (
    key  TEXT PRIMARY KEY,           -- 'default' 全局配置，未来可扩展按项目
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
