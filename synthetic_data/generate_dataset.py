"""
generate_dataset.py — 命令列批量生成 TASA A2.2 標記 TLE 資料集

用法:
  python synthetic_data/generate_dataset.py
  python synthetic_data/generate_dataset.py --n_maneuver 25000 --n_no_maneuver 25000

輸出:
  data/maneuvers/synthetic_tle_dataset.parquet   完整資料集（含 TLE 文字）
  data/maneuvers/synthetic_tle_features.parquet  僅特徵欄位（無 TLE 文字，供 ML 直接讀取）
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from synthetic_tle import NoiseLevel, batch_generate

OUT_DIR = ROOT / "data" / "maneuvers"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FEATURE_COLS = [
    "norad_id", "label", "maneuver_type", "dv_m_s", "delta_t_days",
    "net_da_km", "net_di_deg", "pre_sma_mean", "post_sma_mean",
    "alt_km", "inc_deg",
]


def main(args: argparse.Namespace) -> None:
    print(f"[generate_dataset] 生成 {args.n_maneuver} 機動 + {args.n_no_maneuver} 無機動 樣本")
    print(f"  ΔV 範圍：{args.dv_min:.3f} – {args.dv_max:.1f} m/s")
    print(f"  雜訊等級：{args.noise_level}")
    print(f"  亂數種子：{args.seed}")
    print()

    total = args.n_maneuver + args.n_no_maneuver
    last_pct = [0]
    t0 = time.time()

    def progress_cb(pct: float):
        p = int(pct * 100)
        if p >= last_pct[0] + 5:
            elapsed = time.time() - t0
            eta     = elapsed / pct * (1 - pct) if pct > 0 else 0
            print(f"  [{p:3d}%] {int(pct * total):>6}/{total}  elapsed={elapsed:.0f}s  ETA={eta:.0f}s")
            last_pct[0] = p

    noise = NoiseLevel(args.noise_level)

    df = batch_generate(
        n_maneuver    = args.n_maneuver,
        n_no_maneuver = args.n_no_maneuver,
        dv_range_m_s  = (args.dv_min, args.dv_max),
        n_before      = args.n_before,
        n_after       = args.n_after,
        dt_days       = args.dt_days,
        noise_level   = noise,
        seed          = args.seed,
        progress_cb   = progress_cb,
    )

    elapsed = time.time() - t0
    print(f"\n[完成] {len(df)} 筆樣本，耗時 {elapsed:.1f}s")

    # 統計
    n_pos = int(df["label"].sum())
    n_neg = int((df["label"] == 0).sum())
    print(f"  機動樣本：{n_pos}  無機動：{n_neg}  比例：{n_pos/len(df):.1%}")
    print(f"  Δa 範圍（機動）：{df[df['label']==1]['net_da_km'].min():.4f} ~ "
          f"{df[df['label']==1]['net_da_km'].max():.4f} km")
    print(f"  ΔV 範圍（機動）：{df[df['label']==1]['dv_m_s'].min():.4f} ~ "
          f"{df[df['label']==1]['dv_m_s'].max():.4f} m/s")

    # 儲存完整資料集（含 TLE 文字）
    out_full = OUT_DIR / "synthetic_tle_dataset.parquet"
    df.to_parquet(out_full, index=False)
    print(f"\n[DONE] 完整資料集 → {out_full}  ({out_full.stat().st_size/1024:.0f} KB)")

    # 儲存僅特徵欄位（ML 直接讀取）
    out_feat = OUT_DIR / "synthetic_tle_features.parquet"
    df[FEATURE_COLS].to_parquet(out_feat, index=False)
    print(f"[DONE] 特徵欄位  → {out_feat}  ({out_feat.stat().st_size/1024:.0f} KB)")

    # 分布摘要
    print("\n■ 機動類型分布：")
    for mtype, cnt in df[df["label"] == 1]["maneuver_type"].value_counts().items():
        print(f"    {mtype:<12} : {cnt:>5} ({cnt/n_pos:.1%})")

    print("\n■ 高度分布：")
    for (lo, hi), cnt in (
        df.groupby(
            df["alt_km"].apply(
                lambda x: "sub400" if x < 400 else ("400-600" if x < 600 else "600plus")
            )
        )["norad_id"].count().items()
    ):
        print(f"    {lo:<8} : {cnt}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TASA A2.2 TLE 合成資料集生成器")
    parser.add_argument("--n_maneuver",    type=int,   default=25000)
    parser.add_argument("--n_no_maneuver", type=int,   default=25000)
    parser.add_argument("--dv_min",        type=float, default=0.001, help="最小 ΔV [m/s]")
    parser.add_argument("--dv_max",        type=float, default=50.0,  help="最大 ΔV [m/s]")
    parser.add_argument("--n_before",      type=int,   default=15,    help="機動前 TLE 數")
    parser.add_argument("--n_after",       type=int,   default=15,    help="機動後 TLE 數")
    parser.add_argument("--dt_days",       type=float, default=3.0,   help="TLE 間隔天數")
    parser.add_argument("--noise_level",   type=str,   default="medium",
                        choices=["low", "medium", "high"])
    parser.add_argument("--seed",          type=int,   default=42)
    main(parser.parse_args())
