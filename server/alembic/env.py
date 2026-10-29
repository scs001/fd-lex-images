"""Alembic 环境：目标元数据=计量/账本/控制台/电子签四域 ORM 声明的并集。

连接串优先级：``-x db_url=...`` > ``DATABASE_URL`` env > 默认 sqlite 开发库。
生产（PG）由部署侧以 DATABASE_URL 注入；测试/本地可显式 -x 指定。
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from fd_lex_api.billing import Base as BillingBase
from fd_lex_api.console_api.models import ConsoleBase
from fd_lex_api.esignature.models import EsignBase
from fd_lex_api.metering.db import MeteringBase
from fd_lex_api.metering import models as _metering_models  # noqa: F401 —— 注册映射
from fd_lex_api.billing import models as _billing_models  # noqa: F401
from fd_lex_api.console_api import models as _console_models  # noqa: F401
from fd_lex_api.esignature import models as _esignature_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

x_args = context.get_x_argument(as_dictionary=True)
database_url = (
    x_args.get("db_url")
    or os.environ.get("DATABASE_URL")
    or "sqlite:///./fd_lex_dev.db"
)
config.set_main_option("sqlalchemy.url", database_url)


class _MergedMeta:
    """三域 metadata 的并集视图（alembic autogenerate 读 tables/sorted_tables）。"""

    def __init__(self) -> None:
        from sqlalchemy import MetaData

        merged = MetaData()
        for base in (MeteringBase, BillingBase, ConsoleBase, EsignBase):
            for table in base.metadata.tables.values():
                if table.key not in merged.tables:
                    table.to_metadata(merged)
        self._merged = merged
        self.tables = merged.tables

    @property
    def sorted_tables(self):
        return self._merged.sorted_tables


target_metadata = _MergedMeta()


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 脚本，不连库。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直连目标库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
