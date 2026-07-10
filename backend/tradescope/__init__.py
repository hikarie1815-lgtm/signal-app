"""TradeScope — 裁量トレード支援ターミナル（signal-desk アドオン）。

- api.py:   データ配信API（GMOコイン為替・Binance PAXG金価格の中継）+ /app 配信
- watch.py: 24時間監視エンジン（マルチタイムフレーム分析 → LINE通知）
- static/tradescope.html: ブラウザ版TradeScope本体
"""
