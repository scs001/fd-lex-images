"""识律电子签（change lex-contract-esignature）。

底座=编排层（状态机/哈希锚定/台账/出证），随私有化包进机房；
签署腿（实名/CA/TSA/出证）=可插拔 adapter（adapter.py，厂商承担持牌义务）。
红线：签哈希不签全文（spec）＋任何自动化入口不代签（spec）。
"""

from .models import EsignBase, EsignDocument, EsignEvent, EsignSigner, EsignTask, ensure_esign_schema
from .routes import console_router, signer_router

__all__ = [
    "EsignBase",
    "EsignDocument",
    "EsignEvent",
    "EsignSigner",
    "EsignTask",
    "console_router",
    "ensure_esign_schema",
    "signer_router",
]
