# 森の川と黒猫

『Flow』の雰囲気を参考にしたオリジナルの静止画シーンです。映画から取得したモデルやテクスチャは使用していません。

- `flow_forest.blend`: 編集・レンダリング用のシーン。
- `flow_forest_preview.png`: 確認用レンダー。
- `create_flow_scene.py`: シーンを再生成するBlender Pythonスクリプト。

Blenderで `flow_forest.blend` を開き、テンキー0でカメラ表示、F12でレンダリングできます。猫の部品は `Cat`、樹木は `Tree` の名前で検索できます。

再生成する場合はこのフォルダでPowerShellから実行します。既存の `flow_forest.blend` とプレビューは上書きされます。

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --python create_flow_scene.py
```

Cycles・デノイズ有効。解像度設定は1440×960、出力倍率75%（1080×720）。最終出力ではBlenderの出力プロパティで倍率を100%に変更できます。
